"""同梱の VOICEVOX CORE アダプタと、エンジンの選び方(auto)。

本物の voicevox_core は CI に入っていない(GitHub の wheel と音声モデルが要るため)。
ここでは同じ形の偽モジュールを sys.modules に差し込み、アダプタの流れだけを確かめる。
"""

from __future__ import annotations

import asyncio
import dataclasses
import functools
import io
import sys
import types
import wave
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from sentinel_core.tts.base import TTSUnavailableError, VoiceParams
from sentinel_core.tts.factory import make_engine
from sentinel_core.tts.voicevox import VoicevoxEngine
from sentinel_core.tts.voicevox_core_engine import VoicevoxCoreEngine, query_to_engine_dict


def make_wav(seconds: float, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


def sync(fn: Callable[..., Awaitable[None]]) -> Callable[..., None]:
    """async のテストを、イベントループを立てて同期で回す(pytest-asyncio を足さないため)。"""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> None:
        asyncio.run(fn(*args, **kwargs))  # type: ignore[arg-type]

    return wrapper


# --- 偽の voicevox_core(本物の Python API と同じ名前・形だけ持たせる)---


@dataclasses.dataclass
class Mora:
    text: str
    vowel: str
    vowel_length: float
    pitch: float
    consonant: str | None = None
    consonant_length: float | None = None


@dataclasses.dataclass
class AccentPhrase:
    moras: list[Mora]
    accent: int
    pause_mora: Mora | None = None


@dataclasses.dataclass
class AudioQuery:
    accent_phrases: list[AccentPhrase]
    speed_scale: float = 1.0
    pitch_scale: float = 0.0
    intonation_scale: float = 1.0
    volume_scale: float = 1.0
    pre_phoneme_length: float = 0.1
    post_phoneme_length: float = 0.1


@dataclasses.dataclass
class StyleMeta:
    name: str
    id: int
    type: str = "talk"


@dataclasses.dataclass
class CharacterMeta:
    name: str
    styles: list[StyleMeta]


def make_query() -> AudioQuery:
    # 「はい、」+ 間 +「ん」
    return AudioQuery(
        accent_phrases=[
            AccentPhrase(
                moras=[
                    Mora("ハ", "a", 0.1, 5.0, "h", 0.05),
                    Mora("イ", "i", 0.15, 5.0),
                ],
                accent=1,
                pause_mora=Mora("、", "pau", 0.2, 0.0),
            ),
            AccentPhrase(moras=[Mora("ン", "N", 0.1, 5.0)], accent=1),
        ]
    )


MODELS: dict[str, list[CharacterMeta]] = {
    "24.vvm": [
        CharacterMeta("暁記ミタマ", [StyleMeta("ノーマル", 122), StyleMeta("ささやき", 125)]),
    ],
    "0.vvm": [
        CharacterMeta("ずんだもん", [StyleMeta("ノーマル", 3), StyleMeta("歌", 3000, "sing")]),
    ],
}


class FakeVoiceModelFile:
    def __init__(self, path: str) -> None:
        self.id = Path(path).name
        self.metas = MODELS[self.id]

    @staticmethod
    async def open(path: str) -> FakeVoiceModelFile:
        return FakeVoiceModelFile(path)

    async def close(self) -> None:
        pass


class FakeSynthesizer:
    instances: list[FakeSynthesizer] = []

    def __init__(self, ort: Any, ojt: Any, *, acceleration_mode: str, cpu_num_threads: int):
        self.acceleration_mode = acceleration_mode
        self.loaded: list[str] = []
        self.synthesized: list[tuple[AudioQuery, int]] = []
        FakeSynthesizer.instances.append(self)

    async def load_voice_model(self, model: FakeVoiceModelFile) -> None:
        self.loaded.append(model.id)

    async def create_audio_query(self, text: str, style_id: int) -> AudioQuery:
        return make_query()

    async def synthesis(self, query: AudioQuery, style_id: int) -> bytes:
        self.synthesized.append((query, style_id))
        return make_wav(0.5)

    async def close(self) -> None:
        pass


class FakeOnnxruntime:
    LIB_RECOMMENDED_VERSIONED_FILENAME = "voicevox_onnxruntime.dll"

    @staticmethod
    async def load_once(*, filename: str) -> str:
        return filename


class FakeOpenJtalk:
    @staticmethod
    async def new(path: str) -> str:
        return path


@pytest.fixture
def fake_module(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    mod = types.ModuleType("fake_vvcore")
    sub = types.ModuleType("fake_vvcore.asyncio")
    sub.Onnxruntime = FakeOnnxruntime  # type: ignore[attr-defined]
    sub.OpenJtalk = FakeOpenJtalk  # type: ignore[attr-defined]
    sub.Synthesizer = FakeSynthesizer  # type: ignore[attr-defined]
    sub.VoiceModelFile = FakeVoiceModelFile  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fake_vvcore", mod)
    monkeypatch.setitem(sys.modules, "fake_vvcore.asyncio", sub)
    FakeSynthesizer.instances = []
    return mod


def make_core_dir(root: Path, models: tuple[str, ...] = ("24.vvm", "0.vvm")) -> Path:
    """ダウンローダーが作るのと同じ並びのフォルダ(中身は空ファイル)。"""
    (root / "onnxruntime" / "lib").mkdir(parents=True)
    (root / "onnxruntime" / "lib" / "voicevox_onnxruntime.dll").write_bytes(b"")
    (root / "dict" / "open_jtalk_dic_utf_8-1.11").mkdir(parents=True)
    (root / "models" / "vvms").mkdir(parents=True)
    for m in models:
        (root / "models" / "vvms" / m).write_bytes(b"")
    return root


# --- 音声クエリ → 口パク(ENGINE と同じ変換を通ること)---


def test_core_query_becomes_engine_shaped_dict():
    d = query_to_engine_dict(make_query())
    assert d["speedScale"] == 1.0 and d["prePhonemeLength"] == 0.1
    first = d["accent_phrases"][0]
    assert first["moras"][0] == {"vowel": "a", "vowel_length": 0.1, "consonant_length": 0.05}
    assert first["pause_mora"]["vowel"] == "pau"
    assert d["accent_phrases"][1]["pause_mora"] is None


def test_core_query_with_dict_parts():
    # 本物の CORE では pause_mora などが dict のまま入っていることがある(Windows 実機で確認)
    q = make_query()
    q.accent_phrases[0].pause_mora = {"text": "、", "vowel": "pau", "vowel_length": 0.2}  # type: ignore[assignment]
    q.accent_phrases[1].moras = [{"vowel": "N", "vowel_length": 0.1}]  # type: ignore[list-item]
    d = query_to_engine_dict(q)
    assert d["accent_phrases"][0]["pause_mora"]["vowel_length"] == 0.2
    assert d["accent_phrases"][1]["moras"][0] == {
        "vowel": "N",
        "vowel_length": 0.1,
        "consonant_length": None,
    }


# --- アダプタの流れ ---


@sync
async def test_speakers_merge_vvms_and_skip_singing(tmp_path: Path, fake_module: Any):
    engine = VoicevoxCoreEngine(make_core_dir(tmp_path), module=fake_module)
    speakers = {s.name: s for s in await engine.speakers()}
    assert [st.id for st in speakers["暁記ミタマ"].styles] == [122, 125]
    assert [st.id for st in speakers["ずんだもん"].styles] == [3]  # 歌声(sing)は出さない
    assert speakers["暁記ミタマ"].credit == "VOICEVOX:暁記ミタマ"
    # 話者一覧を出すだけならモデルは読み込まない(重いので)
    assert FakeSynthesizer.instances[0].loaded == []
    assert FakeSynthesizer.instances[0].acceleration_mode == "CPU"  # GPU は LLM に譲る


@sync
async def test_synthesize_loads_only_needed_model_once(tmp_path: Path, fake_module: Any):
    engine = VoicevoxCoreEngine(make_core_dir(tmp_path), module=fake_module)
    voice = VoiceParams(speaker=122, speed=1.2, pitch=0.05)
    speech = await engine.synthesize("はい、ん", voice)
    await engine.synthesize("もう一度", voice)
    synth = FakeSynthesizer.instances[0]
    assert synth.loaded == ["24.vvm"]  # 122 が入った .vvm だけ、1回だけ
    query, style = synth.synthesized[0]
    assert style == 122 and query.speed_scale == 1.2 and query.pitch_scale == 0.05
    assert speech.duration == pytest.approx(0.5)
    assert speech.visemes is not None
    # 間(pau)と「ん」はどちらも口を閉じるので1つにまとまる
    assert [v.vowel for v in speech.visemes] == ["aa", "ih", None]
    # 速さ 1.2 なら長さは 1/1.2 になる(先頭の無音 0.1 秒のあとから話し始める)
    assert speech.visemes[0].start == pytest.approx(0.1 / 1.2)


@sync
async def test_preload_default_voice_after_setup(tmp_path: Path, fake_module: Any):
    engine = VoicevoxCoreEngine(make_core_dir(tmp_path), preload_style=122, module=fake_module)
    assert await engine.is_available()
    assert engine._preload_task is not None
    await engine._preload_task
    assert FakeSynthesizer.instances[0].loaded == ["24.vvm"]
    await engine.aclose()


@sync
async def test_unknown_style_says_model_missing(tmp_path: Path, fake_module: Any):
    engine = VoicevoxCoreEngine(make_core_dir(tmp_path, models=("0.vvm",)), module=fake_module)
    with pytest.raises(TTSUnavailableError, match="122"):
        await engine.synthesize("こんにちは", VoiceParams(speaker=122))


@sync
async def test_missing_files_point_to_setup_script(tmp_path: Path, fake_module: Any):
    engine = VoicevoxCoreEngine(tmp_path / "nowhere", module=fake_module)
    assert not await engine.is_available()
    with pytest.raises(TTSUnavailableError, match="setup_voicevox_core"):
        await engine.speakers()


@sync
async def test_missing_package_points_to_setup_script(tmp_path: Path, monkeypatch: Any):
    monkeypatch.setitem(sys.modules, "voicevox_core", None)  # import すると ImportError になる
    engine = VoicevoxCoreEngine(make_core_dir(tmp_path))
    with pytest.raises(TTSUnavailableError, match="パッケージ"):
        await engine.speakers()


# --- エンジンの選び方 ---


def test_auto_falls_back_to_http_when_core_missing(tmp_path: Path, monkeypatch: Any):
    monkeypatch.setattr("sentinel_core.tts.factory.core_installed", lambda d: False)
    assert isinstance(make_engine({"engine": "auto"}, tmp_path), VoicevoxEngine)


def test_auto_uses_core_when_installed(tmp_path: Path, monkeypatch: Any):
    seen: list[Path] = []
    monkeypatch.setattr(
        "sentinel_core.tts.factory.core_installed", lambda d: seen.append(d) or True
    )
    engine = make_engine({"engine": "auto", "speaker_id": 122}, tmp_path)
    assert isinstance(engine, VoicevoxCoreEngine)
    assert seen == [tmp_path / "voicevox_core"]  # 既定の置き場所は {APP_DATA}/sentinel の下


def test_core_dir_can_be_overridden(tmp_path: Path, monkeypatch: Any):
    seen: list[Path] = []
    monkeypatch.setattr(
        "sentinel_core.tts.factory.core_installed", lambda d: seen.append(d) or False
    )
    make_engine({"engine": "auto", "core": {"dir": str(tmp_path / "x")}}, tmp_path)
    assert seen == [tmp_path / "x"]


def test_explicit_engines(tmp_path: Path):
    assert isinstance(make_engine({"engine": "voicevox"}, tmp_path), VoicevoxEngine)
    assert isinstance(make_engine({"engine": "voicevox_core"}, tmp_path), VoicevoxCoreEngine)
    assert make_engine({"engine": "none"}, tmp_path) is None
