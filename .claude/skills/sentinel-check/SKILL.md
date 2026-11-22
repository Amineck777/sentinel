---
name: sentinel-check
description: SENTINEL のコミット前チェック(Python テスト・ruff・mypy、フロントの ESLint・Prettier・ビルド、Rust の fmt・clippy)を一括で実行し、失敗を直す。「チェックして」「コミット前に確認」「CI と同じ検査」と言われたとき、またはコードを変えてコミットする前に使う。
---

# SENTINEL のコミット前チェック

CI(`.github/workflows/ci.yml`)と同じ検査を手元で回す。CI で初めて落ちるのを防ぐのが目的。

## 手順

1. 変更したファイルを `git status --short` で確認し、どの層を触ったか判断する
   - `core/` → Python
   - `app/src/` や `app/*.json` → フロント
   - `app/src-tauri/` → Rust(フロントの `npm run build` も必要。release の clippy が `dist` を埋め込むため)
   - `scripts/build_sidecar.py`・`core/` の import 変更 → sidecar スモークも
2. 触った層だけ、下の表のコマンドを実行する。迷ったら全部
3. 失敗したら原因を直して、**失敗したコマンドだけ**を再実行する
4. 最後に結果を表で報告する(コマンド / 結果 / 直したこと)

| 層 | 作業場所 | コマンド |
|---|---|---|
| Python | `core/`(venv 有効化) | `python -m pytest tests -q` / `python -m ruff check sentinel_core tests` / `python -m ruff format --check sentinel_core tests` / `python -m mypy` |
| フロント | `app/` | `npm run lint` / `npm run format:check` / `npm run build` |
| Rust | `app/src-tauri/` | `cargo fmt --check` / `cargo clippy -- -D warnings` / `cargo clippy --release -- -D warnings` |
| sidecar | リポジトリ直下 | `python scripts/build_sidecar.py` → `python scripts/smoke_sidecar.py` |

自動整形してよいときは `make fmt`(または `ruff format` / `npm run format` / `cargo fmt`)。

## 注意

- Windows の PowerShell では `make` が無いことが多い。表のコマンドを直接使う
- PowerShell の npm は `--` 以降の引数を落とすので、`npm run tauri build -- --config ...` ではなく `npm run tauri:bundle` を使う
- Python は 3.11 以上(CI は 3.11 と 3.12)。`py -3.13 -m venv .venv` のように版を指定して venv を作る
- テストを消したり skip したりして通さない。落ちた理由を直す
