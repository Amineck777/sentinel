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
    # llm.system_prompt: file のときの人格の文(ファイルの中身そのまま)。それ以外は None。
    # コアがこれに記憶を足して system として送る(ADR 0116)。Modelfile の SYSTEM も
    # 同じファイルから作る(scripts/build_modelfile.py)ので、人格の文の正は1か所になる
    system_text: str | None = None


# character.yaml の llm.system_prompt に書ける値
# - pack : persona/ の .md(persona.md など)から system を組み立てて送る(既定)
# - model: system を送らず、モデル自身の人格(Modelfile の SYSTEM)を使う
# - file : llm.system_file の1ファイルを人格の文として送る(記憶を足せる)
SYSTEM_PROMPT_MODES = ("pack", "model", "file")
# llm.system_file を書かなかったときの場所(Pack のフォルダからの相対パス)
DEFAULT_SYSTEM_FILE = "persona/system.md"


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
        system_text = _read_system_file(root, llm) if mode == "file" else None
        return CharacterPack(
            id=cid,
            display_name=name,
            valid=True,
            system_fragment=compose_system_fragment(root),
            voice=manifest.get("voice") or {},
            model=str(model) if model else None,
            use_model_system=mode == "model",
            system_text=system_text,
        )
    except Exception as e:  # 不正Packでも起動は止めない(§16.3)
        return CharacterPack(id=root.name, display_name=root.name, valid=False, error=str(e))


def _read_system_file(root: Path, llm: dict[str, Any]) -> str:
    """llm.system_file の人格の文を読む。無い・空・Pack の外を指す場合は不正 Pack にする。"""
    rel = str(llm.get("system_file") or DEFAULT_SYSTEM_FILE)
    path = (root / rel).resolve()
    # Pack の外のファイル(../ など)は読まない。Pack は1フォルダで完結させる決まり(§16.1)
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"llm.system_file は Pack の中を指してください: {rel!r}")
    if not path.is_file():
        raise ValueError(f"llm.system_file が見つかりません: {rel!r}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"llm.system_file が空です: {rel!r}")
    return text
