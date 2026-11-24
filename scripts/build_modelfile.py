"""人格の文(1ファイル)から、Ollama の Modelfile の SYSTEM を作り直す(ADR 0116 論点4)。

人格の文の正は Pack の `persona/system.md`(llm.system_prompt: file)。アプリはそれを
コアが読んで記憶と一緒に送るが、`ollama run eva` で直接話すときは Modelfile の SYSTEM が
使われる。2か所を手で揃えると必ずずれるので、このスクリプトで Modelfile 側を上書きする。

使い方(Windows の例。1行ずつ):
    core\\.venv\\Scripts\\python.exe scripts\\build_modelfile.py
        --system persona_private\\sentinel_pack\\eva\\persona\\system.md
        --modelfile persona_private\\ollama\\Modelfile
    (実際は1行につなげて打つ)
    ollama create eva -f persona_private\\ollama\\Modelfile

- Modelfile の SYSTEM \"\"\"...\"\"\" の部分だけを置き換え、FROM・PARAMETER・MESSAGE は残す
- SYSTEM が無い Modelfile なら、FROM の行の次に足す
- 書き換える前の Modelfile は `Modelfile.bak` に残す
- 人格の文に \"\"\" が入っていると Modelfile が壊れるので、その場合は止める

最初の1回だけ、今の Modelfile の SYSTEM から人格の文のファイルを作る(逆向き):
    core\\.venv\\Scripts\\python.exe scripts\\build_modelfile.py --extract
        --system persona_private\\sentinel_pack\\eva\\persona\\system.md
        --modelfile persona_private\\ollama\\Modelfile
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

# SYSTEM """ ... """ の塊(複数行)。DOTALL で改行もまたぐ
_SYSTEM_BLOCK = re.compile(r'^SYSTEM\s+"""(.*?)"""', re.MULTILINE | re.DOTALL)
# FROM の行(SYSTEM が無いとき、この次に足す)
_FROM_LINE = re.compile(r"^FROM\s+.*$", re.MULTILINE)


def render(modelfile_text: str, system_text: str) -> str:
    """Modelfile の文字列の SYSTEM を system_text に差し替えた文字列を返す。"""
    system_text = system_text.strip()
    if '"""' in system_text:
        raise ValueError(
            '人格の文に """ が含まれています。Modelfile の区切りと衝突するので外してください'
        )
    block = f'SYSTEM """{system_text}"""'
    if _SYSTEM_BLOCK.search(modelfile_text):
        # 置き換え文字列の \ や \1 を解釈させないよう、関数で返す
        return _SYSTEM_BLOCK.sub(lambda _m: block, modelfile_text, count=1)
    m = _FROM_LINE.search(modelfile_text)
    if m is None:
        raise ValueError("Modelfile に FROM の行がありません")
    return modelfile_text[: m.end()] + "\n\n" + block + modelfile_text[m.end() :]


def extract(modelfile_text: str) -> str:
    """Modelfile の SYSTEM の中身を取り出す(人格の文のファイルを最初に作るとき用)。"""
    m = _SYSTEM_BLOCK.search(modelfile_text)
    if m is None:
        raise ValueError('Modelfile に SYSTEM """...""" がありません')
    return m.group(1).strip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="persona/system.md から Modelfile の SYSTEM を作る")
    ap.add_argument(
        "--system", required=True, type=Path, help="人格の文(Pack の persona/system.md)"
    )
    ap.add_argument("--modelfile", required=True, type=Path, help="書き換える Modelfile")
    ap.add_argument(
        "--extract",
        action="store_true",
        help="逆向き: Modelfile の SYSTEM から --system のファイルを作る(既にあれば止める)",
    )
    args = ap.parse_args(argv)

    if args.extract:
        if args.system.exists():
            # 正のファイルを誤って上書きしないよう、既にあるときは何もしない
            print(f"エラー: {args.system} は既にあります。上書きしません", file=sys.stderr)
            return 1
        try:
            text = extract(args.modelfile.read_text(encoding="utf-8"))
        except ValueError as e:
            print(f"エラー: {e}", file=sys.stderr)
            return 1
        args.system.parent.mkdir(parents=True, exist_ok=True)
        args.system.write_text(text, encoding="utf-8")
        print(f"人格の文を書き出しました: {args.system}")
        return 0

    system_text = args.system.read_text(encoding="utf-8")
    original = args.modelfile.read_text(encoding="utf-8")
    try:
        updated = render(original, system_text)
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    if updated == original:
        print("変更なし(Modelfile の SYSTEM はすでに人格の文と同じです)")
        return 0
    shutil.copyfile(args.modelfile, args.modelfile.with_name(args.modelfile.name + ".bak"))
    args.modelfile.write_text(updated, encoding="utf-8")
    print(f"更新しました: {args.modelfile}(元の内容は {args.modelfile.name}.bak)")
    print("反映するには: ollama create <モデル名> -f <Modelfile>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
