"""基本人格・ツール方針プロンプト(キャラ非依存の土台。仕様 §5.1 agent/prompts)。

キャラクター(Character Pack)の口調フラグメントはここで合成する。
依存方向は agent → character(agentは「口調コンテキストを受け取る」だけ。§5.2)。
"""
from __future__ import annotations

BASE_SYSTEM_PROMPT = (
    "あなたはSENTINEL、ユーザーのPC上で動作するローカルアシスタントです。"
    "正確さを最優先し、わからないことは推測で断定しないでください。"
    "破壊的な操作は必ずユーザーの確認を取る方針で振る舞ってください。"
)


def system_prompt(character_fragment: str | None = None) -> str:
    """土台プロンプトにキャラクター口調フラグメント(任意)を合成する。"""
    if character_fragment:
        return BASE_SYSTEM_PROMPT + "\n\n" + character_fragment
    return BASE_SYSTEM_PROMPT
