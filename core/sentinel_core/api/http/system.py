from __future__ import annotations

from fastapi import APIRouter, Request

from sentinel_core import __version__

router = APIRouter()


@router.get("/system/health")
async def health(request: Request) -> dict:
    llm_ok = await request.app.state.llm.is_reachable()
    return {
        "status": "ok",
        "version": __version__,
        "llm_reachable": llm_ok,
        "active_character": request.app.state.characters.active_id,
    }
