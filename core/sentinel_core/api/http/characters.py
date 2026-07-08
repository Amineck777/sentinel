from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/characters")
async def list_characters(request: Request) -> dict:
    reg = request.app.state.characters
    reg.rescan()  # Packフォルダの追加・削除を反映(§16.1「置けば増える」)
    return {
        "active": reg.active_id,
        "characters": [
            {"id": p.id, "display_name": p.display_name, "valid": p.valid, "error": p.error}
            for p in reg.list()
        ],
    }


@router.post("/characters/{char_id}/activate")
async def activate(char_id: str, request: Request) -> dict:
    reg = request.app.state.characters
    pack = reg.activate(char_id)
    ok = bool(pack) or char_id in ("none", "")
    await request.app.state.hub.publish(
        {"type": "notice", "level": "info" if ok else "warn",
         "text": f"キャラクター: {pack.display_name if pack else '汎用モード'}"
                 + ("" if ok else "(Packが無効なため汎用モードで継続)")}
    )
    return {"active": reg.active_id, "ok": ok}
