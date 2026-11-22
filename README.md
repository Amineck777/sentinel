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
  src-tauri/              トレイ/ホットキー/sidecar管理
character_pack_template/  Packの雛形(characters/へコピーして使う)
scripts/                  dev起動・sidecarビルド
docs/                     実装方針・仕様書(spec/)・(今後)ADR
```
