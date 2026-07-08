# SENTINEL デスクトップアプリ実装方針

仕様書 v3.0(§3 アーキテクチャ / §14 パッケージング)を実装に落とすための方針書。
本リポジトリの雛形コードはこの方針に従って書かれている。

- 仕様書本体: [`docs/spec/local-llm-assistant-仕様書-v3.md`](spec/local-llm-assistant-仕様書-v3.md)(旧v2は `spec/archive/`)
- Character Packの雛形: リポジトリ直下 `character_pack_template/`(`{APP_DATA}/sentinel/characters/{char_id}/` へコピーして使う)

---

## 1. 実装の大原則:S1とS2で「同じコア」を動かす

デスクトップアプリ化の最大の失敗パターンは「開発中はPythonスクリプト、配布時に
別物のパッケージ」になり、配布直前に動かなくなること。これを防ぐため、
**コアプロセスは起動モードだけが違い、コードは完全に同一**とする。

| モード | 起動者 | ポート | トークン | 終了契機 |
|---|---|---|---|---|
| **dev(S1)** | `make core-dev`(人間) | 固定 8765 | 固定 `dev-token` | Ctrl+C |
| **managed(S2〜)** | Tauri(sidecar) | 動的割当 | 起動毎ランダム | **stdin EOF(親死亡で自動終了)** |

差は `--dev` フラグひとつ。UIも同様に、Tauri内なら`get_core_info`コマンドで
接続先を取得し、ブラウザ開発時は環境変数の固定値へフォールバックする
(`app/src/api/client.ts`)。**「ブラウザで開発→Tauriで確認」が常に両立する。**

## 2. ハンドシェイクプロトコル(UI↔コアの結線)

コアは起動完了時に **stdoutへ1行だけ** 次を出力する:

```
SENTINEL_HANDSHAKE {"port": 52341, "token": "a1b2...", "pid": 1234, "version": "0.1.0"}
```

- Rust側(`sidecar.rs`)はstdout行を監視し、この接頭辞を見つけたらパースして
  アプリ状態に保存、フロントへ `core-ready` イベントを発火する
- 接頭辞方式にする理由:Pythonライブラリが起動時にstdoutへ何か出しても壊れない
- 以降の通信はすべて `http://127.0.0.1:{port}`(HTTP)と `/v1/stream`(WS)。
  認証は全リクエストで `X-Sentinel-Token` ヘッダ(WSはクエリ `?token=`)必須

## 3. プロセスライフサイクル(孤児プロセス対策)

仕様§14.2の「sidecarの孤児化」への実装解:

```
起動:  Tauri setup() → sidecar spawn → handshake受信 → core-ready
死活:  UIは /v1/system/health を接続失敗時にリトライ表示(ステータスレール)
終了:  Tauriプロセス終了 → 子プロセスのstdinパイプがEOF
       → コアのstdin監視スレッドが検知 → uvicornへgraceful shutdown
```

**「親が死ねば子はstdin EOFで自死する」**を基本線にすることで、OSごとの
プロセスグループ制御に依存しない。加えてRust側もExit時にkillを送る二重化。
dev モードではstdin監視を無効化する(ターミナルのstdinで誤終了しないため)。

## 4. リポジトリ内の実装状態マップ

コアのパッケージ構成は仕様 §5.1 に揃えている(`api/http/`+`api/ws/`分割、
生成ロジックは `agent/` に隔離=Phase 3 で LangGraph `graph.py` へ差し替える点)。

