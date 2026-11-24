"""長期記憶(出来事と事実)の読み書き(ADR 0116 の PR2)。

表の形は store.py の版5。ここは「記憶づくりの結果を保存する」「探す」「一覧する」を受け持つ。
原文(messages)は読むだけで、書き換えない(原文は消さない一次記録。ADR 0105)。

保存の決まり:
- 1回の記憶づくり(1つの会話のまとまり)の結果は、1トランザクションでまとめて書く。
  途中で失敗・中断しても、半端な記憶が残らない
- 事実の訂正は上書きしない。古い方を superseded にして、新しい方を superseded_by で指す
- キーワード検索の索引(memory_fts)は、出来事・事実を書くのと同じトランザクションで足す
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sentinel_core.memory.store import now_iso

# 事実の分類。記憶づくりの LLM にもこの中から選ばせる(それ以外は other に寄せる)
FACT_CATEGORIES = (
    "profile",  # 名前・年齢・住んでいる所など
    "preference",  # 好き・嫌い・苦手
    "plan",  # 予定
    "promise",  # 約束(エヴァとの約束も含む)
    "work",  # 仕事・学業
    "health",  # 体調・健康
    "relationship",  # 人間関係
    "habit",  # 習慣
    "other",
)


@dataclass
class NewEpisode:
    summary: str
    importance: float
    source_message_ids: list[str]


@dataclass
class NewFact:
    category: str
    content: str
    kind: str  # "fact"(本人が言った)/ "inference"(推測)
    confidence: float
    importance: float
    expires_at: str | None
    source_message_ids: list[str]


@dataclass
class Correction:
    fact_id: str  # 訂正される既存の事実の ID(DB の本物の ID)
    action: str  # "replace" / "forget"
    new_content: str | None = None


@dataclass
class Extraction:
    """記憶づくり1回分の結果(memory/extractor.py が作る)。"""

    episode: NewEpisode | None
    facts: list[NewFact] = field(default_factory=list)
    corrections: list[Correction] = field(default_factory=list)


@dataclass
class PendingMessage:
    """まだ記憶にしていない発言。rowid は「どこまで記憶にしたか」の目印に使う。"""

    rowid: int
    id: str
    role: str
    content: str
    created_at: str


@dataclass
class MemoryHit:
    """検索で見つかった記憶1件。score は小さいほど良い(FTS5 の bm25 の流儀)。"""

    item_type: str  # "fact" / "episode"
    item_id: str
    text: str
    score: float


def _new_id() -> str:
    return uuid.uuid4().hex


class LongTermStore:
    def __init__(self, db_path: Path) -> None:
        # テーブルは Store(store.py)が起動時に版5まで作ってある前提。同じファイルを開く
        self._path = db_path

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        """接続を開き、ブロックの終わりで commit(例外なら rollback)して閉じる。"""
        with closing(sqlite3.connect(self._path)) as c, c:
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys=ON")
            yield c

    # --- 記憶にしていない発言 ---
    def watermark(self, session_id: str) -> int:
        """そのセッションで、記憶にし終えた発言の rowid の最大値(まだ無ければ 0)。

        失敗(failed)の記録は目印にしない(次の機会にやり直すため)。
        ただし同じ範囲で3回失敗したら skipped を書いて先へ進む(scheduler.py)。
        """
        with self._tx() as c:
            row = c.execute(
                "SELECT MAX(to_rowid) FROM memory_jobs "
                "WHERE session_id=? AND status IN ('done','skipped')",
                (session_id,),
            ).fetchone()
        return int(row[0] or 0)

    def pending_messages(self, session_id: str) -> list[PendingMessage]:
        """そのセッションで、まだ記憶にしていない発言(古い順)。"""
        mark = self.watermark(session_id)
        with self._tx() as c:
            rows = c.execute(
                "SELECT rowid, id, role, content, created_at FROM messages "
                "WHERE session_id=? AND rowid>? AND role IN ('user','assistant') "
                "ORDER BY rowid",
                (session_id, mark),
            ).fetchall()
        return [PendingMessage(r[0], r[1], r[2], r[3], r[4]) for r in rows]

    def sessions_with_pending(self) -> list[tuple[str, str | None]]:
        """記憶にしていない発言が残っているセッション(session_id, character_id)。古い順。"""
        with self._tx() as c:
            rows = c.execute(
                "SELECT s.id, s.character_id FROM sessions s "
                "WHERE EXISTS (SELECT 1 FROM messages m WHERE m.session_id=s.id "
                "  AND m.role IN ('user','assistant') AND m.rowid > COALESCE("
                "    (SELECT MAX(j.to_rowid) FROM memory_jobs j WHERE j.session_id=s.id "
                "     AND j.status IN ('done','skipped')), 0)) "
                "ORDER BY s.updated_at, s.rowid"
            ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def failure_count(self, session_id: str, from_rowid: int) -> int:
        """同じ範囲(開始の rowid が同じ)で記憶づくりに失敗した回数。"""
        with self._tx() as c:
            row = c.execute(
                "SELECT COUNT(*) FROM memory_jobs "
                "WHERE session_id=? AND from_rowid=? AND status='failed'",
                (session_id, from_rowid),
            ).fetchone()
        return int(row[0])

    # --- 記憶づくりの結果を保存 ---
    def save_extraction(
        self,
        *,
        session_id: str,
        character_id: str | None,
        messages: list[PendingMessage],
        result: Extraction,
        model: str | None,
        started_at: str,
        duration_ms: int,
    ) -> dict[str, int]:
        """1回分の結果と、その記録(memory_jobs)を1トランザクションで書く。件数を返す。"""
        now = now_iso()
        counts = {"episodes": 0, "facts": 0, "corrections": 0}
        with self._tx() as c:
            if result.episode is not None:
                eid = _new_id()
                c.execute(
                    "INSERT INTO episodes(id,character_id,session_id,started_at,ended_at,summary,"
                    "importance,source_message_ids,extractor_model,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        eid,
                        character_id,
                        session_id,
                        messages[0].created_at,
                        messages[-1].created_at,
                        result.episode.summary,
                        result.episode.importance,
                        json.dumps(result.episode.source_message_ids),
                        model,
                        now,
                    ),
                )
                self._index(c, "episode", eid, result.episode.summary)
                counts["episodes"] = 1
            for fact in result.facts:
                self._insert_fact(c, fact, character_id, model, now)
                counts["facts"] += 1
            for corr in result.corrections:
                if self._apply_correction(c, corr, character_id, model, now, messages):
                    counts["corrections"] += 1
            c.execute(
                "INSERT INTO memory_jobs(id,session_id,character_id,from_rowid,to_rowid,status,"
                "model,n_episodes,n_facts,n_corrections,started_at,duration_ms) "
                "VALUES(?,?,?,?,?,'done',?,?,?,?,?,?)",
                (
                    _new_id(),
                    session_id,
                    character_id,
                    messages[0].rowid,
                    messages[-1].rowid,
                    model,
                    counts["episodes"],
                    counts["facts"],
                    counts["corrections"],
                    started_at,
                    duration_ms,
                ),
            )
        return counts

    def record_job(
        self,
        *,
        session_id: str,
        character_id: str | None,
        from_rowid: int,
        to_rowid: int,
        status: str,
        model: str | None,
        started_at: str,
        duration_ms: int | None,
        error: str | None,
    ) -> None:
        """記憶を作らなかった回(skipped / failed)の記録。"""
        with self._tx() as c:
            c.execute(
                "INSERT INTO memory_jobs(id,session_id,character_id,from_rowid,to_rowid,status,"
                "model,started_at,duration_ms,error) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    _new_id(),
                    session_id,
                    character_id,
                    from_rowid,
                    to_rowid,
                    status,
                    model,
                    started_at,
                    duration_ms,
                    error,
                ),
            )

    def _insert_fact(
        self,
        c: sqlite3.Connection,
        fact: NewFact,
        character_id: str | None,
        model: str | None,
        now: str,
    ) -> str:
        fid = _new_id()
        c.execute(
            "INSERT INTO facts(id,category,content,kind,confidence,importance,expires_at,"
            "source_message_ids,source_character_id,extractor_model,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                fid,
                fact.category,
                fact.content,
                fact.kind,
                fact.confidence,
                fact.importance,
                fact.expires_at,
                json.dumps(fact.source_message_ids),
                character_id,
                model,
                now,
                now,
            ),
        )
        self._index(c, "fact", fid, fact.content)
        return fid

    def _apply_correction(
        self,
        c: sqlite3.Connection,
        corr: Correction,
        character_id: str | None,
        model: str | None,
        now: str,
        messages: list[PendingMessage],
    ) -> bool:
        """既存の事実を置き換える/忘れる。対象が有効な事実でなければ何もしない(False)。"""
        old = c.execute(
            "SELECT * FROM facts WHERE id=? AND status='active'", (corr.fact_id,)
        ).fetchone()
        if old is None:
            return False
        if corr.action == "forget":
            # 忘れる = 思い出さないだけ。行も原文も残す(論点6の2。完全削除は画面から)
            c.execute(
                "UPDATE facts SET status='forgotten', updated_at=? WHERE id=?", (now, old["id"])
            )
            return True
        if corr.action == "replace" and corr.new_content:
            # 新しい事実を足し、古い方は「置き換え済み」にして新しい方を指す(上書きしない)
            new_id = self._insert_fact(
                c,
                NewFact(
                    category=old["category"],
                    content=corr.new_content,
                    kind="fact",
                    confidence=max(float(old["confidence"]), 0.8),  # 本人の訂正なので高め
                    importance=float(old["importance"]),
                    expires_at=old["expires_at"],
                    source_message_ids=[m.id for m in messages],
                ),
                character_id,
                model,
                now,
            )
            c.execute(
                "UPDATE facts SET status='superseded', superseded_by=?, updated_at=? WHERE id=?",
                (new_id, now, old["id"]),
            )
            # 固定枠の指定は新しい方へ引き継ぐ
            if old["pinned"]:
                c.execute("UPDATE facts SET pinned=1 WHERE id=?", (new_id,))
            return True
        return False

    @staticmethod
    def _index(c: sqlite3.Connection, item_type: str, item_id: str, text: str) -> None:
        c.execute(
            "INSERT INTO memory_fts(text,item_type,item_id) VALUES(?,?,?)",
            (text, item_type, item_id),
        )

    # --- 読む ---
    def active_facts(self, limit: int = 40) -> list[dict[str, Any]]:
        """有効な事実を、固定枠 → 重要度 → 新しい順で。

        記憶づくりに「すでに覚えていること」として渡す(重複と訂正を見分けさせるため)。
        """
        with self._tx() as c:
            rows = c.execute(
                "SELECT * FROM facts WHERE status='active' "
                "ORDER BY pinned DESC, importance DESC, updated_at DESC, rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_facts(self, include_inactive: bool = False) -> list[dict[str, Any]]:
        """画面・確認用の一覧(新しい順)。"""
        where = "" if include_inactive else "WHERE status='active'"
        with self._tx() as c:
            rows = c.execute(f"SELECT * FROM facts {where} ORDER BY rowid DESC").fetchall()
        return [dict(r) for r in rows]

    def list_episodes(
        self, character_id: str | None = None, any_character: bool = True
    ) -> list[dict[str, Any]]:
        """画面・確認用の一覧(新しい順)。any_character=False ならそのキャラの分だけ。"""
        with self._tx() as c:
            if any_character:
                rows = c.execute(
                    "SELECT * FROM episodes WHERE status='active' "
                    "ORDER BY ended_at DESC, rowid DESC"
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM episodes WHERE status='active' AND character_id IS ? "
                    "ORDER BY ended_at DESC, rowid DESC",
                    (character_id,),
                ).fetchall()
        return [dict(r) for r in rows]

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._tx() as c:
            rows = c.execute(
                "SELECT * FROM memory_jobs ORDER BY rowid DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # --- キーワード検索 ---
    def search_keyword(
        self, query: str, character_id: str | None, limit: int = 10
    ) -> list[MemoryHit]:
        """キーワードで記憶を探す(ADR 0116 論点3 の片方。意味の検索は PR3)。

        - 事実は全キャラ共有、出来事は character_id のキャラのものだけ(論点5)
        - 3文字以上のかたまりは FTS5(trigram)で、2文字のかたまりは LIKE で探す
          (trigram は3文字未満の語を引けないため。「仕事」「映画」など)
        """
        trigrams, short_words = query_terms(query)
        hits: dict[tuple[str, str], MemoryHit] = {}
        with self._tx() as c:
            if trigrams:
                # 各3文字を OR でつなぐ。多く一致した記憶ほど bm25 の値が小さく(良く)なる
                match = " OR ".join('"' + t.replace('"', '""') + '"' for t in trigrams)
                rows = c.execute(
                    "SELECT item_type, item_id, text, bm25(memory_fts) AS score FROM memory_fts "
                    "WHERE memory_fts MATCH ? ORDER BY score LIMIT ?",
                    (match, limit * 4),  # 下で無効な記憶を外すので多めに取る
                ).fetchall()
                for r in rows:
                    hits.setdefault((r[0], r[1]), MemoryHit(r[0], r[1], r[2], float(r[3])))
            for word in short_words:
                like = f"%{word}%"
                for r in c.execute(
                    "SELECT item_type, item_id, text FROM memory_fts WHERE text LIKE ? LIMIT ?",
                    (like, limit * 4),
                ).fetchall():
                    # LIKE の一致は順位を付けられないので、FTS の一致より少し後ろに置く
                    hits.setdefault((r[0], r[1]), MemoryHit(r[0], r[1], r[2], 0.0))
            visible = self._visible_ids(c, character_id, list(hits))
        ranked = sorted((h for k, h in hits.items() if k in visible), key=lambda h: h.score)
        return ranked[:limit]

    @staticmethod
    def _visible_ids(
        c: sqlite3.Connection, character_id: str | None, keys: list[tuple[str, str]]
    ) -> set[tuple[str, str]]:
        """検索で見つかったもののうち、今のキャラが思い出してよい有効な記憶。"""
        out: set[tuple[str, str]] = set()
        for item_type, item_id in keys:
            if item_type == "fact":
                row = c.execute(
                    "SELECT 1 FROM facts WHERE id=? AND status='active'", (item_id,)
                ).fetchone()
            else:
                row = c.execute(
                    "SELECT 1 FROM episodes WHERE id=? AND status='active' AND character_id IS ?",
                    (item_id, character_id),
                ).fetchone()
            if row:
                out.add((item_type, item_id))
        return out


# 区切りとみなす文字(空白・句読点・記号)。この間の「かたまり」から検索語を作る
# (長音の「ー」は「コーヒー」のように語の中に出るので区切りにしない)
_SPLIT = re.compile(r"[\s、。,.!?！？「」『』()（）\[\]【】・:：;；\"'〜~]+")
# 漢字だけ・カタカナだけの並び。2文字の語(「仕事」「映画」「ゲーム」の一部など)を拾うため
_KANJI_OR_KATAKANA_RUN = re.compile(r"[\u4e00-\u9fff々]+|[\u30a1-\u30fa\u30fc]+")
# 3文字の窓をいくつまで使うか(長い発言で検索式が巨大にならないように)
MAX_TRIGRAMS = 64


def query_terms(query: str) -> tuple[list[str], list[str]]:
    """検索語を作る。(3文字の窓の一覧, 2文字のかたまりの一覧)。

    日本語は単語の区切りが無いので、かたまりを3文字ずつずらして切り出す(trigram)。
    例: 「コーヒーが苦手」→「コーヒ」「ーヒー」「ヒーが」…
    """
    trigrams: list[str] = []
    short: list[str] = []
    for chunk in _SPLIT.split(query):
        if len(chunk) >= 3:
            for i in range(len(chunk) - 2):
                gram = chunk[i : i + 3]
                if gram not in trigrams:
                    trigrams.append(gram)
        elif len(chunk) == 2 and chunk not in short:
            short.append(chunk)
        # 文の中の2文字の漢字語・カタカナ語(「仕事の話」の「仕事」)も LIKE で探す。
        # 「仕事の」「事の話」の3文字窓だけでは「仕事が忙しい」に一致しないため
        for run in _KANJI_OR_KATAKANA_RUN.findall(chunk):
            if len(run) == 2 and run not in short:
                short.append(run)
    return trigrams[:MAX_TRIGRAMS], short
