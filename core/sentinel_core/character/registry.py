"""Character Packの走査・切替(仕様 §16.1/§16.3)。

- characters/ 配下の1フォルダ=1キャラ。「置けば増え、消せば消える」
- 不正Packは無効化して理由を保持し、起動は止めない
- どの失敗でも汎用モードへフォールバックしてアシスタント本体は動き続ける
"""
from __future__ import annotations

from pathlib import Path

from sentinel_core.character.pack import CharacterPack, load_pack


class CharacterRegistry:
    def __init__(self, characters_dir: Path) -> None:
        self._dir = characters_dir
        self._packs: dict[str, CharacterPack] = {}
        self._active: str | None = None
        self.rescan()

    def rescan(self) -> None:
        self._packs = {}
        for child in sorted(self._dir.iterdir()) if self._dir.exists() else []:
            if child.is_dir() and (child / "character.yaml").exists():
                pack = load_pack(child)
                self._packs[pack.id] = pack

    def list(self) -> list[CharacterPack]:
        return list(self._packs.values())

    def activate(self, char_id: str | None) -> CharacterPack | None:
        """char_id=None/'none' で汎用モードへ。フォールバック連鎖(§16.3)。"""
        if not char_id or char_id == "none":
            self._active = None
            return None
        pack = self._packs.get(char_id)
        if pack and pack.valid:
            self._active = char_id
            return pack
        self._active = None  # 失敗時は汎用モードで動き続ける
        return None

    @property
    def active_id(self) -> str | None:
        return self._active

    def active_fragment(self) -> str | None:
        """アクティブなキャラの口調フラグメント。汎用モードでは None。"""
        pack = self._packs.get(self._active) if self._active else None
        if pack and pack.valid:
            return pack.system_fragment
        return None
