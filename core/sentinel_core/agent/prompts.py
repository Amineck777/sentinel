"""基本人格・ツール方針プロンプト(キャラ非依存の土台。仕様 §5.1 agent/prompts)。

キャラクター(Character Pack)の口調フラグメントはここで合成する。
依存方向は agent → character(agentは「口調コンテキストを受け取る」だけ。§5.2)。
"""

from __future__ import annotations

import hashlib

from sentinel_core.character.pack import CharacterPack

# プロンプトの組み立て方の版。組み立ての規則(順番・見出し・記憶の入れ方など)を
# 変えたら上げる。自己観測ログ(turn_logs)に残し、変更の前後で応答を比べられるようにする
PROMPT_VERSION = "2026-11-24.1"

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


def build_system(pack: CharacterPack | None, fragment: str | None) -> str | None:
    """このターンで送る system の文。None なら system を送らない。

    - Pack が file モード: 人格の文(ファイル)をそのまま使う。人格の文が完結しているので、
      SENTINEL の土台プロンプトは足さない(足すと「あなたはSENTINEL」と人格がぶつかる)
    - Pack が model モード: 送らない(送ると Ollama が Modelfile の SYSTEM を捨てるため)
    - それ以外(pack モード・汎用モード): 土台プロンプト + 口調フラグメント
    記憶(ADR 0116)は、ここで組み立てた文の後ろに足す予定(PR3)。
    """
    if pack and pack.system_text:
        return pack.system_text
    if pack and pack.use_model_system:
        return None
    return system_prompt(fragment)


def persona_hash(system: str | None) -> str | None:
    """人格の版の指紋(system の SHA-256 の先頭12桁)。system を送らないときは None。

    人格の文を書き換えると値が変わるので、観測ログで「いつ人格を変えたか」が分かる。
    """
    if system is None:
        return None
    return hashlib.sha256(system.encode("utf-8")).hexdigest()[:12]
