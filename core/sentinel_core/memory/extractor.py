"""記憶づくり: 会話の原文から「出来事」と「マスターの事実」を取り出す(ADR 0116 論点1・2)。

LLM に会話を読ませ、JSON で書き出させる。モデルはチャットと同じもの(例: eva)を使い、
記憶係としての system を付けて呼ぶ。別のモデルを読み込ませないのは、8GB の VRAM に
2つ目のモデルを載せる余裕がないため(Ollama はモデル名が違うと読み込み直すことがある)。

LLM の出力は崩れることがある(余計な前置き、``` の囲み、範囲外の数値、知らない分類)。
ここで受け取り方を寛容にし、使えない項目だけ捨てる。全体が読めなければ例外にして、
呼び出し側(scheduler.py)が「失敗」として記録し、次の機会にやり直す。
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sentinel_core.llm.client import LLMClient
from sentinel_core.memory.longterm import (
    FACT_CATEGORIES,
    Correction,
    Extraction,
    NewEpisode,
    NewFact,
    PendingMessage,
)

# 記憶係への指示。人格は演じさせない(要約が口調に引きずられないように)
EXTRACTOR_SYSTEM = """あなたは会話の記録係です。キャラクターは演じません。
渡された会話を読み、長期記憶として残すものを JSON だけで書き出してください。前置きや説明は不要です。

出力の形:
{"episode": {"summary": "...", "importance": 0.5},
 "facts": [{"category": "preference", "content": "マスターは...", "kind": "fact",
            "confidence": 0.9, "importance": 0.6, "expires_at": null, "sources": [1]}],
 "corrections": [{"id": "F1", "action": "replace", "new_content": "マスターは..."}]}

episode(この会話で何があったか):
- summary は1〜3文。第三者の視点で「マスターは〜」「{assistant}は〜」と書く
- 「今日」「明日」などは、会話の日付から具体的な日付に直す
- importance は 0〜1。あいさつだけ・雑談だけなら 0.2 以下。大事な出来事や相談なら高く
- 残すほどの内容がまったく無ければ "episode": null

facts(マスター本人について、後の会話で役立つこと):
- 対象は、マスターの好み・苦手、予定、約束、仕事・学業、健康、人間関係、プロフィール、習慣
- {assistant}自身のこと、一般的な知識、その場限りのこと(「今お茶を飲んでいる」など)は入れない
- content は1文で、主語は「マスターは」
- category は次のどれか: profile / preference / plan / promise / work / health /
  relationship / habit / other
- kind は、マスターが自分で言ったなら "fact"、会話からの推測なら "inference"
- confidence(確かさ)と importance(大事さ)は 0〜1
- expires_at は、予定や約束で日付が分かれば "YYYY-MM-DD"、分からなければ null
- sources は根拠になった発言の番号の配列
- 冗談・仮定の話・ごっこ遊びは事実にしない
- 「すでに覚えていること」と同じ内容は書かない

