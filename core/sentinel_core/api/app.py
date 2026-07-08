"""FastAPIアプリファクトリ。依存(settings/token/store/characters/llm/hub/chat)をここで結線する。

いわゆるポート&アダプタの結線点(仕様 §5.2)。テストでは `llm=` にモックを
渡すだけで実LLMなしに全経路を検証できる(仕様 §12.2)。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sentinel_core import __version__
from sentinel_core.agent.service import ChatService
from sentinel_core.api.http import characters, chat, system
from sentinel_core.api.ws import stream
from sentinel_core.auth import make_http_guard
from sentinel_core.character.registry import CharacterRegistry
from sentinel_core.events import EventHub
from sentinel_core.llm.client import LLMClient
from sentinel_core.llm.openai_compat import OpenAICompatClient
from sentinel_core.memory.store import Store
from sentinel_core.settings import Settings


def create_app(
    settings: Settings,
    token: str,
    dev: bool = False,
    llm: LLMClient | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        aclose = getattr(app.state.llm, "aclose", None)  # モックLLMはacloseを持たなくてよい
        if aclose:
            await aclose()

    app = FastAPI(title="sentinel-core", version=__version__, lifespan=lifespan)

    if dev:  # ブラウザ開発(Vite)時のみCORS許可。managedでは不要=無効(実装方針 §6)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # --- 依存の組み立て ---
    app.state.settings = settings
    app.state.token = token
    app.state.hub = EventHub()
    app.state.store = Store(settings.db_path)
    app.state.characters = CharacterRegistry(settings.characters_dir)
    app.state.llm = llm or OpenAICompatClient(
        endpoint=settings.llm_endpoint,
        model=settings.chat_model,
        timeout_sec=int(settings.data["llm"].get("request_timeout_sec", 120)),
    )
    app.state.chat = ChatService(
        store=app.state.store,
        llm=app.state.llm,
        characters=app.state.characters,
        hub=app.state.hub,
    )

    guard = make_http_guard(token)
    app.include_router(system.router, prefix="/v1", dependencies=[Depends(guard)])
    app.include_router(chat.router, prefix="/v1", dependencies=[Depends(guard)])
    app.include_router(characters.router, prefix="/v1", dependencies=[Depends(guard)])
    app.include_router(stream.router, prefix="/v1")  # WSはハンドラ内でトークン検証
    return app
