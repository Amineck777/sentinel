"""S1開発起動: コアをdevモード(固定 8765 / dev-token)で立ち上げる。

UIは別ターミナルで:
  ブラウザ開発: cd app && npm run dev   → http://localhost:5173
  Tauri確認:   cd app && npm run tauri dev(devビルドはsidecarを起動せず、ここに接続)
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    subprocess.run(
        [sys.executable, "-m", "sentinel_core", "--dev"],
        cwd=ROOT / "core",
        check=False,
    )
