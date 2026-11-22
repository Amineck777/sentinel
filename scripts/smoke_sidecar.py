"""配布用 sidecar(PyInstaller 製の sentinel-core)を実際に起動して確かめる(実装方針 §5)。

確かめること:
  1. managed モードで起動し、SENTINEL_HANDSHAKE 行を出す
  2. その port / token で /v1/system/health が 200 を返す(uvicorn 等の import 漏れ=B9 の検出)
  3. 親が stdin を閉じると自分で終了する(アプリ終了時にコアが残らない)

使い方: python scripts/build_sidecar.py の後に python scripts/smoke_sidecar.py
標準ライブラリだけで動く(CI で仮想環境なしに実行するため)。
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = ROOT / "app" / "src-tauri" / "binaries"
HANDSHAKE_PREFIX = "SENTINEL_HANDSHAKE "
START_TIMEOUT_SEC = 60  # --onefile は初回の展開に時間がかかる
EXIT_TIMEOUT_SEC = 15


def find_binary() -> Path:
    found = sorted(BIN_DIR.glob("sentinel-core-*"))
    if not found:
        sys.exit(
            f"sidecar が見つかりません: {BIN_DIR}(先に scripts/build_sidecar.py を実行)"
        )
    return found[0]


def main() -> None:
    binary = find_binary()
    print(f"[smoke] {binary.name} を起動")
    with tempfile.TemporaryDirectory() as data_dir:
        env = {**os.environ, "SENTINEL_DATA_DIR": data_dir}  # 実データを汚さない
        proc = subprocess.Popen(
            [str(binary)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        lines: queue.Queue[str] = queue.Queue()
        assert proc.stdout is not None
        threading.Thread(
            target=lambda: [lines.put(ln) for ln in proc.stdout], daemon=True
        ).start()
        log: list[str] = []
        try:
            handshake = _wait_handshake(proc, lines, log)
            print(
                f"[smoke] handshake: port={handshake['port']} version={handshake['version']}"
            )

            req = urllib.request.Request(
                f"http://127.0.0.1:{handshake['port']}/v1/system/health",
                headers={"X-Sentinel-Token": handshake["token"]},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                body = json.loads(r.read())
            assert r.status == 200 and body["status"] == "ok", body
            print(f"[smoke] /health: {body}")

            assert proc.stdin is not None
            proc.stdin.close()  # 親が死んだときと同じ状態
            code = proc.wait(timeout=EXIT_TIMEOUT_SEC)
            print(f"[smoke] stdin を閉じて終了を確認(exit={code})")
        except BaseException:
            proc.kill()
            print("[smoke] 失敗。sidecar の出力:\n" + "".join(log) + _drain(lines))
            raise
    print("[smoke] OK")


def _wait_handshake(
    proc: subprocess.Popen[str], lines: queue.Queue[str], log: list[str]
) -> dict[str, str]:
    for _ in range(START_TIMEOUT_SEC * 10):
        try:
            line = lines.get(timeout=0.1)
        except queue.Empty:
            if proc.poll() is not None:
                raise RuntimeError(
                    f"handshake 前に終了しました(exit={proc.returncode})"
                ) from None
            continue
        log.append(line)
        if line.startswith(HANDSHAKE_PREFIX):
            return dict(json.loads(line[len(HANDSHAKE_PREFIX) :]))
    raise TimeoutError(f"{START_TIMEOUT_SEC} 秒以内に handshake が来ませんでした")


def _drain(lines: queue.Queue[str]) -> str:
    out = []
    while not lines.empty():
        out.append(lines.get_nowait())
    return "".join(out)


if __name__ == "__main__":
    main()
