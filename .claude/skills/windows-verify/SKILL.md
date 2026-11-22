---
name: windows-verify
description: Tauri アプリの変更を Windows 実機で確かめる手順(dev 起動・ホットキー・トレイ・配布ビルド・sidecar 自動起動)を案内し、結果を記録する。「Windows で確認したい」「実機確認の手順」「インストーラが作れるか試したい」と言われたとき、またはシェル(app/src-tauri)や sidecar を変えた PR のマージ前に使う。
---

# Windows 実機での確認

CI はコンパイルと sidecar の起動までは確かめるが、**窓が出るか・キーやトレイが効くか**は人が見るしかない。

## 0. 下準備(初回だけ)

- Python 3.11 以上(`py --list` で確認)、Node 20 以上、Rust(`cargo --version`)、Visual Studio Build Tools の「C++ によるデスクトップ開発」
- PowerShell でスクリプトを許可:`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
- 依存の導入(リポジトリ直下):
  ```powershell
  cd core; py -3.13 -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -e ".[dev]"; cd ..
  cd app; npm install; cd ..
  ```
  `;` でつなぐと途中で失敗しても先へ進むので、うまくいかないときは1行ずつ実行する

## 1. 開発ウィンドウ

- ターミナル1:`python scripts/dev.py`(`127.0.0.1:8765` で待ち受け)
- ターミナル2:`cd app; npm run tauri dev`(初回は Rust のビルドに数分)

確認項目:
1. 画面上部が「CORE LINK」になり、送信すると返事(Ollama が無ければ警告の通知)が来る
2. ターミナル2に `[hotkey] Ctrl+Shift+Space を登録しました`
3. Ctrl+Shift+Space を押すたびに窓が消える・出る(開いてすぐ閉じるのは不具合)
4. タスクトレイのアイコンから表示・終了できる
5. コアのログで `token=***` と伏せられている

## 2. 配布ビルド

両方のターミナルを止めてから:
```powershell
pip install pyinstaller
python scripts/build_sidecar.py
python scripts/smoke_sidecar.py
cd app; npm run tauri:bundle
```
`app\src-tauri\target\release\bundle\msi`(または `nsis`)にインストーラができる。入れて起動し、
**コアを手で起動していない状態で** 「CORE LINK」になれば、sidecar の自動起動も OK。

## よくあるエラー

| エラー | 対処 |
|---|---|
| `No suitable Python runtime found` | 入っている版を `py --list` で確認し、`py -3.13` などに変える |
| `Activate.ps1` を読み込めない | 実行ポリシー(上の Set-ExecutionPolicy) |
| `link.exe not found` | Visual Studio Build Tools の C++ を入れる |
| `version mismatched Tauri packages` | `app/package.json` の `@tauri-apps/*` と `Cargo.lock` の `tauri` の minor を揃える |

## 記録

結果は PR のコメントか、`docs/implementation-policy.md` の該当節に「確認済(日付, Windows 実機)」として残す。
スクリーンショットをもらったら、ログの内容(OPTIONS が 200、`token=***`、hotkey 登録)まで読んで判定する。
