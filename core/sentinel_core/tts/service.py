"""返答の読み上げ(仕様 §18.4)。

ChatService が LLM のトークンを流すたびに `Utterance.feed()` へ渡す。文が閉じたら
合成待ちの列に積み、1本の作業タスクが順番に合成して `audio_chunk` イベントで画面へ送る。
画面は受け取った順に再生し、同時にアバター窓へ口パクのタイムラインを渡す。

- 新しいターンが始まったら、前のターンの未合成の文は捨てる(話の途中で次の返事が来たとき、
  古い返事を最後まで読み続けないように)。画面側も古いターンの音声は捨てる
- エンジンに繋がらないときは、そのターンで1回だけ通知し、チャット自体は止めない
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
from dataclasses import dataclass
from typing import Any

from sentinel_core.character.registry import CharacterRegistry
from sentinel_core.events import EventHub
from sentinel_core.memory.store import Store
from sentinel_core.tts.base import Speech, TTSEngine, TTSUnavailableError, VoiceParams
from sentinel_core.tts.sentences import SentenceSplitter

ENABLED_KEY = "voice.enabled"
SPEAKER_KEY = "voice.speaker."  # + キャラID(汎用モードは "none")


def _speaker_key(char_id: str | None) -> str:
    return SPEAKER_KEY + (char_id or "none")


def speech_payload(speech: Speech) -> dict[str, Any]:
    """WS / HTTP で返す形。WAV は base64 にして JSON に載せる(仕様 §7 audio_chunk)。"""
    return {
        "format": "wav",
        "data_b64": base64.b64encode(speech.wav).decode("ascii"),
        "duration": round(speech.duration, 3),
        "visemes": [v.to_json() for v in speech.visemes] if speech.visemes is not None else None,
    }


@dataclass
class _Job:
    turn: int
    session_id: str
    seq: int
    text: str  # None ではない文。ターンの終わりは done=True で表す
    voice: VoiceParams
    done: bool = False


class Utterance:
    """1ターン分の読み上げ。トークンを受けて文単位で合成待ちに積む。"""

    def __init__(self, service: SpeechService, turn: int, session_id: str, voice: VoiceParams):
        self._service = service
        self._turn = turn
        self._session_id = session_id
        self._voice = voice
        self._splitter = SentenceSplitter()
        self._seq = 0

    def feed(self, delta: str) -> None:
        for s in self._splitter.feed(delta):
            self._push(s)

    def finish(self) -> None:
        for s in self._splitter.flush():
            self._push(s)
        self._service.enqueue(
            _Job(self._turn, self._session_id, self._seq, "", self._voice, done=True)
        )

    def _push(self, text: str) -> None:
        self._service.enqueue(_Job(self._turn, self._session_id, self._seq, text, self._voice))
        self._seq += 1


class SpeechService:
    def __init__(
        self,
        engine: TTSEngine | None,
        store: Store,
        characters: CharacterRegistry,
        hub: EventHub,
        defaults: dict[str, Any],
    ) -> None:
        """defaults は config の voice 節(enabled / speaker_id / speed / pitch)。"""
        self._engine = engine
        self._store = store
        self._characters = characters
        self._hub = hub
        self._defaults = defaults
        self._queue: asyncio.Queue[_Job] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._turn = 0
        self._failed_turn = -1

    # --- 設定(画面の「声」から変える。kv に保存して再起動後も保つ)---

    @property
    def engine_name(self) -> str | None:
        return self._engine.name if self._engine else None

    @property
    def enabled(self) -> bool:
        saved = self._store.get_state(ENABLED_KEY)
        if saved is None:
            return bool(self._defaults.get("enabled", False))
        return saved == "1"

    def set_enabled(self, on: bool) -> None:
        self._store.set_state(ENABLED_KEY, "1" if on else "0")

    def chosen_speaker(self) -> int | None:
        """今のキャラの声: 画面で選んだもの > Pack の voice.speaker_id > config の speaker_id。"""
        saved = self._store.get_state(_speaker_key(self._characters.active_id))
        if saved:
            return int(saved)
        pack = self._characters.active_pack()
        for src in (pack.voice if pack else {}, self._defaults):
            if src.get("speaker_id") is not None:
                return int(src["speaker_id"])
        return None

    def set_speaker(self, speaker: int | None) -> None:
        key = _speaker_key(self._characters.active_id)
        self._store.set_state(key, "" if speaker is None else str(speaker))

    def voice(self, speaker: int | None = None) -> VoiceParams:
        pack = self._characters.active_pack()
        src: dict[str, Any] = {**self._defaults, **(pack.voice if pack else {})}
        return VoiceParams(
            speaker=speaker if speaker is not None else self.chosen_speaker(),
            speed=float(src.get("speed", 1.0)),
            pitch=float(src.get("pitch", 0.0)),
            intonation=float(src.get("intonation", 1.0)),
            volume=float(src.get("volume", 1.0)),
        )

    async def status(self) -> dict[str, Any]:
        available = await self._engine.is_available() if self._engine else False
        return {
            "enabled": self.enabled,
            "engine": self.engine_name,
            "available": available,
            "speaker_id": self.chosen_speaker(),
            "character_id": self._characters.active_id,
        }

    async def speakers(self) -> list[dict[str, Any]]:
        if not self._engine:
            raise TTSUnavailableError("TTS エンジンが設定されていません(config の voice.engine)。")
        return [
            {
                "name": s.name,
                "credit": s.credit,
                "styles": [{"id": st.id, "name": st.name} for st in s.styles],
            }
            for s in await self._engine.speakers()
        ]

    async def preview(self, text: str, speaker: int | None = None) -> Speech:
        if not self._engine:
            raise TTSUnavailableError("TTS エンジンが設定されていません(config の voice.engine)。")
        return await self._engine.synthesize(text, self.voice(speaker))

    # --- 返答の読み上げ ---

    def begin(self, session_id: str) -> Utterance | None:
        """新しいターンの読み上げを始める。声がオフなら None(何もしない)。"""
        if not (self._engine and self.enabled):
            return None
        self._turn += 1
        if self._worker is None or self._worker.done():
            self._worker = asyncio.get_running_loop().create_task(self._run())
        return Utterance(self, self._turn, session_id, self.voice())

    def enqueue(self, job: _Job) -> None:
        self._queue.put_nowait(job)

    async def _run(self) -> None:
        while True:
            job = await self._queue.get()
            if job.turn < self._turn:
                continue  # もっと新しいターンが始まった。古い文は読まない
            if job.done:
                await self._hub.publish(
                    {"type": "audio_done", "session_id": job.session_id, "turn": job.turn}
                )
                continue
            if job.turn == self._failed_turn:
                continue  # このターンはもう失敗を通知した
            try:
                assert self._engine is not None  # begin() がエンジン無しでは Utterance を作らない
                speech = await self._engine.synthesize(job.text, job.voice)
            except TTSUnavailableError as e:
                self._failed_turn = job.turn
                await self._hub.publish({"type": "notice", "level": "warn", "text": str(e)})
                continue
            except Exception as e:  # 想定外でも作業タスクは生かしておく
                self._failed_turn = job.turn
                await self._hub.publish(
                    {"type": "notice", "level": "error", "text": f"音声合成エラー: {e}"}
                )
                continue
            await self._hub.publish(
                {
                    "type": "audio_chunk",
                    "session_id": job.session_id,
                    "turn": job.turn,
                    "seq": job.seq,
                    "text": job.text,
                    **speech_payload(speech),
                }
            )

    async def aclose(self) -> None:
        if self._worker:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
        if self._engine:
            await self._engine.aclose()
