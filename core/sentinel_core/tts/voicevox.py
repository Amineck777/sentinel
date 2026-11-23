"""VOICEVOX ENGINE(HTTP API)のアダプタ。

VOICEVOX のアプリ(またはエンジン単体)を起動すると http://127.0.0.1:50021 で待ち受ける。
合成は2段階:
  1. POST /audio_query?text=…&speaker=ID  → 読み・アクセント・各音の長さ(音声クエリ)
  2. POST /synthesis?speaker=ID(本文=音声クエリ) → WAV
1 の音声クエリに「モーラ(拍)ごとの母音と長さ」が入っているので、そこから口パクの
タイムラインを作る(ADR 0108)。CPU で動くので、GPU(VRAM)を LLM と取り合わない。
"""

from __future__ import annotations

import io
import wave
from typing import Any

import httpx

from sentinel_core.tts.base import (
    SpeakerInfo,
    Speech,
    TTSUnavailableError,
    Viseme,
    VoiceParams,
    VoiceStyle,
    Vowel,
)

DEFAULT_ENDPOINT = "http://127.0.0.1:50021"

UNAVAILABLE_NOTICE = (
    "VOICEVOX に接続できませんでした。VOICEVOX を起動しているか確認してください"
    "(声を使わないときは設定の「声」をオフにします)。"
)

# 音声クエリの母音 → VRM の口の形。N(ん)・cl(っ)・pau(無音)は口を閉じる
_VOWEL_MAP: dict[str, Vowel] = {"a": "aa", "i": "ih", "u": "ou", "e": "ee", "o": "oh"}


def _vowel(v: str | None) -> Vowel | None:
    # 無声化した母音は大文字で来る(例: "U")。口の形は同じなので小文字にそろえる
    return _VOWEL_MAP.get((v or "").lower())


def visemes_from_query(query: dict[str, Any]) -> list[Viseme]:
    """音声クエリから口パクのタイムラインを作る。

    VOICEVOX は各長さ(秒)を speedScale で割って合成する(速いほど短い)。
    子音の間も、その拍の母音の口にしておく(子音だけ口を閉じるとパクパクしすぎる)。
    """
    speed = float(query.get("speedScale") or 1.0)
    pause_len = query.get("pauseLength")  # 新しいエンジンだけにある。None なら元の長さ
    pause_scale = float(query.get("pauseLengthScale") or 1.0)

    out: list[Viseme] = []
    t = float(query.get("prePhonemeLength") or 0.0) / speed

    def add(vowel: Vowel | None, length: float) -> None:
        nonlocal t
        if length <= 0:
            return
        # 同じ口が続くなら1つにまとめる(送るデータを減らす)
        if out and out[-1].vowel == vowel:
            out[-1] = Viseme(vowel, out[-1].start, t + length)
        else:
            out.append(Viseme(vowel, t, t + length))
        t += length

    for phrase in query.get("accent_phrases") or []:
        for mora in phrase.get("moras") or []:
            length = float(mora.get("consonant_length") or 0.0) + float(
                mora.get("vowel_length") or 0.0
            )
            add(_vowel(mora.get("vowel")), length / speed)
        pause = phrase.get("pause_mora")
        if pause:
            length = float(pause_len) if pause_len is not None else float(pause["vowel_length"])
            add(None, length * pause_scale / speed)
    return out


def wav_duration(data: bytes) -> float:
    try:
        with wave.open(io.BytesIO(data)) as w:
            return float(w.getnframes()) / float(w.getframerate())
    except (wave.Error, EOFError, ZeroDivisionError):
        return 0.0


class VoicevoxEngine:
    name = "voicevox"

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        timeout_sec: float = 30,
        transport: httpx.AsyncBaseTransport | None = None,  # テストで偽のエンジンを渡す
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout_sec, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def is_available(self) -> bool:
        try:
            r = await self._client.get(f"{self._endpoint}/version", timeout=2)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def speakers(self) -> list[SpeakerInfo]:
        data = await self._request("GET", "/speakers")
        out: list[SpeakerInfo] = []
        for sp in data.json():
            # type は "talk"(話す声)以外に "singing_teacher" などがある。古い版には無い
            styles = [
                VoiceStyle(id=int(st["id"]), name=str(st["name"]))
                for st in sp.get("styles", [])
                if st.get("type", "talk") == "talk"
            ]
            if styles:
                name = str(sp["name"])
                out.append(SpeakerInfo(name=name, styles=styles, credit=f"VOICEVOX:{name}"))
        return out

    async def synthesize(self, text: str, voice: VoiceParams) -> Speech:
        speaker = voice.speaker if voice.speaker is not None else await self._first_style()
        q = await self._request("POST", "/audio_query", params={"text": text, "speaker": speaker})
        query: dict[str, Any] = q.json()
        query["speedScale"] = voice.speed
        query["pitchScale"] = voice.pitch
        query["intonationScale"] = voice.intonation
        query["volumeScale"] = voice.volume
        r = await self._request("POST", "/synthesis", params={"speaker": speaker}, json=query)
        wav = r.content
        return Speech(wav=wav, duration=wav_duration(wav), visemes=visemes_from_query(query))

    async def _first_style(self) -> int:
        # 話者を選んでいないときは、エンジンが返す最初の声を使う
        speakers = await self.speakers()
        if not speakers:
            raise TTSUnavailableError("VOICEVOX に使える話者がありません。")
        return speakers[0].styles[0].id

    async def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        try:
            r = await self._client.request(method, f"{self._endpoint}{path}", **kw)
            r.raise_for_status()
            return r
        except httpx.TransportError as e:
            raise TTSUnavailableError(UNAVAILABLE_NOTICE) from e
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            hint = "(話者IDが存在しない可能性があります)" if code == 422 else ""
            raise TTSUnavailableError(f"VOICEVOX の合成に失敗しました: HTTP {code}{hint}") from e
