"""Character Packのロード・検証(仕様 §16.2)。

characters/{char_id}/character.yaml をマニフェストとして検証してロードする。
不正Packは「無効化して理由を保持」し、起動は止めない(§16.3)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from sentinel_core.character.persona import compose_system_fragment


@dataclass
class CharacterPack:
    id: str
    display_name: str
    valid: bool
    error: str | None = None
    system_fragment: str = ""
    voice: dict[str, Any] = field(default_factory=dict)
    # このキャラで使うモデル名(例: Ollama の "eva")。None なら設定の llm.chat_model
    model: str | None = None
    # True なら SENTINEL からはシステムプロンプトを送らず、モデル自身の人格
    # (Ollama の Modelfile の SYSTEM)をそのまま使う。人格の正をモデル側に置く使い方
    use_model_system: bool = False


# character.yaml の llm.system_prompt に書ける値
SYSTEM_PROMPT_MODES = ("pack", "model")


def load_pack(root: Path) -> CharacterPack:
    manifest_path = root / "character.yaml"
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        cid = str(manifest["id"])  # 必須キーの存在チェックを兼ねる
        name = str(manifest.get("display_name", cid))
        llm = manifest.get("llm") or {}
        model = llm.get("model")
        mode = str(llm.get("system_prompt") or "pack")
        if mode not in SYSTEM_PROMPT_MODES:
            raise ValueError(
                f"llm.system_prompt は {' / '.join(SYSTEM_PROMPT_MODES)} のどれか: {mode!r}"
            )
        if mode == "model" and not model:
            raise ValueError("llm.system_prompt: model には llm.model(モデル名)が必要です")
        return CharacterPack(
            id=cid,
            display_name=name,
            valid=True,
            system_fragment=compose_system_fragment(root),
            voice=manifest.get("voice") or {},
            model=str(model) if model else None,
            use_model_system=mode == "model",
        )
    except Exception as e:  # 不正Packでも起動は止めない(§16.3)
        return CharacterPack(id=root.name, display_name=root.name, valid=False, error=str(e))
