"""VOICEVOX CORE(同梱の音声合成)を、この PC に入れる。VOICEVOX のアプリを起動しなくても声が出るようになる。

使い方(リポジトリ直下から。コアの仮想環境の python で動かす):
  core\\.venv\\Scripts\\python.exe scripts\\setup_voicevox_core.py

やること:
  1. Python パッケージ voicevox_core を、コアの仮想環境に pip で入れる
     (PyPI に無いので、VOICEVOX 公式の GitHub Releases の wheel を直接指定する)
  2. 公式のダウンローダーを取ってきて動かし、ONNX Runtime・辞書・音声モデル(.vvm)を
     {APP_DATA}/sentinel/voicevox_core/ に入れる
     → 途中で音声モデルの利用規約が表示される。読んで、同意するなら y を入力する
       (規約への同意は利用者本人が行うものなので、このスクリプトは代わりに答えない)
  3. 試しに1文合成して、test.wav を書き出す

オプション:
  --all-models  音声モデルを全部入れる(既定はエヴァの声 暁記ミタマが入った 24.vvm だけ。
                全部だと 1GB 以上ある)
  --models P    入れる .vvm のファイル名パターン(例: "0.vvm"。ずんだもん等が入っている)
  --dir D       置き場所を変える(変えたら config の voice.core.dir にも同じ場所を書く)
  --skip-pip / --skip-download  その段階を飛ばす(やり直すとき用)

ここで取ってくるファイルは、どれも git に入れない(.gitignore と CI で防ぐ。ADR 0115)。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import platform
import subprocess
import sys
import urllib.request
from pathlib import Path

from sentinel_core.settings import Settings
from sentinel_core.tts.factory import CORE_DIR_NAME

# 使う VOICEVOX CORE の版。上げるときはここと、下の SHA-256 をまとめて変える
VERSION = "0.17.0"
RELEASE = f"https://github.com/VOICEVOX/voicevox_core/releases/download/{VERSION}"

# OS・CPU ごとの wheel とダウンローダーのファイル名(Releases の Assets にある名前)
PLATFORMS: dict[tuple[str, str], tuple[str, str]] = {
    ("Windows", "AMD64"): (
        f"voicevox_core-{VERSION}-cp310-abi3-win_amd64.whl",
        "download-windows-x64.exe",
    ),
    ("Linux", "x86_64"): (
        f"voicevox_core-{VERSION}-cp310-abi3-manylinux_2_34_x86_64.whl",
        "download-linux-x64",
    ),
    ("Linux", "aarch64"): (
        f"voicevox_core-{VERSION}-cp310-abi3-manylinux_2_34_aarch64.whl",
        "download-linux-arm64",
    ),
    ("Darwin", "arm64"): (
        f"voicevox_core-{VERSION}-cp310-abi3-macosx_11_0_arm64.whl",
        "download-osx-arm64",
    ),
    ("Darwin", "x86_64"): (
        f"voicevox_core-{VERSION}-cp310-abi3-macosx_10_12_x86_64.whl",
        "download-osx-x64",
    ),
}

# 取ってきたファイルが壊れていない・すり替わっていないかの確認用(Releases ページに載っている値)。
# 値が無いものは確認を飛ばす(今は Windows だけ控えてある)
SHA256: dict[str, str] = {
    f"voicevox_core-{VERSION}-cp310-abi3-win_amd64.whl": "66f4d8d650cb47610f5c29ad4d54462c4cafdffd1612fe25f84fd0c35190154b",
    "download-windows-x64.exe": "4f0ae2758f3149f084cc91556065009553bf81010f58498c89acb6e2289546b6",
}

# エヴァの声(暁記ミタマ ノーマル)。どの .vvm に入っているかは voicevox_vvm の README の対応表で確認
EVA_STYLE = 122
EVA_VVM = "24.vvm"


def fetch(url: str, dest: Path) -> Path:
    """url を dest に保存し、控えてある SHA-256 があれば照合する。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  取得: {url}")
    with urllib.request.urlopen(url) as r, dest.open("wb") as f:
        f.write(r.read())
    expected = SHA256.get(dest.name)
    if expected:
        actual = hashlib.sha256(dest.read_bytes()).hexdigest()
        if actual != expected:
            dest.unlink()
            sys.exit(f"ファイルの SHA-256 が一致しません({dest.name})。取り直してください。")
        print("  SHA-256 OK")
    return dest


def install_wheel(wheel: str, work: Path) -> None:
    print(f"[1/3] Python パッケージ voicevox_core {VERSION} を入れます({sys.executable})")
    path = fetch(f"{RELEASE}/{wheel}", work / wheel)
    subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", str(path)], check=True)


