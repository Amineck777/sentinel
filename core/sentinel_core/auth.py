"""トークン認証(実装方針 §2/§6)。HTTPはヘッダ、WSはクエリで検証する。"""
from __future__ import annotations

import hmac

from fastapi import HTTPException, Request, WebSocket

TOKEN_HEADER = "X-Sentinel-Token"


def _token_match(provided: str | None, expected: str) -> bool:
    # タイミング攻撃対策の定数時間比較(127.0.0.1限定だが多層防御として)
    return provided is not None and hmac.compare_digest(provided.encode(), expected.encode())


def make_http_guard(token: str):
    async def guard(request: Request) -> None:
        if not _token_match(request.headers.get(TOKEN_HEADER), token):
            raise HTTPException(status_code=401, detail="invalid token")

    return guard


def ws_token_ok(ws: WebSocket, token: str) -> bool:
    return _token_match(ws.query_params.get("token"), token)
