"""SENTINEL core entry point.

起動モード(実装方針 §1):
  dev     : make core-dev で人間が起動。固定ポート・固定トークン・stdin監視なし
  managed : Tauri sidecar として起動。動的ポート・ランダムトークン・stdin EOFで自死

ハンドシェイク(実装方針 §2):
  起動完了時に stdout へ 1 行 `SENTINEL_HANDSHAKE {...}` を出力する。
  出力は uvicorn が実際に listen を開始した後(実装方針 §7.1-2)。
  handshake を受けた側はリトライなしで即接続してよい。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import socket
import sys
import threading

import uvicorn

from sentinel_core import __version__
from sentinel_core.api.app import create_app
from sentinel_core.settings import Settings

HANDSHAKE_PREFIX = "SENTINEL_HANDSHAKE "


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _watch_stdin_for_parent_death(server: uvicorn.Server) -> None:
    """親(Tauri)が死ぬと stdin が EOF になる。それを検知して graceful shutdown。"""

    def _run() -> None:
        try:
            while sys.stdin.buffer.read(1024):
                pass  # 親からの入力は現状使わない(将来 "shutdown" コマンド等に拡張可)
        except Exception:
            pass
        server.should_exit = True  # EOF → uvicorn へ終了要求

    threading.Thread(target=_run, name="stdin-watch", daemon=True).start()


async def _serve_with_handshake(server: uvicorn.Server, handshake: dict) -> None:
    """listen開始を確認してからhandshakeを出力する。

    早すぎるhandshakeはUI側の初回 /health を接続失敗させる(§7.1-2)。
    起動に失敗した場合はhandshakeを出さずに終了する(Rust側はタイムアウトで検知)。
    """
    serve_task = asyncio.get_running_loop().create_task(server.serve())
    while not server.started and not serve_task.done():
        await asyncio.sleep(0.02)
    if server.started:
        print(HANDSHAKE_PREFIX + json.dumps(handshake), flush=True)
    await serve_task


def main() -> None:
    parser = argparse.ArgumentParser(prog="sentinel-core")
    parser.add_argument("--dev", action="store_true", help="開発モード(固定port/token・stdin監視なし)")
    parser.add_argument("--port", type=int, default=0, help="0なら動的割当")
    parser.add_argument("--token", default=None)
    args = parser.parse_args()

    if args.dev:
        port = args.port or 8765
        token = args.token or "dev-token"
    else:
        port = args.port or _find_free_port()
        token = args.token or secrets.token_urlsafe(32)

    settings = Settings.load()
    app = create_app(settings=settings, token=token, dev=args.dev)

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info")
    server = uvicorn.Server(config)

    if not args.dev:
        _watch_stdin_for_parent_death(server)

    # ハンドシェイク(Rust側 sidecar.rs がこの行を待っている)は listen 開始後に出す
    handshake = {"port": port, "token": token, "pid": os.getpid(), "version": __version__}
    asyncio.run(_serve_with_handshake(server, handshake))


if __name__ == "__main__":
    main()
