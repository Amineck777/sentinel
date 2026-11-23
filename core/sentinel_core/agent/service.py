"""会話ターンの実行(仕様 §3.3 の実行モデルのPhase 1形)。

POST /v1/chat から呼ばれ、即座に (session_id, message_id) を返し、
生成本体はバックグラウンドタスクが hub へ token/message_done イベントを流す。
この生成部は Pydantic AI のエージェント実行へ差し替える予定(ADR-0102)。
差し替え点をこのクラスに閉じ込めてある。
"""

from __future__ import annotations

import asyncio

from sentinel_core.agent.prompts import system_prompt
from sentinel_core.character.registry import CharacterRegistry
from sentinel_core.events import EventHub
from sentinel_core.llm.client import LLMClient, LLMUnavailableError
from sentinel_core.memory.store import Store


class ChatService:
    def __init__(
        self,
        store: Store,
        llm: LLMClient,
        characters: CharacterRegistry,
        hub: EventHub,
        default_model: str,
    ) -> None:
        self._store = store
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
        sid = self._store.ensure_session(session_id, self._characters.active_id)
        mid = self._store.add_message(sid, "user", content)

        task = asyncio.get_running_loop().create_task(self._generate(sid))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return sid, mid

    async def _generate(self, session_id: str) -> None:
        lock = self._session_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            await self._generate_turn(session_id)

    def active_model(self) -> str:
        """今のキャラで使うモデル名(Packの指定 > 設定の llm.chat_model)。"""
        pack = self._characters.active_pack()
        return (pack.model if pack else None) or self._default_model

    async def _generate_turn(self, session_id: str) -> None:
        pack = self._characters.active_pack()
        messages: list[dict[str, str]] = []
        # 人格をモデル側(Modelfile の SYSTEM)に持つPackでは system を送らない。
        # 送ると Ollama はそちらを優先し、Modelfile の人格が消えるため
        if not (pack and pack.use_model_system):
            messages.append(
                {"role": "system", "content": system_prompt(self._characters.active_fragment())}
            )
        messages += self._store.history(session_id)
        model = self.active_model()

        parts: list[str] = []
        try:
            async for delta in self._llm.stream_chat(messages, model=pack.model if pack else None):
                parts.append(delta)
                await self._hub.publish({"type": "token", "session_id": session_id, "delta": delta})
        except LLMUnavailableError as e:
            # オフライン応答などの案内文は通知として見せ、履歴には残さない
            await self._hub.publish({"type": "notice", "level": "warn", "text": str(e)})
        except Exception as e:  # 予期しない失敗もUIへ通知して終端する(無言で固まらせない)
            await self._hub.publish(
                {"type": "notice", "level": "error", "text": f"生成エラー: {e}"}
            )

        # 保存するのはモデルが実際に生成した文だけ(途中で切れた場合はそこまで)。
        # 何も生成されなかったターンは assistant 発言を作らない
        full = "".join(parts)
        if not full:
            return
        mid = self._store.add_message(session_id, "assistant", full, model=model)
        await self._hub.publish(
            {"type": "message_done", "session_id": session_id, "message_id": mid}
        )
