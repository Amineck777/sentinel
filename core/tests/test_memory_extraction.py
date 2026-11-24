"""長期記憶づくり(ADR 0116 の PR2)の検査。

- LLM の崩れた出力を寛容に読む(extractor.parse)
- 出来事・事実・訂正を1トランザクションで保存し、どこまで記憶にしたかを覚える(longterm)
- キーワード検索: 3文字の窓 + 2文字の漢字語。出来事はキャラ別、事実は共有
- 区切りで動かす予約係: 挨拶だけは飛ばす、3回失敗で飛ばす、話しかけたら止める(scheduler)
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from sentinel_core.api.app import create_app
from sentinel_core.character.registry import CharacterRegistry
from sentinel_core.llm.client import LLMUnavailableError
from sentinel_core.llm.openai_compat import OpenAICompatClient
from sentinel_core.memory.extractor import ExtractionError, build_messages, parse
from sentinel_core.memory.longterm import (
    Correction,
    Extraction,
    LongTermStore,
    NewEpisode,
    NewFact,
    PendingMessage,
    query_terms,
)
from sentinel_core.memory.scheduler import MemoryScheduler
from sentinel_core.memory.store import Store
from sentinel_core.settings import Settings

TOKEN = "test-token"
H = {"X-Sentinel-Token": TOKEN}


def _pm(i: int, role: str, content: str) -> PendingMessage:
    return PendingMessage(i, f"m{i}", role, content, "2026-11-24T01:00:00Z")


def _fact(content: str, category: str = "preference", **kw: Any) -> NewFact:
    base: dict[str, Any] = {
        "category": category,
        "content": content,
        "kind": "fact",
        "confidence": 0.9,
        "importance": 0.6,
        "expires_at": None,
        "source_message_ids": ["m1"],
    }
    base.update(kw)
    return NewFact(**base)


def _setup(tmp_path: Path) -> tuple[Store, LongTermStore]:
    store = Store(tmp_path / "t.db")  # 版5まで作る
    return store, LongTermStore(store.path)


def _talk(store: Store, char: str | None, *lines: tuple[str, str]) -> str:
    sid = store.ensure_session(None, char)
    for role, content in lines:
        store.add_message(sid, role, content, character_id=char)
    return sid


def _save(lt: LongTermStore, sid: str, char: str | None, result: Extraction) -> dict[str, int]:
    pending = lt.pending_messages(sid)
    return lt.save_extraction(
        session_id=sid,
        character_id=char,
        messages=pending,
        result=result,
        model="eva",
        started_at="2026-11-24T01:00:00Z",
        duration_ms=10,
    )


# --- LLM の出力を読む ---


def test_parse_accepts_fenced_json_and_cleans_values():
    pending = [_pm(1, "user", "コーヒーは苦手なんだ"), _pm(2, "assistant", "承知しました")]
    text = """はい、記録します。
