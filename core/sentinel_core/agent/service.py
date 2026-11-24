"""会話ターンの実行(仕様 §3.3 の実行モデルのPhase 1形)。

POST /v1/chat から呼ばれ、即座に (session_id, message_id) を返し、
生成本体はバックグラウンドタスクが hub へ token/message_done イベントを流す。
この生成部は Pydantic AI のエージェント実行へ差し替える予定(ADR-0102)。
差し替え点をこのクラスに閉じ込めてある。
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Coroutine
from datetime import datetime
from typing import Any

from sentinel_core.agent.prompts import PROMPT_VERSION, build_system, persona_hash
from sentinel_core.character.registry import CharacterRegistry
from sentinel_core.events import EventHub
from sentinel_core.expression import TurnExpression
from sentinel_core.llm.client import LLMClient, LLMUnavailableError
from sentinel_core.memory.budget import estimate_message_tokens
from sentinel_core.memory.store import Store, now_iso
from sentinel_core.tts.service import SpeechService


def _part_of_day(hour: int) -> str:
    if 5 <= hour < 11:
        return "朝"
    if 11 <= hour < 17:
        return "昼"
    if 17 <= hour < 23:
        return "夜"
    return "深夜"


def greeting_cue(now: datetime | None = None) -> str:
    """起動時の挨拶を促す合図。LLMには user として渡すが、会話履歴には保存しない。

    コアは利用者のPC上で動くので、ローカル時刻 = 利用者の時刻。時間帯に合った挨拶にするため渡す。
    """
    now = now or datetime.now()
    return (
        f"(マスターがアプリを起動しました。今は{now.hour}時{now.minute:02d}分、"
        f"{_part_of_day(now.hour)}です。あなたから先に、短く挨拶してください。"
        "この括弧の文そのものには触れないでください)"
    )


class ChatService:
    def __init__(
        self,
        store: Store,
        llm: LLMClient,
        characters: CharacterRegistry,
        hub: EventHub,
        default_model: str,
        speech: SpeechService | None = None,
        short_term_tokens: int = 2500,
        session_resume_hours: float = 6,
    ) -> None:
        self._store = store
        # 短期記憶(直近の会話をそのまま渡す分)の上限と、再起動後に会話を続ける時間(ADR 0116)
        self._short_term_tokens = short_term_tokens
        self._session_resume_hours = session_resume_hours
        self._speech = speech  # 返答の読み上げ。None なら声なし
        self._default_model = default_model  # 記録用(Packがモデルを指定しないときの名前)
        self._llm = llm
        self._characters = characters
        self._hub = hub
        # asyncio.Task は強参照を保持しないとGCで途中終了し得るため、ここで持つ
        self._tasks: set[asyncio.Task[None]] = set()
        # セッション毎の生成直列化ロック。生成中の追い打ち送信で token イベントが
        # 交錯するのを防ぐ。エントリは解放しない(個人利用のセッション数では
        # 問題にならず、解放処理は取得との競合を生むため)
        self._session_locks: dict[str, asyncio.Lock] = {}

    def start_turn(
        self,
        content: str,
        session_id: str | None = None,
        character_id: str | None = None,
    ) -> tuple[str, str]:
        """ユーザー発話を保存し、生成をバックグラウンドで開始する。"""
        if character_id is not None:
            self._characters.activate(character_id)
        sid = self._resolve_session(session_id)
        mid = self._store.add_message(sid, "user", content, character_id=self._characters.active_id)
        self._spawn(self._generate(sid))
        return sid, mid

    def start_greeting(self, session_id: str | None = None) -> str | None:
        """キャラから先に挨拶するターンを始める(起動時・キャラ切替時)。

        汎用モードでは挨拶しない(None を返す)。合図の文は保存せず、挨拶だけを
        assistant の発言として残す(次のターンからはその挨拶が履歴の先頭になる)。
        """
        if self._characters.active_pack() is None:
            return None
        sid = self._resolve_session(session_id)
        self._spawn(self._generate(sid, cue=greeting_cue()))
        return sid

    def _resolve_session(self, session_id: str | None) -> str:
        """このターンで使うセッションを決める(ADR 0116 の短期記憶)。

        1. 画面が渡したセッションが今のキャラのものなら、それを続ける
        2. そうでなければ(起動直後・別キャラのセッション)、今のキャラと最後に話した
           セッションが session_resume_hours 以内なら、それを続ける(再起動しても会話が切れない)
        3. どちらでもなければ新しいセッション
        別キャラのセッションを続けないのは、出来事をキャラ別に覚えるため(論点5)。
        """
        active = self._characters.active_id
        if session_id:
            found, owner = self._store.session_owner(session_id)
            if not found:
                # 画面が自分で決めた新しい ID。そのまま作る(今までと同じ振る舞い)
                return self._store.ensure_session(session_id, active)
            if owner == active:
                return session_id
        resumed = self._store.resumable_session(active, self._session_resume_hours)
        return resumed or self._store.ensure_session(None, active)

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _generate(self, session_id: str, cue: str | None = None) -> None:
        lock = self._session_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            await self._generate_turn(session_id, cue)

    def active_model(self) -> str:
        """今のキャラで使うモデル名(Packの指定 > 設定の llm.chat_model)。"""
        pack = self._characters.active_pack()
        return (pack.model if pack else None) or self._default_model

    async def _generate_turn(self, session_id: str, cue: str | None = None) -> None:
        pack = self._characters.active_pack()
        character_id = self._characters.active_id
        messages: list[dict[str, str]] = []
        # system の文(None なら送らない)。決め方は prompts.build_system
        system = build_system(pack, self._characters.active_fragment())
        if system is not None:
            messages.append({"role": "system", "content": system})
        # 短期記憶: 直近の会話を、トークン数の上限まで新しい順に(memory/store.py)
        messages += self._store.recent_history(session_id, self._short_term_tokens)
        if cue:  # 保存しない合図(挨拶など)。履歴の最後に user として足す
            messages.append({"role": "user", "content": cue})
        model = self.active_model()

        # --- 自己観測ログ用の計測(ADR 0116 論点7)---
        started_at = now_iso()
        t0 = time.monotonic()
        first_token_ms: int | None = None
        error: str | None = None

        parts: list[str] = []
        # 声がオンなら、文が閉じるたびに合成を始める(全文を待たずに話し始める)
        utter = self._speech.begin(session_id) if self._speech else None
        # 感情タグを抜き、文ごとに表情を決める(expression.py)
        expr = TurnExpression()
        shown_emotion = "neutral"

        async def emit(clean: str, sentences: list[tuple[str, str]]) -> None:
            nonlocal shown_emotion, first_token_ms
            if clean and first_token_ms is None:
                # 最初の文字が画面に出るまでの時間。体感の速さに一番効く数字
                first_token_ms = int((time.monotonic() - t0) * 1000)
            if clean:
                parts.append(clean)
                await self._hub.publish({"type": "token", "session_id": session_id, "delta": clean})
            for text, emotion in sentences:
                if emotion != shown_emotion:
                    shown_emotion = emotion
                    await self._hub.publish(
                        {"type": "emotion", "session_id": session_id, "emotion": emotion}
                    )
                if utter:
                    utter.say(text, emotion)

        try:
            async for delta in self._llm.stream_chat(messages, model=pack.model if pack else None):
                await emit(*expr.feed(delta))
        except LLMUnavailableError as e:
            # オフライン応答などの案内文は通知として見せ、履歴には残さない
            error = str(e)
            await self._hub.publish({"type": "notice", "level": "warn", "text": str(e)})
        except Exception as e:  # 予期しない失敗もUIへ通知して終端する(無言で固まらせない)
            error = f"生成エラー: {e}"
            await self._hub.publish({"type": "notice", "level": "error", "text": error})

        finally:
            # 閉じずに終わった最後の文も表示・読み上げる
            await emit(*expr.flush())
            if utter:
                utter.finish()  # 残りの文を読み、ターンの終わり(audio_done)を知らせる

        # 保存するのはモデルが実際に生成した文だけ(途中で切れた場合はそこまで)。
        # 何も生成されなかったターンは assistant 発言を作らない
        full = "".join(parts)
        mid = (
            self._store.add_message(
                session_id, "assistant", full, model=model, character_id=character_id
            )
            if full
            else None
        )
        # 返答できなかったターンも、失敗の記録として観測ログには残す
        self._log_turn(
            session_id=session_id,
            message_id=mid,
            character_id=character_id,
            model=model,
            system=system,
            messages=messages,
            started_at=started_at,
            first_token_ms=first_token_ms,
            total_ms=int((time.monotonic() - t0) * 1000),
            error=error,
        )
        if mid is None:
            return
        await self._hub.publish(
            {"type": "message_done", "session_id": session_id, "message_id": mid}
        )

    def _log_turn(
        self,
        *,
        session_id: str,
        message_id: str | None,
        character_id: str | None,
        model: str,
        system: str | None,
        messages: list[dict[str, str]],
        started_at: str,
        first_token_ms: int | None,
        total_ms: int,
        error: str | None,
    ) -> None:
        """自己観測ログを1件書く。ログの失敗で会話を止めないよう、例外は握りつぶす。"""
        # 推論サーバーが返したトークン数(返さないサーバーや失敗時は None)
        usage = getattr(self._llm, "last_usage", None) or {}
        # 観測ログは「無くても会話は続く」もの。書けなくても(DB のロック等)会話は止めない
        with contextlib.suppress(Exception):
            self._store.add_turn_log(
                session_id=session_id,
                message_id=message_id,
                character_id=character_id,
                model=model,
                persona_hash=persona_hash(system),
                prompt_version=PROMPT_VERSION,
                recalled_ids=[],  # 思い出した記憶の ID。長期記憶の検索(PR3)で埋める
                started_at=started_at,
                first_token_ms=first_token_ms,
                total_ms=total_ms,
                # こちらの見積もり。usage と比べれば、見積もりがどれだけ多めかも分かる
                prompt_tokens_est=sum(estimate_message_tokens(m["content"]) for m in messages),
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                error=error,
            )
