"""コアをPyInstallerで単一実行ファイル化し、Tauri externalBin規約の名前で配置する。

Tauri externalBin は `{name}-{target_triple}(.exe)` 命名を要求する(実装方針 §5)。
target triple は rustc から取得(Tauriと同じ判定基準に揃えるため)。

使い方(各OSのローカル/CIで実行):
    pip install pyinstaller
    python scripts/build_sidecar.py
"""
from __future__ import annotations

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
    triple = target_triple()
    ext = ".exe" if platform.system() == "Windows" else ""
    name = f"sentinel-core-{triple}{ext}"

    subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            "--onefile", "--name", "sentinel-core",
            "--clean", "--noconfirm",
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
    print("次: cd app && pnpm tauri build")


if __name__ == "__main__":
    main()
