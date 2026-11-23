"""config の voice.engine から TTS エンジンを作る。新しいエンジンはここに足す。"""

from __future__ import annotations

from typing import Any

from sentinel_core.tts.base import TTSEngine
from sentinel_core.tts.voicevox import DEFAULT_ENDPOINT, VoicevoxEngine


def make_engine(voice_cfg: dict[str, Any]) -> TTSEngine | None:
    """engine が "none" や未知の名前なら None(声なしで動く)。"""
    name = str(voice_cfg.get("engine") or "none")
    if name == "voicevox":
        return VoicevoxEngine(endpoint=str(voice_cfg.get("endpoint") or DEFAULT_ENDPOINT))
    # 例: if name == "sbv2": return StyleBertVits2Engine(...)
    return None
