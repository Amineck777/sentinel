"""Character Packのロード・検証(仕様 §16.2)。

characters/{char_id}/character.yaml をマニフェストとして検証してロードする。
不正Packは「無効化して理由を保持」し、起動は止めない(§16.3)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from sentinel_core.character.persona import compose_system_fragment


@dataclass
class CharacterPack:
    id: str
    display_name: str
    valid: bool
    error: str | None = None
    system_fragment: str = ""
    voice: dict = field(default_factory=dict)


def load_pack(root: Path) -> CharacterPack:
    manifest_path = root / "character.yaml"
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        cid = str(manifest["id"])  # 必須キーの存在チェックを兼ねる
        name = str(manifest.get("display_name", cid))
        return CharacterPack(
            id=cid, display_name=name, valid=True,
            system_fragment=compose_system_fragment(root),
            voice=manifest.get("voice") or {},
        )
    except Exception as e:  # 不正Packでも起動は止めない(§16.3)
        return CharacterPack(id=root.name, display_name=root.name, valid=False, error=str(e))
