"""会話ターンの実行(仕様 §3.3 の実行モデルのPhase 1形)。

POST /v1/chat から呼ばれ、即座に (session_id, message_id) を返し、
生成本体はバックグラウンドタスクが hub へ token/message_done イベントを流す。
この生成部は Pydantic AI のエージェント実行へ差し替える予定(ADR-0102)。
差し替え点をこのクラスに閉じ込めてある。
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import datetime
from typing import Any

from sentinel_core.agent.prompts import system_prompt
from sentinel_core.character.registry import CharacterRegistry
from sentinel_core.events import EventHub
from sentinel_core.expression import TurnExpression
from sentinel_core.llm.client import LLMClient, LLMUnavailableError
from sentinel_core.memory.store import Store
from sentinel_core.tts.service import SpeechService


def _part_of_day(hour: int) -> str:
    if 5 <= hour < 11:
        return "朝"
    if 11 <= hour < 17:
        return "昼"
    if 17 <= hour < 23:
        return "夜"
    return "深夜"


def greeting_cue(now: datetime | None = None) -> str:
    """起動時の挨拶を促す合図。LLMには user として渡すが、会話履歴には保存しない。

    コアは利用者のPC上で動くので、ローカル時刻 = 利用者の時刻。時間帯に合った挨拶にするため渡す。
    """
    now = now or datetime.now()
    return (
        f"(マスターがアプリを起動しました。今は{now.hour}時{now.minute:02d}分、"
        f"{_part_of_day(now.hour)}です。あなたから先に、短く挨拶してください。"
        "この括弧の文そのものには触れないでください)"
    )


class ChatService:
    def __init__(
        self,
        store: Store,
        llm: LLMClient,
        characters: CharacterRegistry,
        hub: EventHub,
        default_model: str,
        speech: SpeechService | None = None,
    ) -> None:
        self._store = store
        self._speech = speech  # 返答の読み上げ。None なら声なし
        self._default_model = default_model  # 記録用(Packがモデルを指定しないときの名前)
        self._llm = llm
        self._characters = characters
        self._hub = hub
        # asyncio.Task は強参照を保持しないとGCで途中終了し得るため、ここで持つ
        self._tasks: set[asyncio.Task[None]] = set()
        # セッション毎の生成直列化ロック。生成中の追い打ち送信で token イベントが
        # 交錯するのを防ぐ。エントリは解放しない(個人利用のセッション数では
        # 問題にならず、解放処理は取得との競合を生むため)
        self._session_locks: dict[str, asyncio.Lock] = {}

    def start_turn(
        self,
        content: str,
        session_id: str | None = None,
        character_id: str | None = None,
    ) -> tuple[str, str]:
        """ユーザー発話を保存し、生成をバックグラウンドで開始する。"""
        if character_id is not None:
            self._characters.activate(character_id)
        sid = self._store.ensure_session(session_id, self._characters.active_id)
        mid = self._store.add_message(sid, "user", content)
        self._spawn(self._generate(sid))
        return sid, mid

    def start_greeting(self, session_id: str | None = None) -> str | None:
        """キャラから先に挨拶するターンを始める(起動時・キャラ切替時)。

        汎用モードでは挨拶しない(None を返す)。合図の文は保存せず、挨拶だけを
        assistant の発言として残す(次のターンからはその挨拶が履歴の先頭になる)。
        """
        if self._characters.active_pack() is None:
            return None
        sid = self._store.ensure_session(session_id, self._characters.active_id)
        self._spawn(self._generate(sid, cue=greeting_cue()))
        return sid

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _generate(self, session_id: str, cue: str | None = None) -> None:
        lock = self._session_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            await self._generate_turn(session_id, cue)

    def active_model(self) -> str:
        """今のキャラで使うモデル名(Packの指定 > 設定の llm.chat_model)。"""
        pack = self._characters.active_pack()
        return (pack.model if pack else None) or self._default_model

    async def _generate_turn(self, session_id: str, cue: str | None = None) -> None:
        pack = self._characters.active_pack()
        messages: list[dict[str, str]] = []
        # 人格をモデル側(Modelfile の SYSTEM)に持つPackでは system を送らない。
        # 送ると Ollama はそちらを優先し、Modelfile の人格が消えるため
        if not (pack and pack.use_model_system):
            messages.append(
                {"role": "system", "content": system_prompt(self._characters.active_fragment())}
            )
        messages += self._store.history(session_id)
        if cue:  # 保存しない合図(挨拶など)。履歴の最後に user として足す
            messages.append({"role": "user", "content": cue})
        model = self.active_model()

        parts: list[str] = []
        # 声がオンなら、文が閉じるたびに合成を始める(全文を待たずに話し始める)
        utter = self._speech.begin(session_id) if self._speech else None
        # 感情タグを抜き、文ごとに表情を決める(expression.py)
        expr = TurnExpression()
        shown_emotion = "neutral"

        async def emit(clean: str, sentences: list[tuple[str, str]]) -> None:
            nonlocal shown_emotion
            if clean:
                parts.append(clean)
                await self._hub.publish({"type": "token", "session_id": session_id, "delta": clean})
            for text, emotion in sentences:
                if emotion != shown_emotion:
                    shown_emotion = emotion
                    await self._hub.publish(
                        {"type": "emotion", "session_id": session_id, "emotion": emotion}
                    )
                if utter:
                    utter.say(text, emotion)

        try:
            async for delta in self._llm.stream_chat(messages, model=pack.model if pack else None):
                await emit(*expr.feed(delta))
        except LLMUnavailableError as e:
            # オフライン応答などの案内文は通知として見せ、履歴には残さない
            await self._hub.publish({"type": "notice", "level": "warn", "text": str(e)})
        except Exception as e:  # 予期しない失敗もUIへ通知して終端する(無言で固まらせない)
            await self._hub.publish(
                {"type": "notice", "level": "error", "text": f"生成エラー: {e}"}
            )

        finally:
            # 閉じずに終わった最後の文も表示・読み上げる
            await emit(*expr.flush())
            if utter:
                utter.finish()  # 残りの文を読み、ターンの終わり(audio_done)を知らせる

        # 保存するのはモデルが実際に生成した文だけ(途中で切れた場合はそこまで)。
        # 何も生成されなかったターンは assistant 発言を作らない
        full = "".join(parts)
        if not full:
            return
        mid = self._store.add_message(session_id, "assistant", full, model=model)
        await self._hub.publish(
            {"type": "message_done", "session_id": session_id, "message_id": mid}
        )
