"""声(TTS): 文の切り方、VOICEVOX の口パク変換、返答の読み上げの流れ。

実エンジンは使わない。VOICEVOX は httpx.MockTransport の偽サーバー、
読み上げの流れは決定的な FakeTTS で確かめる(仕様 §12.2 と同じ考え方)。
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import wave
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from sentinel_core.api.app import create_app
from sentinel_core.settings import Settings
from sentinel_core.tts.base import SpeakerInfo, Speech, TTSUnavailableError, Viseme, VoiceParams
from sentinel_core.tts.sentences import SentenceSplitter, clean_for_speech
from sentinel_core.tts.voicevox import VoicevoxEngine, visemes_from_query

TOKEN = "test-token"
H = {"X-Sentinel-Token": TOKEN}


def make_wav(seconds: float, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


# --- 文の切り方 ---


def split_all(deltas: list[str]) -> list[str]:
    sp = SentenceSplitter()
    out: list[str] = []
    for d in deltas:
        out += sp.feed(d)
    return out + sp.flush()


def test_splits_on_sentence_end_even_across_tokens():
    assert split_all(["おかえり", "なさいませ。", "お茶を", "淹れますね！", "少々"]) == [
        "おかえりなさいませ。",
        "お茶を淹れますね！",
        "少々",
    ]


def test_closing_bracket_stays_with_sentence():
    assert split_all(["「はい。", "」と言った"]) == ["「はい。」", "と言った"]


def test_drops_stage_directions_markup_and_empty():
    assert clean_for_speech("（微笑んで）**承知**しました😊") == "承知しました"
    assert split_all(["……。", "（一礼）\n", "はい"]) == ["はい"]


def test_long_sentence_is_cut_at_comma():
    long = "あ" * 50 + "、" + "い" * 50
    out = split_all([long, "。"])
    assert out[0] == "あ" * 50 + "、" and out[1] == "い" * 50 + "。"


# --- VOICEVOX の音声クエリ → 口パク ---

QUERY = {
    "accent_phrases": [
        {
            "moras": [
                {"text": "コ", "consonant": "k", "consonant_length": 0.05, "vowel": "o",
                 "vowel_length": 0.10, "pitch": 5.6},
                {"text": "ン", "consonant": None, "consonant_length": None, "vowel": "N",
                 "vowel_length": 0.08, "pitch": 5.7},
                {"text": "ニ", "consonant": "n", "consonant_length": 0.04, "vowel": "i",
                 "vowel_length": 0.06, "pitch": 5.8},
                {"text": "チ", "consonant": "ch", "consonant_length": 0.05, "vowel": "I",
                 "vowel_length": 0.05, "pitch": 0.0},
                {"text": "ワ", "consonant": "w", "consonant_length": 0.05, "vowel": "a",
                 "vowel_length": 0.15, "pitch": 5.5},
            ],
            "accent": 5,
            "pause_mora": {"text": "、", "consonant": None, "consonant_length": None,
                           "vowel": "pau", "vowel_length": 0.3, "pitch": 0.0},
        },
    ],
    "speedScale": 1.0,
    "pitchScale": 0.0,
    "intonationScale": 1.0,
    "volumeScale": 1.0,
    "prePhonemeLength": 0.1,
    "postPhonemeLength": 0.1,
    "outputSamplingRate": 24000,
    "outputStereo": False,
}  # fmt: skip


def test_visemes_follow_mora_lengths():
    v = visemes_from_query(QUERY)
    assert [x.vowel for x in v] == ["oh", None, "ih", "aa", None]  # ニ・チ(無声化 I)は1つに
    assert v[0].start == pytest.approx(0.1)  # 最初の無音のあと
    assert v[0].end == pytest.approx(0.25)
    assert v[2].end == pytest.approx(0.53)
    assert v[-1].end == pytest.approx(1.03)  # 読点の間(0.3 秒)まで


def test_visemes_scale_with_speed_and_pause_length():
    q = {**QUERY, "speedScale": 2.0, "pauseLength": 0.1, "pauseLengthScale": 1.0}
    v = visemes_from_query(q)
    assert v[0].start == pytest.approx(0.05)
    assert v[-1].end - v[-1].start == pytest.approx(0.05)


def fake_voicevox(calls: list[httpx.Request]) -> httpx.MockTransport:
    speakers = [
        {"name": "冥鳴ひまり", "styles": [{"name": "ノーマル", "id": 14, "type": "talk"}]},
        {"name": "歌う人", "styles": [{"name": "ハミング", "id": 3000, "type": "frame_decode"}]},
    ]

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if req.url.path == "/version":
            return httpx.Response(200, json="0.25.0")
        if req.url.path == "/speakers":
            return httpx.Response(200, json=speakers)
        if req.url.path == "/audio_query":
            return httpx.Response(200, json=QUERY)
        if req.url.path == "/synthesis":
            return httpx.Response(200, content=make_wav(1.03))
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_voicevox_engine_against_fake_server():
    calls: list[httpx.Request] = []

    async def run() -> tuple[list[SpeakerInfo], Speech]:
        eng = VoicevoxEngine(transport=fake_voicevox(calls))
        try:
            assert await eng.is_available()
            return await eng.speakers(), await eng.synthesize(
                "こんにちは", VoiceParams(speed=1.2, pitch=0.05)
            )
        finally:
            await eng.aclose()

    speakers, speech = asyncio.run(run())
    # 歌声用(type が talk 以外)の話者は外す。クレジット表記も付く
    assert [(s.name, s.credit) for s in speakers] == [("冥鳴ひまり", "VOICEVOX:冥鳴ひまり")]
    assert speech.duration == pytest.approx(1.03, abs=1e-3)
    assert speech.visemes and speech.visemes[0].vowel == "oh"
    synth = next(r for r in calls if r.url.path == "/synthesis")
    # 話者未指定なら最初の声。速さ・高さは音声クエリに書き込んで送る
    assert synth.url.params["speaker"] == "14"
    body = json.loads(synth.content)
    assert body["speedScale"] == 1.2 and body["pitchScale"] == 0.05


def test_voicevox_unreachable_raises_friendly_error():
    def refuse(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    async def run() -> None:
        eng = VoicevoxEngine(transport=httpx.MockTransport(refuse))
        try:
            assert not await eng.is_available()
            await eng.synthesize("はい", VoiceParams(speaker=14))
        finally:
            await eng.aclose()

    with pytest.raises(TTSUnavailableError, match="VOICEVOX を起動"):
        asyncio.run(run())


# --- 返答の読み上げ(API 全体) ---


class FakeTTS:
    name = "fake"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.spoken: list[tuple[str, int | None]] = []

    async def is_available(self) -> bool:
        return not self.fail

    async def speakers(self) -> list[SpeakerInfo]:
        return [SpeakerInfo(name="テスト", credit="VOICEVOX:テスト")]

    async def synthesize(self, text: str, voice: VoiceParams) -> Speech:
        if self.fail:
            raise TTSUnavailableError("VOICEVOX に接続できませんでした。")
        self.spoken.append((text, voice.speaker))
        return Speech(wav=make_wav(0.2), duration=0.2, visemes=[Viseme("aa", 0.0, 0.2)])

    async def aclose(self) -> None:
        pass


class TwoSentenceLLM:
    async def stream_chat(self, messages, *, model=None) -> AsyncIterator[str]:
        for chunk in ["おかえりなさいませ", "、マスター。", "お茶を", "どうぞ"]:
            await asyncio.sleep(0)
            yield chunk

    async def is_reachable(self) -> bool:
        return True


@pytest.fixture()
def make_client(tmp_path: Path):
    clients: list[TestClient] = []

    def _make(tts: FakeTTS) -> TestClient:
        settings = Settings.load(data_dir=tmp_path)
        app = create_app(settings=settings, token=TOKEN, dev=True, llm=TwoSentenceLLM(), tts=tts)
        c = TestClient(app)
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


def collect_until(ws, kind: str, limit: int = 30) -> list[dict]:
    events = []
    for _ in range(limit):
        ev = ws.receive_json()
        events.append(ev)
        if ev["type"] == kind:
            return events
    raise AssertionError(f"{kind} が来なかった: {events}")


def test_voice_is_off_by_default(make_client):
    tts = FakeTTS()
    c = make_client(tts)
    assert c.get("/v1/voice", headers=H).json()["enabled"] is False
    with c.websocket_connect(f"/v1/stream?token={TOKEN}") as ws:
        c.post("/v1/chat", headers=H, json={"content": "ただいま"})
        events = collect_until(ws, "message_done")
    assert not any(e["type"] == "audio_chunk" for e in events)
    assert tts.spoken == []


def test_reply_is_spoken_sentence_by_sentence(make_client):
    tts = FakeTTS()
    c = make_client(tts)
    st = c.patch("/v1/voice", headers=H, json={"enabled": True, "speaker_id": 14}).json()
    assert st["enabled"] is True and st["speaker_id"] == 14 and st["available"] is True

    with c.websocket_connect(f"/v1/stream?token={TOKEN}") as ws:
        c.post("/v1/chat", headers=H, json={"content": "ただいま"})
        events = collect_until(ws, "audio_done")

    chunks = [e for e in events if e["type"] == "audio_chunk"]
    assert [ch["text"] for ch in chunks] == ["おかえりなさいませ、マスター。", "お茶をどうぞ"]
    assert [ch["seq"] for ch in chunks] == [0, 1]
    # 文ごとの表情(アバター用)も一緒に届く。この返事には手がかりの言葉が無いのでふつう
    assert [ch["emotion"] for ch in chunks] == ["neutral", "neutral"]
    first = chunks[0]
    assert first["format"] == "wav" and first["visemes"] == [["aa", 0.0, 0.2]]
    assert base64.b64decode(first["data_b64"])[:4] == b"RIFF"
    assert all(sp == 14 for _, sp in tts.spoken)


def test_tts_failure_notifies_once_and_chat_continues(make_client):
    c = make_client(FakeTTS(fail=True))
    c.patch("/v1/voice", headers=H, json={"enabled": True})
    with c.websocket_connect(f"/v1/stream?token={TOKEN}") as ws:
        c.post("/v1/chat", headers=H, json={"content": "ただいま"})
        events = collect_until(ws, "audio_done")
    notices = [e for e in events if e["type"] == "notice"]
    assert len(notices) == 1 and "VOICEVOX" in notices[0]["text"]
    assert any(e["type"] == "message_done" for e in events)  # 文字の返事は届く


def test_voice_settings_persist_and_preview(make_client):
    c = make_client(FakeTTS())
    c.patch("/v1/voice", headers=H, json={"enabled": True, "speaker_id": 23})
    assert c.get("/v1/voice/speakers", headers=H).json()["speakers"][0]["credit"] == (
        "VOICEVOX:テスト"
    )
    p = c.post("/v1/voice/preview", headers=H, json={}).json()
    assert p["format"] == "wav" and p["duration"] == 0.2

    # 再起動しても(同じ data_dir で作り直しても)オン・声の選択は残る
    c2 = make_client(FakeTTS())
    st = c2.get("/v1/voice", headers=H).json()
    assert st["enabled"] is True and st["speaker_id"] == 23
    st = c2.patch("/v1/voice", headers=H, json={"clear_speaker": True}).json()
    assert st["speaker_id"] == 122  # 選択を外すと config の既定(暁記ミタマ)に戻る


def test_preview_reports_unavailable_engine(make_client):
    c = make_client(FakeTTS(fail=True))
    r = c.post("/v1/voice/preview", headers=H, json={"text": "テスト"})
    assert r.status_code == 503 and "VOICEVOX" in r.json()["detail"]