| 領域 | 状態 | 対応ファイル |
|---|---|---|
| コア起動・ハンドシェイク・認証 | ✅ 実装済 | `core/sentinel_core/__main__.py`, `auth.py` |
| チャットAPI(受付のみの薄いルーター) | ✅ 実装済 | `api/http/chat.py` |
| 会話ターン生成(EX-01・Phase 3差し替え点) | ✅ 実装済 | `agent/service.py`, `agent/prompts.py` |
| WSストリーミング+イベントハブ | ✅ 実装済 | `api/ws/stream.py`, `events.py` |
| OpenAI互換LLMクライアント(Ollama) | ✅ 実装済(**未接続時はオフライン応答へ自動フォールバック**=LLMなしでもUI開発可) | `llm/client.py`(抽象), `llm/openai_compat.py` |
| 会話永続化(ME-01/02の土台) | ✅ 実装済(SQLite: sessions/messages) | `memory/store.py` |
| Character Packロード(CH-01/02=口調Lv1) | ✅ 実装済(ロード=pack / 口調合成=persona / 走査・切替=registry) | `character/pack.py`, `character/persona.py`, `character/registry.py`, `api/http/characters.py` |
| Tauriシェル(sidecar・トレイ・ホットキー) | ✅ 実装済(要ローカルビルド確認) | `app/src-tauri/src/*.rs` |
| チャットUI+ステータスレール | ✅ 実装済(接続=useCore / 会話=useChat / 表示コンポーネント3分割) | `app/src/features/chat/` |
| Function Calling・承認ゲート(AC-06) | ⬜ Phase 2(hubに`approval_required`イベント型だけ予約済み) | — |
| RAG / LangGraph / MCP | ⬜ Phase 3 | — |
| 音声(STT/TTS) | ⬜ Phase 4 / Track X2 | — |
| PyInstaller sidecar化 | 🔶 スクリプト提供(実行は各OSで) | `scripts/build_sidecar.py` |

**テストでのLLM差し替え:** `create_app(..., llm=モック)` のDI引数で行う
(アプリ生成後の `app.state.llm` 差し替えは `ChatService` が参照を掴んでいるため効かない)。

> **注:** Rust/TypeScript部分は本環境ではコンパイル未検証(Rustツールチェーン・
> GUI環境が必要)。Python部分はテスト実行済み。初回 `tauri dev` で型・API名の
> 微修正が発生し得る前提でレビューすること。

## 5. 開発→配布のビルドパイプライン

```
[S1: 日常開発]
  make core-dev        # コアを固定ポートで起動(Ollama無しでも動く)
  make ui-dev          # Vite devサーバ(ブラウザで http://localhost:5173)
  make tauri-dev       # Tauriウィンドウで統合確認(devモードのコアに接続)

[S2: 配布ビルド]
  make sidecar         # PyInstallerでコアを単一実行ファイル化
                       #   → app/src-tauri/binaries/sentinel-core-{target_triple}
  make bundle          # tauri build(externalBinとしてコアを同梱)
                       #   → .msi / .dmg / .AppImage
```

- Tauriの`externalBin`は **`名前-{ターゲットトリプル}`** 命名を要求する
  (例: `sentinel-core-x86_64-pc-windows-msvc.exe`)。`build_sidecar.py`が
  `rustc -vV`からトリプルを取得して自動命名する
- PyInstallerは当面 `--onefile`(単一ファイル=externalBinに素直に載る)。
  起動が遅い場合は onedir + resources 方式へ移行(ADR起票の上)
- **sidecarスモークCI**(§14.2):ビルド成果物を起動→handshake→/health確認
  だけを行うテストを、機能追加より先にCIへ入れること

## 6. セキュリティ実装の要点(§13対応)

- コアは `127.0.0.1` バインド固定。0.0.0.0にする設定項目を**作らない**
- トークンはmanagedモードで起動毎に`secrets.token_urlsafe(32)`生成。
  ログにトークンを出さない(handshake行はRustが読むのみでログ保存しない)
- CORSはdevモードのみ `http://localhost:5173` を許可。managedでは無効
- Tauri capabilities は `core:default` のみ(フロントに shell 権限を渡さない。
  sidecar起動はRust側の責務)

## 7. 次の実装ステップ(このコードベースからの継続)

1. **Phase 2:** `tools/registry.py`+`files.py`(read系のみ)→ `plan_or_respond`を
   Function Calling対応に。承認ゲートは`hub`の`approval_required`イベント+
   `POST /v1/approvals/{id}` を先に固定(UIと同時に)
2. **Track X0:** Character管理UI(一覧・切替は実装済API `/v1/characters` を叩くだけ)
3. **CI:** GitHub Actionsで `make test` + sidecarスモーク(§5)
