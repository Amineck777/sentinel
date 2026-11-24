"""記憶づくりをいつ動かすか(ADR 0116 論点2: 会話の区切り)。

GPU(8GB)はチャットの生成と記憶づくりを同時にこなせない。そこで:
- マスターが話しかけたら、動いている記憶づくりを止める(会話を優先。途中の結果は捨てる)
- 返答が終わってから idle_seconds(既定15分)何も無ければ、まだ記憶にしていない発言をまとめて処理する
- 起動の少しあと(startup_delay_seconds)にも処理する。前回、強制終了などで作れなかった分のため
- アプリ終了時にも、時間を区切って処理を試みる

途中で止めても半端な記憶は残らない。結果は最後に1トランザクションで書くため(longterm.py)。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable

from sentinel_core.character.registry import CharacterRegistry
from sentinel_core.llm.client import LLMClient, LLMUnavailableError
from sentinel_core.memory.budget import estimate_message_tokens
from sentinel_core.memory.extractor import ExtractionError, extract
from sentinel_core.memory.longterm import LongTermStore, PendingMessage
from sentinel_core.memory.store import now_iso

log = logging.getLogger("sentinel.memory")

# 同じ範囲で何回失敗したら諦めて先へ進むか(壊れた出力が続くと、毎回やり直して GPU を使い続けるため)
MAX_FAILURES = 3


class MemoryScheduler:
    def __init__(
        self,
        longterm: LongTermStore,
        llm: LLMClient,
        characters: CharacterRegistry,
        default_model: str,
        *,
        idle_seconds: float = 900,
        startup_delay_seconds: float = 30,
        chunk_tokens: int = 2500,
        is_busy: Callable[[], bool] = lambda: False,
    ) -> None:
        self._lt = longterm
        self._llm = llm
        self._characters = characters
        self._default_model = default_model  # 記録用(Pack がモデルを指定しないときの名前)
        self._idle_seconds = idle_seconds
        self._startup_delay = startup_delay_seconds
        # 1回の記憶づくりで LLM に読ませる会話の量。長い会話は、この大きさで区切って何回かに分ける
        self._chunk_tokens = chunk_tokens
        # チャットが生成中かどうか(ChatService が教える)。生成中は記憶づくりを始めない
        self._is_busy = is_busy
        self._timer: asyncio.Task[None] | None = None  # 区切りを待つタイマー
        self._job: asyncio.Task[dict[str, int]] | None = None  # 動いている記憶づくり
        self._lock = asyncio.Lock()  # 記憶づくりは同時に1つだけ

    # --- 合図(ChatService / app.py から呼ぶ) ---
    def start(self) -> None:
        """起動時に呼ぶ。少し待ってから、前回の積み残しを処理する。"""
        if self._startup_delay >= 0:
            self._restart_timer(self._startup_delay)

    def on_user_activity(self) -> None:
        """マスターが話しかけた/キャラが話し始める。記憶づくりを止め、タイマーも止める。"""
        self._cancel_timer()
        if self._job and not self._job.done():
            self._job.cancel()  # GPU を会話に譲る。結果は書かれずに捨てられる

    def on_turn_finished(self) -> None:
        """返答が終わった。ここから idle_seconds 何も無ければ記憶を作る。"""
        self._restart_timer(self._idle_seconds)

    async def aclose(self, flush_timeout: float = 0) -> None:
        """終了時に呼ぶ。flush_timeout 秒まで、残りの記憶づくりを試みる。"""
        self._cancel_timer()
        if flush_timeout > 0:
            with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(self.run_pending(), timeout=flush_timeout)
        if self._job and not self._job.done():
            self._job.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._job

    # --- 本体 ---
    async def run_pending(self) -> dict[str, int]:
        """記憶にしていない発言を、すべてのセッションについて処理する。件数の合計を返す。

        チャットの生成中なら何もしない(返答が終われば on_turn_finished でまた予約される)。
        """
        if self._is_busy():
            return {"episodes": 0, "facts": 0, "corrections": 0, "failed": 0}
        async with self._lock:
            self._job = asyncio.get_running_loop().create_task(self._run_all())
            try:
                return await self._job
            except asyncio.CancelledError:
                # on_user_activity で止めた。呼び出し元(タイマーや API)には「0件」と返す
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise  # 呼び出し元自身が止められたときは、そのまま伝える
                return {"episodes": 0, "facts": 0, "corrections": 0, "failed": 0}
            finally:
                self._job = None

    async def _run_all(self) -> dict[str, int]:
        total = {"episodes": 0, "facts": 0, "corrections": 0, "failed": 0}
        for session_id, character_id in self._lt.sessions_with_pending():
            try:
                counts = await self._run_session(session_id, character_id)
            except LLMUnavailableError as e:
                # 推論サーバーが止まっている。ほかのセッションも無理なので、今回は終わり
                log.warning("記憶づくりを中断しました(推論サーバーに接続できません): %s", e)
                total["failed"] += 1
                break
            for k, v in counts.items():
                total[k] += v
        return total

    async def _run_session(self, session_id: str, character_id: str | None) -> dict[str, int]:
        total = {"episodes": 0, "facts": 0, "corrections": 0, "failed": 0}
        pack = self._characters.get(character_id)
        model = pack.model if pack and pack.model else None  # None = 設定の llm.chat_model
        model_name = model or self._default_model
        name = pack.display_name if pack else "アシスタント"
        for chunk in self._chunks(self._lt.pending_messages(session_id)):
            started_at = now_iso()
            t0 = time.monotonic()

            def record(
                status: str,
                error: str,
                ms: int = 0,
                part: list[PendingMessage] = chunk,  # 今のまとまりを既定値で固定する
                started: str = started_at,
            ) -> None:
                """記憶を作らなかった回(飛ばした・失敗した)を記録する。"""
                self._lt.record_job(
                    session_id=session_id,
                    character_id=character_id,
                    from_rowid=part[0].rowid,
                    to_rowid=part[-1].rowid,
                    status=status,
                    model=model_name,
                    started_at=started,
                    duration_ms=ms,
                    error=error,
                )

            if not any(m.role == "user" for m in chunk):
                # キャラの挨拶だけ、などマスターの発言が無いまとまりは記憶にしない
                record("skipped", "マスターの発言なし")
                continue
            if self._lt.failure_count(session_id, chunk[0].rowid) >= MAX_FAILURES:
                record("skipped", f"{MAX_FAILURES}回失敗したため飛ばした")
                continue
            try:
                result = await extract(self._llm, chunk, self._lt.active_facts(), name, model)
            except ExtractionError as e:
                record("failed", str(e), int((time.monotonic() - t0) * 1000))
                total["failed"] += 1
                continue
            except LLMUnavailableError as e:
                record("failed", str(e), int((time.monotonic() - t0) * 1000))
                raise
            counts = self._lt.save_extraction(
                session_id=session_id,
                character_id=character_id,
                messages=chunk,
                result=result,
                model=model_name,
                started_at=started_at,
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
            for k, v in counts.items():
                total[k] += v
            log.info("記憶を作りました: %s %s", session_id, counts)
        return total

    def _chunks(self, pending: list[PendingMessage]) -> list[list[PendingMessage]]:
        """発言を、chunk_tokens に収まる大きさのまとまりに区切る(古い順)。"""
        chunks: list[list[PendingMessage]] = []
        current: list[PendingMessage] = []
        used = 0
        for m in pending:
            cost = estimate_message_tokens(m.content)
            if current and used + cost > self._chunk_tokens:
                chunks.append(current)
                current, used = [], 0
            current.append(m)
            used += cost
        if current:
            chunks.append(current)
        return chunks

    # --- タイマー ---
    def _restart_timer(self, delay: float) -> None:
        self._cancel_timer()
        self._timer = asyncio.get_running_loop().create_task(self._fire_after(delay))

    def _cancel_timer(self) -> None:
        if self._timer and not self._timer.done():
            self._timer.cancel()
        self._timer = None

    async def _fire_after(self, delay: float) -> None:
        await asyncio.sleep(delay)
        try:
            await self.run_pending()
        except Exception:  # 記憶づくりの失敗で、コア全体を落とさない
            log.exception("記憶づくりで予期しないエラー")
