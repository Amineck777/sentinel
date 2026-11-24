"""コアをPyInstallerで単一実行ファイル化し、Tauri externalBin規約の名前で配置する。

Tauri externalBin は `{name}-{target_triple}(.exe)` 命名を要求する(実装方針 §5)。
target triple は rustc から取得(Tauriと同じ判定基準に揃えるため)。

使い方(各OSのローカル/CIで実行):
    pip install pyinstaller
    python scripts/build_sidecar.py
"""
from __future__ import annotations

import importlib.util
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "app" / "src-tauri" / "binaries"


def target_triple() -> str:
    out = subprocess.run(["rustc", "-vV"], capture_output=True, text=True, check=True).stdout
    m = re.search(r"host: (\S+)", out)
    if not m:
        sys.exit("rustc -vV から target triple を取得できませんでした")
    return m.group(1)


def main() -> None:
    # Windows の CI ではパイプ出力が cp1252 になり、日本語の print で落ちるため UTF-8 に揃える
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    triple = target_triple()
    ext = ".exe" if platform.system() == "Windows" else ""
    name = f"sentinel-core-{triple}{ext}"

    # VOICEVOX CORE(任意・ADR 0115)が入っていれば同梱する。コアは import を実行時に
    # importlib で行う(無くても起動できるように)ため、PyInstaller が自動では拾えない。
    # 中のネイティブ拡張(_rust)ごと集めるよう --collect-all を付ける。
    # 音声モデル・ONNX Runtime・辞書は実行ファイルに入れず、{APP_DATA} 側のものを読む
    extra: list[str] = []
    if importlib.util.find_spec("voicevox_core") is not None:
        extra = ["--collect-all", "voicevox_core"]
        print("voicevox_core を同梱します")

    subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            "--onefile", "--name", "sentinel-core",
            "--clean", "--noconfirm",
            *extra,
            str(ROOT / "core" / "sentinel_core" / "__main__.py"),
        ],
        check=True,
        cwd=ROOT / "core",
    )

    built = ROOT / "core" / "dist" / f"sentinel-core{ext}"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dest = OUT_DIR / name
    shutil.copy2(built, dest)
    print(f"sidecar -> {dest}")
    print("次: python scripts/smoke_sidecar.py で起動確認 → cd app && npm run tauri:bundle")


if __name__ == "__main__":
    main()