```json
{"episode": {"summary": "マスターはコーヒーが苦手だと話した", "importance": 3},
 "facts": [
   {"category": "preference", "content": "マスターはコーヒーが苦手", "kind": "fact",
    "confidence": "0.9", "importance": 0.7, "expires_at": "来週", "sources": [1, 99]},
   {"category": "謎", "content": "マスターは猫が好き", "kind": "inference"},
   {"category": "plan", "content": ""}
 ],
 "corrections": [{"id": "F1", "action": "forget"}, {"id": "F9", "action": "forget"},
                 {"id": "F1", "action": "replace"}]}
```"""
    result = parse(text, pending, {"F1": "real-fact-id"})
    assert result.episode is not None
    assert result.episode.importance == 1.0  # 0〜1 に丸める
    assert result.episode.source_message_ids == ["m1", "m2"]
    first, second = result.facts  # 中身が空の事実は捨てる
    assert first.confidence == 0.9 and first.expires_at is None  # 日付でない期限は捨てる
    assert first.source_message_ids == ["m1"]  # 範囲外の番号は捨てる
    assert second.category == "other" and second.kind == "inference"
    assert second.source_message_ids == ["m1"]  # 出典が無ければマスターの発言
    # 知らない番号と、新しい内容の無い replace は捨てる
    assert result.corrections == [Correction("real-fact-id", "forget", None)]


def test_parse_rejects_text_without_json():
    with pytest.raises(ExtractionError):
        parse("すみません、できません", [], {})


def test_build_messages_numbers_lines_and_hides_real_fact_ids():
    pending = [_pm(1, "user", "ただいま"), _pm(2, "assistant", "お帰りなさいませ")]
    messages, ids = build_messages(
        pending, [{"id": "abc123", "content": "マスターは猫が好き"}], "エヴァ"
    )
    assert ids == {"F1": "abc123"}
    system, user = messages[0]["content"], messages[1]["content"]
    assert "記録係" in system and "エヴァ" in system and "{assistant}" not in system
    assert "F1: マスターは猫が好き" in user and "abc123" not in user
    assert "マスター: ただいま" in user and "エヴァ: お帰りなさいませ" in user
    assert "[1]" in user and "[2]" in user


# --- 保存 ---


def test_save_extraction_writes_all_and_advances_watermark(tmp_path: Path):
    store, lt = _setup(tmp_path)
    sid = _talk(store, "eva", ("user", "コーヒーは苦手"), ("assistant", "承知しました"))
    counts = _save(
        lt,
        sid,
        "eva",
        Extraction(
            NewEpisode("マスターはコーヒーが苦手と話した", 0.4, ["m1"]),
            [_fact("マスターはコーヒーが苦手")],
        ),
    )
    assert counts == {"episodes": 1, "facts": 1, "corrections": 0}
    assert lt.pending_messages(sid) == []  # 記憶にし終えた
    assert lt.sessions_with_pending() == []
    assert lt.list_episodes()[0]["character_id"] == "eva"
    fact = lt.list_facts()[0]
    assert fact["source_character_id"] == "eva" and fact["extractor_model"] == "eva"
    assert lt.list_jobs()[0]["status"] == "done"
    # 新しい発言が来たら、その分だけがまた「まだ記憶にしていない」になる
    store.add_message(sid, "user", "紅茶は好き", character_id="eva")
    assert [m.content for m in lt.pending_messages(sid)] == ["紅茶は好き"]


def test_replace_keeps_old_fact_as_superseded(tmp_path: Path):
    store, lt = _setup(tmp_path)
    sid = _talk(store, "eva", ("user", "コーヒーは苦手"))
    _save(lt, sid, "eva", Extraction(None, [_fact("マスターはコーヒーが苦手")]))
    old = lt.list_facts()[0]
    with lt._tx() as c:  # 固定枠に入れてあった、ということにする
        c.execute("UPDATE facts SET pinned=1 WHERE id=?", (old["id"],))

    store.add_message(sid, "user", "最近はコーヒーも飲めるようになった", character_id="eva")
    corr = Correction(old["id"], "replace", "マスターは最近コーヒーを飲めるようになった")
    assert _save(lt, sid, "eva", Extraction(None, [], [corr]))["corrections"] == 1

    facts = {f["content"]: f for f in lt.list_facts(include_inactive=True)}
    new = facts["マスターは最近コーヒーを飲めるようになった"]
    assert facts["マスターはコーヒーが苦手"]["status"] == "superseded"
    assert facts["マスターはコーヒーが苦手"]["superseded_by"] == new["id"]
    assert new["status"] == "active" and new["pinned"] == 1  # 固定枠は引き継ぐ
    assert [f["content"] for f in lt.list_facts()] == [new["content"]]


def test_forget_hides_fact_but_keeps_row(tmp_path: Path):
    store, lt = _setup(tmp_path)
    sid = _talk(store, None, ("user", "猫を飼っている"))
    _save(lt, sid, None, Extraction(None, [_fact("マスターは猫を飼っている")]))
    fid = lt.list_facts()[0]["id"]
    store.add_message(sid, "user", "さっきの猫の話は忘れて")
    _save(lt, sid, None, Extraction(None, [], [Correction(fid, "forget")]))
    assert lt.list_facts() == []
    assert lt.list_facts(include_inactive=True)[0]["status"] == "forgotten"
    assert lt.search_keyword("猫を飼って", None) == []  # 忘れたものは思い出さない


# --- キーワード検索 ---


def test_query_terms_make_trigrams_and_two_char_words():
    trigrams, short = query_terms("仕事の話。コーヒーは?")
    assert "コーヒ" in trigrams and "ーヒー" in trigrams  # 長音は区切りにしない
    assert "仕事" in short


def test_search_finds_facts_for_everyone_and_episodes_per_character(tmp_path: Path):
    store, lt = _setup(tmp_path)
    eva = _talk(store, "eva", ("user", "締め切りが金曜"))
    _save(
        lt,
        eva,
        "eva",
        Extraction(
            NewEpisode("マスターは金曜の締め切りに追われていた", 0.6, []),
            [_fact("マスターは仕事が忙しい", "work")],
        ),
    )
    # 事実はユウカでも見つかるが、エヴァとの出来事はユウカからは見えない
    assert [h.item_type for h in lt.search_keyword("仕事は順調?", "yuuka")] == ["fact"]
    hits = lt.search_keyword("金曜の締め切り", "eva")
    assert hits and hits[0].item_type == "episode"
    assert lt.search_keyword("金曜の締め切り", "yuuka") == []


# --- 予約係(scheduler) ---


class JsonLLM:
    """記憶係への呼び出しには JSON を、それ以外にはふつうの返事を返すモック。"""

    def __init__(self, payload: dict[str, Any] | str | None = None) -> None:
        self.payload = (
            payload
            if payload is not None
            else {
                "episode": {"summary": "マスターはカレーを作った", "importance": 0.4},
                "facts": [{"category": "habit", "content": "マスターは料理をする", "sources": [1]}],
                "corrections": [],
            }
        )
        self.extract_calls = 0
        self.gate: asyncio.Event | None = None  # セットされるまで記憶係の返事を待たせる

    async def stream_chat(self, messages, *, model=None) -> AsyncIterator[str]:
        if "記録係" in messages[0]["content"]:
            self.extract_calls += 1
            if self.gate is not None:
                await self.gate.wait()
            if isinstance(self.payload, Exception):
                raise self.payload
            yield self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        else:
            yield "かしこまりました。"

    async def is_reachable(self) -> bool:
        return True


def _scheduler(store: Store, llm: Any, tmp_path: Path, **kw: Any) -> MemoryScheduler:
    chars = CharacterRegistry(tmp_path / "characters")
    return MemoryScheduler(
        LongTermStore(store.path), llm, chars, "base", startup_delay_seconds=-1, **kw
    )


def test_run_pending_creates_memory_and_skips_greeting_only(tmp_path: Path):
    store, lt = _setup(tmp_path)
    _talk(store, None, ("user", "カレーを作った"), ("assistant", "おいしそうですね"))
    _talk(store, None, ("assistant", "おはようございます"))  # 挨拶だけのセッション
    llm = JsonLLM()
    result = asyncio.run(_scheduler(store, llm, tmp_path).run_pending())
    assert result == {"episodes": 1, "facts": 1, "corrections": 0, "failed": 0}
    assert llm.extract_calls == 1  # 挨拶だけのほうは LLM を呼ばない
    assert sorted(j["status"] for j in lt.list_jobs()) == ["done", "skipped"]
    assert lt.sessions_with_pending() == []


def test_long_conversation_is_split_into_chunks(tmp_path: Path):
    store, lt = _setup(tmp_path)
    _talk(store, None, *[("user", "あ" * 40) for _ in range(5)])  # 1件 44トークン
    llm = JsonLLM()
    asyncio.run(_scheduler(store, llm, tmp_path, chunk_tokens=100).run_pending())
    assert llm.extract_calls == 3  # 2件 + 2件 + 1件
    assert len(lt.list_episodes()) == 3


def test_broken_output_is_retried_then_skipped(tmp_path: Path):
    store, lt = _setup(tmp_path)
    _talk(store, None, ("user", "やあ"))
    llm = JsonLLM("JSON ではない返事")
    sched = _scheduler(store, llm, tmp_path)
    for _ in range(3):
        assert asyncio.run(sched.run_pending())["failed"] == 1
    assert lt.sessions_with_pending()  # 失敗だけでは先へ進まない(やり直す)
    asyncio.run(sched.run_pending())  # 4回目は諦めて飛ばす
    assert llm.extract_calls == 3
    assert lt.list_jobs()[0]["status"] == "skipped" and lt.sessions_with_pending() == []


def test_offline_llm_stops_the_run(tmp_path: Path):
    store, lt = _setup(tmp_path)
    _talk(store, None, ("user", "一つ目"))
    _talk(store, None, ("user", "二つ目"))
    llm = JsonLLM()
    llm.payload = LLMUnavailableError("オフライン")  # type: ignore[assignment]
    result = asyncio.run(_scheduler(store, llm, tmp_path).run_pending())
    assert result["failed"] == 1 and llm.extract_calls == 1  # 2つ目のセッションは試さない
    assert len(lt.sessions_with_pending()) == 2


def test_user_activity_cancels_running_extraction(tmp_path: Path):
    store, lt = _setup(tmp_path)
    _talk(store, None, ("user", "やあ"))
    llm = JsonLLM()
    llm.gate = asyncio.Event()  # 記憶係の返事を止めておく

    async def scenario() -> dict[str, int]:
        sched = _scheduler(store, llm, tmp_path)
        run = asyncio.create_task(sched.run_pending())
        while llm.extract_calls == 0:  # 記憶係が呼ばれるまで待つ
            await asyncio.sleep(0)
        sched.on_user_activity()  # マスターが話しかけた
        return await run

    assert asyncio.run(scenario())["episodes"] == 0
    assert lt.list_episodes() == [] and lt.list_jobs() == []  # 半端な記憶も記録も残らない
    assert lt.sessions_with_pending()  # あとでやり直す


def test_busy_chat_skips_run(tmp_path: Path):
    store, lt = _setup(tmp_path)
    _talk(store, None, ("user", "やあ"))
    llm = JsonLLM()
    asyncio.run(_scheduler(store, llm, tmp_path, is_busy=lambda: True).run_pending())
    assert llm.extract_calls == 0


# --- API 経由 ---


def test_extract_api_then_list_and_search(tmp_path: Path):
    settings = Settings.load(data_dir=tmp_path)
    app = create_app(settings=settings, token=TOKEN, dev=True, llm=JsonLLM())
    with TestClient(app) as c, c.websocket_connect(f"/v1/stream?token={TOKEN}") as ws:
        c.post("/v1/chat", headers=H, json={"content": "今日はカレーを作った"})
        while ws.receive_json()["type"] != "message_done":
            pass
        r = c.post("/v1/memory/extract", headers=H).json()["result"]
        assert r["episodes"] == 1 and r["facts"] == 1
        facts = c.get("/v1/memory/facts", headers=H).json()["facts"]
        assert [f["content"] for f in facts] == ["マスターは料理をする"]
        assert len(c.get("/v1/memory/episodes", headers=H).json()["episodes"]) == 1
        hits = c.get("/v1/memory/search", headers=H, params={"q": "料理をする?"}).json()["hits"]
        assert hits[0]["item_type"] == "fact"
        assert c.get("/v1/memory/jobs", headers=H).json()["jobs"][0]["status"] == "done"


# --- JSON で答えさせる呼び出し(OpenAI 互換)---


def test_complete_json_asks_for_json_and_falls_back():
    seen: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        payload = json.loads(req.content)
        seen.append(payload)
        if "response_format" in payload:
            return httpx.Response(400, text="unsupported")
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"facts": []}'}}]})

    async def run() -> str:
        client = OpenAICompatClient("http://llm/v1", "m")
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        text = await client.complete_json([{"role": "user", "content": "hi"}], model="eva")
        await client.aclose()
        return text

    assert asyncio.run(run()) == '{"facts": []}'
    assert seen[0]["response_format"] == {"type": "json_object"} and seen[0]["stream"] is False
    assert "response_format" not in seen[1] and seen[1]["model"] == "eva"
