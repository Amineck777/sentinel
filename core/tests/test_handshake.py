"""起動スモーク: handshake行が出た時点で /health が既に応答すること(方針 §7.1-2)。

実プロセスを spawn するため、sidecarスモークCI(方針 §5)のミニ版を兼ねる。
"""

from __future__ import annotations

import json
import os
import queue
import socket
import subprocess
import sys
import threading
from pathlib import Path

import httpx

HANDSHAKE_PREFIX = "SENTINEL_HANDSHAKE "
WAIT_SEC = 30


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_handshake_printed_after_listening(tmp_path: Path):
    env = {
        **os.environ,
        "PYTHONUNBUFFERED": "1",
        "SENTINEL_DATA_DIR": str(tmp_path),  # 実ユーザーデータを汚さない
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "sentinel_core", "--dev", "--port", str(_free_port())],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        env=env,
    )
    lines: queue.Queue[str] = queue.Queue()
    threading.Thread(target=lambda: [lines.put(ln) for ln in proc.stdout], daemon=True).start()

    try:
        handshake = None
        for _ in range(WAIT_SEC * 20):
            try:
                line = lines.get(timeout=0.05)
            except queue.Empty:
                assert proc.poll() is None, "core exited before handshake"
                continue
            if line.startswith(HANDSHAKE_PREFIX):
                handshake = json.loads(line[len(HANDSHAKE_PREFIX) :])
                break
        assert handshake, f"handshake not received within {WAIT_SEC}s"

        # handshakeの契約: 受信側はリトライなしで即接続できる(1発で通ること)
        r = httpx.get(
            f"http://127.0.0.1:{handshake['port']}/v1/system/health",
            headers={"X-Sentinel-Token": handshake["token"]},
            timeout=5,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
    finally:
        proc.kill()
        proc.wait(timeout=10)
