"""口調コンテキストの合成(仕様 §16.3 / 口調Lv1〜簡易Lv2)。

persona.md + speech_style.md + examples.jsonl(先頭N件)をシステムプロンプトへ
注入するフラグメントとして合成する。
Lv2の本実装(口調RAG・文体検査)は Track X1 で style_rag.py / style_check.py に分離予定。
"""

from __future__ import annotations

import json
from pathlib import Path

FEWSHOT_LIMIT = 8  # プロンプト予算対策。X1で口調RAG(場面検索)に置換する


def compose_system_fragment(pack_root: Path) -> str:
    parts: list[str] = []
    persona = pack_root / "persona" / "persona.md"
    style = pack_root / "persona" / "speech_style.md"
    examples = pack_root / "persona" / "examples.jsonl"

    if persona.exists():
        parts.append("# キャラクター人格\n" + persona.read_text(encoding="utf-8"))
    if style.exists():
        parts.append("# 口調ルール\n" + style.read_text(encoding="utf-8"))
    if examples.exists():
        lines = _fewshot_lines(examples)
        if lines:
            parts.append("# 話し方の参照例(この口調を維持する)\n" + "\n".join(lines))
    parts.append(
        "# 業務整合(必須)\nツール実行・承認確認・エラー報告では、キャラクターの口調を"
        "保ちつつ、内容の正確さと明瞭さを最優先すること。"
    )
    return "\n\n".join(parts)


def _fewshot_lines(examples_path: Path) -> list[str]:
    lines: list[str] = []
    for raw in examples_path.read_text(encoding="utf-8").splitlines():
        if len(lines) >= FEWSHOT_LIMIT:
            break
        if not raw.strip():
            continue
        try:
            ex = json.loads(raw)
            lines.append(f"[{ex.get('situation', '')}] {ex.get('reply', '')}")
        except json.JSONDecodeError:
            continue
    return lines
