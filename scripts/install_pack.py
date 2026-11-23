"""Character Pack を、コアが読む場所({APP_DATA}/sentinel/characters/)へ入れる。

使い方(リポジトリ直下から):
  core\\.venv\\Scripts\\python.exe scripts\\install_pack.py <Packフォルダ>

例: 主人格のような私的な Pack はリポジトリの外(git に入らない場所)に置いておき、
この script でコピーする。リポジトリの中には Pack を置かない(.gitignore でも防ぐ)。
同じ id の Pack が既にあれば、中身を入れ替える(元は characters_backup/<id> へ退避。
characters/ の中に残すと、同じ id の Pack が2つ読まれてしまうため外に置く)。
コアの仮想環境(core\\.venv)の python で動かす(sentinel_core を読むため)。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import yaml
from sentinel_core.character.pack import load_pack
from sentinel_core.settings import Settings


def main(src_arg: str) -> int:
    src = Path(src_arg).expanduser().resolve()
    if not (src / "character.yaml").exists():
        print(f"character.yaml が見つかりません: {src}")
        return 1
    pack = load_pack(src)
    if not pack.valid:
        print(f"Pack が不正です: {pack.error}")
        return 1
    manifest = yaml.safe_load((src / "character.yaml").read_text(encoding="utf-8"))
    pack_id = str(manifest["id"])

    dest_root = Settings.load().characters_dir
    dest = dest_root / pack_id
    if dest.exists():
        backup = dest_root.parent / "characters_backup" / pack_id
        if backup.exists():
            shutil.rmtree(backup)
        backup.parent.mkdir(parents=True, exist_ok=True)
        dest.rename(backup)
        print(f"既存の Pack を退避しました: {backup}")
    shutil.copytree(src, dest)
    print(f"入れました: {dest}")
    print(
        f"表示名: {pack.display_name} / モデル: {pack.model or '(設定の llm.chat_model)'}"
    )
    print("コアを再起動するか、画面右上の character を開き直すと選べます。")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