def run_downloader(exe_name: str, out: Path, pattern: str) -> None:
    print(f"[2/3] ONNX Runtime・辞書・音声モデル({pattern})を {out} に入れます")
    exe = fetch(f"{RELEASE}/{exe_name}", out / "_downloader" / exe_name)
    exe.chmod(0o755)  # Linux / macOS では実行権限が要る
    print()
    print("  ※ このあと音声モデルの利用規約が表示されます。")
    print("    上下キーで読み、q で閉じてから、同意するなら y を入力して Enter を押してください。")
    print()
    # c-api(C 言語向けライブラリ)は Python から使うので要らない。GPU 版も使わない(CPU 固定)
    cmd = [
        str(exe),
        "--exclude",
        "c-api",
        "--devices",
        "cpu",
        "--models-pattern",
        pattern,
        "-o",
        str(out),
    ]
    # 入力(規約への同意)は利用者の端末にそのまま渡す
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        sys.exit("ダウンローダーが失敗しました(規約に同意しなかった場合も、ここで止まります)。")


async def try_synthesize(out: Path) -> None:
    """コアと同じ部品(VoicevoxCoreEngine)で1文合成して、test.wav に書き出す。"""
    import importlib

    # 同じプロセスの中で今 pip で入れたパッケージを import できるよう、探索の記憶を消す
    importlib.invalidate_caches()
    from sentinel_core.tts.base import VoiceParams
    from sentinel_core.tts.voicevox_core_engine import VoicevoxCoreEngine

    engine = VoicevoxCoreEngine(base_dir=out)
    try:
        speakers = await engine.speakers()
        ids = {st.id for sp in speakers for st in sp.styles}
        style = EVA_STYLE if EVA_STYLE in ids else min(ids)
        name = next(
            f"{sp.name} / {st.name}" for sp in speakers for st in sp.styles if st.id == style
        )
        print(f"  入っている声: {', '.join(sp.name for sp in speakers)}")
        print(
            f"  試しに「{name}」(スタイルID {style})で合成します(初回はモデルの読み込みで数秒かかります)"
        )
        speech = await engine.synthesize(
            "おかえりなさいませ、マスター。", VoiceParams(speaker=style)
        )
        wav = out / "test.wav"
        wav.write_bytes(speech.wav)
        print(f"  OK: {speech.duration:.2f} 秒の音声を {wav} に書き出しました")
    finally:
        await engine.aclose()


def main() -> int:
    # Windows の端末でも日本語の print で落ちないよう UTF-8 にそろえる
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    ap = argparse.ArgumentParser(description="VOICEVOX CORE を入れる")
    ap.add_argument("--dir", help="置き場所(既定は {APP_DATA}/sentinel/voicevox_core)")
    ap.add_argument("--models", default=EVA_VVM, help=f"入れる .vvm のパターン(既定 {EVA_VVM})")
    ap.add_argument("--all-models", action="store_true", help="音声モデルを全部入れる")
    ap.add_argument("--skip-pip", action="store_true")
    ap.add_argument("--skip-download", action="store_true")
    args = ap.parse_args()

    key = (platform.system(), platform.machine())
    if key not in PLATFORMS:
        print(f"この OS / CPU({key})向けの VOICEVOX CORE は、このスクリプトでは扱っていません。")
        return 1
    wheel, exe_name = PLATFORMS[key]
    out = Path(args.dir).expanduser() if args.dir else Settings.load().data_dir / CORE_DIR_NAME
    out.mkdir(parents=True, exist_ok=True)
    # 歌声用の .vvm(s0.vvm など)は使わないので、「全部」でも話す声(数字の名前)だけにする
    pattern = "[0-9]*.vvm" if args.all_models else args.models

    if not args.skip_pip:
        install_wheel(wheel, out / "_downloader")
    if not args.skip_download:
        run_downloader(exe_name, out, pattern)
    print("[3/3] 試しに合成します")
    from sentinel_core.tts.base import TTSUnavailableError

    try:
        asyncio.run(try_synthesize(out))
    except TTSUnavailableError as e:
        # 足りないファイルなどは、コアが画面に出すのと同じ文面で知らせる
        print(f"  失敗: {e}")
        return 1
    print()
    print("できました。コアを再起動すると、声が VOICEVOX CORE(アプリ不要)に切り替わります。")
    print("(config の voice.engine が auto のとき。設定画面の「声」→ エンジン で確認できます)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
