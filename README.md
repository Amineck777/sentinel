# SENTINEL

ローカルLLMパーソナルアシスタント(仕様書 v3.0 準拠のリファレンス実装・Phase 1相当)。

## 何が動くか

- ストリーミングチャット(FastAPI + WS + Ollama/OpenAI互換)
- **Ollama未起動でも動く**(オフライン応答へ自動フォールバック → UI開発を止めない)
- 会話のSQLite永続化 / Character Pack のロード・切替(口調Lv1)
- Tauriデスクトップ:トレイ常駐・ホットキー(既定 Ctrl+Shift+Space、`SENTINEL_HOTKEY` で変更可)で表示切替・sidecar自動起動(リリースビルド)

## クイックスタート(S1: 開発モード)

前提: Python 3.11+ / Node 20+(npm)。(Tauri確認には Rust toolchain も)

```bash
make setup        # 依存インストール
make core-dev     # ターミナル1: コア起動(8765/dev-token)
make ui-dev       # ターミナル2: ブラウザで http://localhost:5173
# Ollamaを使う場合: ollama serve + ollama pull qwen2.5:7b-instruct
```

Character Pack は `{APP_DATA}/sentinel/characters/` にPackフォルダを置くと
UI右上のセレクタに現れる(リポジトリ直下の `character_pack_template/` をコピーして使える)。

## デスクトップアプリとして確認・配布(S2)

```bash
make tauri-dev    # 開発ウィンドウ(devモードのコアに接続)
make bundle       # sidecar化 + インストーラ生成(要: pip install pyinstaller)
```

詳細は `docs/implementation-policy.md`(実装方針)を参照。

## Windows(PowerShell)での起動

`make` が無い Windows では、次をリポジトリ直下から実行する。

**初回だけ:**
```powershell
cd core; py -3.13 -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -e ".[dev]"; cd ..
cd app; npm install; cd ..
```

**チャット(ブラウザ):** ターミナルを2つ使う。
```powershell
# ターミナル1: コア(127.0.0.1:8765)
core\.venv\Scripts\python.exe scripts\dev.py
```
```powershell
# ターミナル2: 画面 → http://localhost:5173
cd app; npm run dev
```

**デスクトップアプリ:** ターミナル1でコアを起動したまま、ターミナル2を次に変える。
```powershell
cd app; npm run tauri dev
```
`npm run dev` が別に動いていると `Port 5173 is already in use` で止まるので、先に止める。

## アバター(試作)

three-vrm で VRM モデルを表示し、表情・まばたき・口パクを試すページ。詳しくは `docs/learning/04-avatar-prototype.md`。

**モデルの指定(初回だけ):** メモ帳で `app\.env.local` を作り、1行書く(区切りは `/`)。
```
SENTINEL_AVATAR_VRM=C:/path/to/model.vrm
```
このファイルと `*.vrm` は `.gitignore` 済み。**モデルはリポジトリに入れない**(配布規約で再配布禁止のものがあるため。CI でも検査する)。
指定しなくても、画面に `.vrm` をドロップすれば読める。

**ブラウザで:** `cd app; npm run dev` → http://localhost:5173/avatar.html
(右のパネルで表情・まばたき・口パク。ドラッグで回転、ホイールで拡大)

**デスクトップ窓で:** `cd app; npm run tauri dev` → タスクトレイの SENTINEL アイコン →「アバターを表示/隠す」
(透明・枠なし・最前面。キャラを掴むと窓ごと移動、ダブルクリックで操作パネル)

## 学習ノートと Claude Code スキル

- `docs/learning/` … なぜこう作ったか・何でつまずいたかを残す学習ノート(読む順番は README)
- `.claude/skills/` … Claude Code で使えるスキル
  - `/sentinel-check` コミット前に CI と同じ検査を回す
  - `/windows-verify` Windows 実機での確認手順
  - `/learn-note` 変更を学習ノートにまとめる
  - `/adr` 設計判断を ADR として記録する

## 構成

```
core/                     Pythonコア … テスト済み
  sentinel_core/
    __main__.py           起動・ハンドシェイク・stdin監視
    api/http/ api/ws/     ルーター(受付のみ)/ WSストリーム
    agent/                会話生成(Phase 3でLangGraphへ差し替える点)
    character/            Character Pack(pack=ロード/persona=口調合成/registry=切替)
    llm/ memory/          LLM抽象+OpenAI互換 / SQLite永続化
    events.py             WSイベントハブ
app/                      Tauri 2 + React UI
  src/features/chat/      useCore・useChat + StatusRail/MessageLog/Composer
  src/features/avatar/    アバター試作(three-vrm の描画・表情・口パク)
  src-tauri/              トレイ/ホットキー/sidecar管理
character_pack_template/  Packの雛形(characters/へコピーして使う)
scripts/                  dev起動・sidecarビルド
docs/                     実装方針・仕様書(spec/)・(今後)ADR
```
