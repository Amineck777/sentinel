"""WSストリーム(仕様 §7)。トークンはクエリで検証(実装方針 §2)。"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from sentinel_core.auth import ws_token_ok
from sentinel_core.events import CLOSE_SENTINEL

router = APIRouter()


@router.websocket("/stream")
async def stream(ws: WebSocket) -> None:
    if not ws_token_ok(ws, ws.app.state.token):
        await ws.close(code=4401)
        return
    await ws.accept()
    hub = ws.app.state.hub
    q = hub.subscribe()
    try:
        while True:
            event = await q.get()
            if event is CLOSE_SENTINEL:  # hubに切り離された(配信が追いつかない)
                await ws.close(code=1013)  # try again later → クライアントが再接続する
                return
            await ws.send_json(event)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        hub.unsubscribe(q)