corrections(「すでに覚えていること」が、この会話で変わったとき):
- 内容が変わった・間違いだった → {"id": "F番号", "action": "replace", "new_content": "新しい1文"}
- マスターが「忘れて」と言った → {"id": "F番号", "action": "forget"}
- 無ければ []
"""

# 1回の記憶づくりで受け付ける事実の数の上限(LLM が暴走して大量に書いたときの歯止め)
MAX_FACTS_PER_JOB = 12


class ExtractionError(ValueError):
    """LLM の出力から記憶を読み取れなかった。"""


def build_messages(
    pending: Sequence[PendingMessage],
    known_facts: Sequence[dict[str, Any]],
    assistant_name: str,
    now: datetime | None = None,
) -> tuple[list[dict[str, str]], dict[str, str]]:
    """記憶係に渡す messages と、「F番号 → 事実の本物の ID」の対応表を作る。

    事実の ID(32桁)をそのまま見せると LLM が書き写し間違えるので、短い番号に置き換える。
    """
    now = now or datetime.now().astimezone()
    fact_ids: dict[str, str] = {}
    known_lines: list[str] = []
    for i, fact in enumerate(known_facts, start=1):
        key = f"F{i}"
        fact_ids[key] = str(fact["id"])
        known_lines.append(f"{key}: {fact['content']}")

    convo_lines: list[str] = []
    for i, m in enumerate(pending, start=1):
        speaker = "マスター" if m.role == "user" else assistant_name
        convo_lines.append(f"[{i}] {_local_time(m.created_at)} {speaker}: {m.content}")

    user = (
        f"今日の日付: {now:%Y-%m-%d}({_WEEKDAYS[now.weekday()]})\n\n"
        "## すでに覚えていること\n"
        + ("\n".join(known_lines) if known_lines else "(まだ無し)")
        + "\n\n## 会話\n"
        + "\n".join(convo_lines)
    )
    system = EXTRACTOR_SYSTEM.replace("{assistant}", assistant_name)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}], fact_ids


async def extract(
    llm: LLMClient,
    pending: Sequence[PendingMessage],
    known_facts: Sequence[dict[str, Any]],
    assistant_name: str,
    model: str | None,
) -> Extraction:
    """LLM に記憶を取り出させる。読み取れなければ ExtractionError。"""
    messages, fact_ids = build_messages(pending, known_facts, assistant_name)
    # JSON だけを返させる指定が使えるクライアント(OpenAICompatClient)ならそれを使う。
    # 無ければ(テスト用のモックなど)ふつうのストリームを集めて読む
    complete_json = getattr(llm, "complete_json", None)
    if complete_json is not None:
        text = await complete_json(messages, model=model)
    else:
        text = "".join([d async for d in llm.stream_chat(messages, model=model)])
    return parse(text, pending, fact_ids)


def parse(text: str, pending: Sequence[PendingMessage], fact_ids: dict[str, str]) -> Extraction:
    """LLM の出力(JSON のはず)を Extraction に直す。使えない項目は黙って捨てる。"""
    data = _load_json(text)
    episode = _episode(data.get("episode"), pending)
    facts = [f for f in (_fact(x, pending) for x in _list(data.get("facts"))) if f]
    corrections = [
        c for c in (_correction(x, fact_ids) for x in _list(data.get("corrections"))) if c
    ]
    return Extraction(episode=episode, facts=facts[:MAX_FACTS_PER_JOB], corrections=corrections)


# --- ここから下は、崩れた出力を受け止めるための小さな関数 ---

_WEEKDAYS = "月火水木金土日"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _local_time(created_at: str) -> str:
    """DB の UTC 時刻を、利用者の PC の時刻(コアが動いている PC = 利用者の PC)で短く表す。"""
    try:
        t = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return ""
    return t.astimezone().strftime("%m-%d %H:%M")


def _load_json(text: str) -> dict[str, Any]:
    # ```json ... ``` の囲みや前置きがあっても、最初の { から最後の } までを読む
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ExtractionError(f"JSON が見つかりません: {text[:80]!r}")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise ExtractionError(f"JSON として読めません: {e}") from e
    if not isinstance(data, dict):
        raise ExtractionError("JSON の一番外側がオブジェクトではありません")
    return data


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _ratio(value: Any, default: float) -> float:
    """0〜1 の数に丸める。数でなければ default。"""
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    return min(1.0, max(0.0, x))


def _sources(value: Any, pending: Sequence[PendingMessage]) -> list[str]:
    """発言番号の配列を、発言の本物の ID に直す。範囲外の番号は捨てる。"""
    ids: list[str] = []
    for n in _list(value):
        if isinstance(n, int) and 1 <= n <= len(pending):
            mid = pending[n - 1].id
            if mid not in ids:
                ids.append(mid)
    return ids


def _episode(value: Any, pending: Sequence[PendingMessage]) -> NewEpisode | None:
    if not isinstance(value, dict):
        return None
    summary = str(value.get("summary") or "").strip()
    if not summary:
        return None
    return NewEpisode(
        summary=summary,
        importance=_ratio(value.get("importance"), 0.3),
        # 出来事の出典は、そのまとまりの発言すべて
        source_message_ids=[m.id for m in pending],
    )


def _fact(value: Any, pending: Sequence[PendingMessage]) -> NewFact | None:
    if not isinstance(value, dict):
        return None
    content = str(value.get("content") or "").strip()
    if not content:
        return None
    category = str(value.get("category") or "other")
    expires = value.get("expires_at")
    sources = _sources(value.get("sources"), pending)
    return NewFact(
        category=category if category in FACT_CATEGORIES else "other",
        content=content,
        kind="inference" if value.get("kind") == "inference" else "fact",
        confidence=_ratio(value.get("confidence"), 0.5),
        importance=_ratio(value.get("importance"), 0.5),
        expires_at=expires if isinstance(expires, str) and _DATE.match(expires) else None,
        # 出典の番号が無ければ、そのまとまりのマスターの発言を出典にする(原文へ戻れるように)
        source_message_ids=sources or [m.id for m in pending if m.role == "user"],
    )


def _correction(value: Any, fact_ids: dict[str, str]) -> Correction | None:
    if not isinstance(value, dict):
        return None
    real_id = fact_ids.get(str(value.get("id") or ""))
    action = value.get("action")
    if real_id is None or action not in ("replace", "forget"):
        return None
    new_content = str(value.get("new_content") or "").strip() or None
    if action == "replace" and new_content is None:
        return None
    return Correction(fact_id=real_id, action=str(action), new_content=new_content)
