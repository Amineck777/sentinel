"""config の voice.engine から TTS エンジンを作る。新しいエンジンはここに足す。

voice.engine の値:
  - "auto"          … 同梱の VOICEVOX CORE が使える状態なら CORE、無ければ VOICEVOX ENGINE(HTTP)
  - "voicevox_core" … 同梱の VOICEVOX CORE だけを使う(アプリの起動は不要)
  - "voicevox"      … 別に起動した VOICEVOX(アプリかエンジン)に HTTP で頼む
  - "none"          … 声なし
"auto" の判定はコアの起動時に1回だけ行う(セットアップ後はコアの再起動で切り替わる)。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from sentinel_core.tts.base import TTSEngine
from sentinel_core.tts.voicevox import DEFAULT_ENDPOINT, VoicevoxEngine
from sentinel_core.tts.voicevox_core_engine import VoicevoxCoreEngine

# CORE のファイル置き場の既定({APP_DATA}/sentinel/ の下)。config の voice.core.dir で変えられる
CORE_DIR_NAME = "voicevox_core"


def core_dir(voice_cfg: dict[str, Any], data_dir: Path) -> Path:
    raw = (voice_cfg.get("core") or {}).get("dir")
    return Path(raw).expanduser() if raw else data_dir / CORE_DIR_NAME


def core_installed(base_dir: Path) -> bool:
    """CORE を使える見込みがあるか(パッケージが入っていて、音声モデルが1つ以上ある)。

    中身が正しいかまでは見ない(DLL の読み込みは重いので、実際の確認は初回の合成時)。
    """
    has_package = importlib.util.find_spec("voicevox_core") is not None
    return has_package and any((base_dir / "models").glob("**/*.vvm"))


def _make_core(voice_cfg: dict[str, Any], data_dir: Path) -> VoicevoxCoreEngine:
    core_cfg = voice_cfg.get("core") or {}
    speaker = voice_cfg.get("speaker_id")
    return VoicevoxCoreEngine(
        base_dir=core_dir(voice_cfg, data_dir),
        cpu_threads=int(core_cfg.get("cpu_threads") or 0),
        # 既定の声のモデルは起動直後に裏で読み込む(最初の返事を待たせないため)
        preload_style=int(speaker) if speaker is not None else None,
    )


def make_engine(voice_cfg: dict[str, Any], data_dir: Path) -> TTSEngine | None:
    """engine が "none" や未知の名前なら None(声なしで動く)。"""
    name = str(voice_cfg.get("engine") or "none")
    if name == "auto":
        name = "voicevox_core" if core_installed(core_dir(voice_cfg, data_dir)) else "voicevox"
    if name == "voicevox_core":
        return _make_core(voice_cfg, data_dir)
    if name == "voicevox":
        return VoicevoxEngine(endpoint=str(voice_cfg.get("endpoint") or DEFAULT_ENDPOINT))
    # 例: if name == "sbv2": return StyleBertVits2Engine(...)
    return None
