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
| OpenAI互換LLMクライアント(Ollama) | ✅ 実装済(**未接続時はオフライン応答を通知で表示**=LLMなしでもUI開発可。履歴には保存しない) | `llm/client.py`(抽象), `llm/openai_compat.py` |
| 会話永続化(ME-01/02の土台) | ✅ 実装済(SQLite: sessions/messages/kv。`user_version` で版管理し、移行前に自動退避) | `memory/store.py` |
| Character Packロード(CH-01/02=口調Lv1) | ✅ 実装済(ロード=pack / 口調合成=persona / 走査・切替=registry) | `character/pack.py`, `character/persona.py`, `character/registry.py`, `api/http/characters.py` |
| Tauriシェル(sidecar・トレイ・ホットキー) | ✅ 2026-11-22 Windows実機で `tauri dev`(dev コア接続・ホットキー・トレイ)と `tauri build`(sidecar 自動起動)を確認。CI で clippy(Windows) | `app/src-tauri/src/*.rs` |
| チャットUI+ステータスレール | ✅ 実装済(接続=useCore / 会話=useChat / 表示コンポーネント3分割) | `app/src/features/chat/` |
| Function Calling・承認ゲート(AC-06) | ⬜ Phase 2(hubに`approval_required`イベント型だけ予約済み) | — |
| RAG / LangGraph / MCP | ⬜ Phase 3 | — |
| 音声(STT/TTS) | ⬜ Phase 4 / Track X2 | — |
| PyInstaller sidecar化 | ✅ Windows で生成・起動を確認(2026-11-22)。CI で Windows/Linux の起動スモーク | `scripts/build_sidecar.py`, `scripts/smoke_sidecar.py` |

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
  make bundle          # tauri build(externalBinとしてコアを同梱。tauri.bundle.conf.json を重ねる)
                       #   → .msi / .dmg / .AppImage
```

- `externalBin` は `tauri.conf.json` ではなく **`tauri.bundle.conf.json`** に置く。
  基本設定に置くと、sidecar を未ビルドのままでは `tauri dev` もビルドスクリプトで失敗するため
- Tauriの`externalBin`は **`名前-{ターゲットトリプル}`** 命名を要求する
  (例: `sentinel-core-x86_64-pc-windows-msvc.exe`)。`build_sidecar.py`が
  `rustc -vV`からトリプルを取得して自動命名する
- PyInstallerは当面 `--onefile`(単一ファイル=externalBinに素直に載る)。
  起動が遅い場合は onedir + resources 方式へ移行(ADR起票の上)
- **sidecarスモークCI**(§14.2):✅ 導入済(2026-11-22)。`scripts/smoke_sidecar.py` が
  ビルド成果物を managed モードで起動→handshake→/health→stdin を閉じて終了、を確認する。
  CI の `sidecar` ジョブが Windows と Linux で実行

## 6. セキュリティ実装の要点(§13対応)

- コアは `127.0.0.1` バインド固定。0.0.0.0にする設定項目を**作らない**
- トークンはmanagedモードで起動毎に`secrets.token_urlsafe(32)`生成。
  ログにトークンを出さない(handshake行はRustが読むのみでログ保存しない)
- CORS は許可するoriginを限定する。**managedでも Tauri の画面のorigin(`http://tauri.localhost`・
  `https://tauri.localhost`・`tauri://localhost`)は許可が必要**(無いとUIからの fetch が
  プリフライトで拒否され、配布ビルドが動かない)。devではそれに加えて Vite(`localhost:5173`)を許可
- uvicorn のログは WS の `?token=` を `token=***` にマスクする(`logging_setup.py`)
- Tauri capabilities は `core:default` のみ(フロントに shell 権限を渡さない。
  sidecar起動はRust側の責務)

## 7. セルフレビュー: 既知の懸念点と導入すべきもの(2026-07-08)

リファクタリング後のコードベースに対する棚卸し。**検証済み:** Pythonテスト7件パス・
tsc+viteビルド成功。**未検証:** Rust/Tauri部分のコンパイル(要ローカル `tauri dev`)。

### 7.1 動作に関わる懸念(優先度高)→ ✅ 全件対処済み(2026-07-08)

| # | 懸念 | 対処(実装済み) |
|---|---|---|
| 1 | **並行生成の混線:** 生成中に同一セッションへ次のメッセージを送ると、2つの生成タスクが同じ`session_id`でtokenを流し、UIの応答バブルが交錯する | ✅ `ChatService`にセッション単位の`asyncio.Lock`で直列化。交錯の再現テスト付き(`test_concurrent_sends_are_serialized`)。Phase 2の`cancel`(barge-in・仕様§18.4)はこのロック点に挿す |
| 2 | **ハンドシェイクのタイミング:** handshake行がuvicornのlisten開始**前**に出力され、受信直後の`/health`が接続失敗し得る | ✅ `server.started`を待ってから出力(`_serve_with_handshake`)。契約を「handshake受信後はリトライ不要」に強化し、実プロセスspawnのスモークテストで検証(`test_handshake.py`=sidecarスモークCIのミニ版) |
| 3 | **health表示が一回きり:** Ollamaを後から起動しても`LLM OFFLINE`表示のまま | ✅ `useCore`が15秒周期で`/health`をポーリング。取得失敗時は`CORE ERROR`表示に落とす(§3「リトライ表示」) |

補足: テスト・CI用にデータディレクトリを`SENTINEL_DATA_DIR`環境変数で隔離可能にした
(スモークテストが実ユーザーデータを汚さないため)。

### 7.2 設計上の割り切り(単一ユーザー・ローカル前提。条件を満たしたら見直し)

| # | 割り切り | 見直し条件 |
|---|---|---|
| 4 | 同期SQLiteをイベントループ上で直接実行(クエリが軽微なため) | RAG導入(Phase 3)で重いクエリが入る時に`asyncio.to_thread`/aiosqlite化 |
| 5 | アクティブキャラがプロセスグローバル(`CharacterRegistry._active`) | セッション毎キャラが必要になったら`sessions.character_id`へ紐づけ直す |
| 6 | EventHubは全WS接続へファンアウト(UI側で`session_id`フィルタ) | 複数ウィンドウ・承認イベント(Phase 2)導入時にセッション購読制へ |
| 7 | ~~オフライン応答・エラー文言もassistantメッセージとして履歴保存される~~ | ✅ 解消(2026-11-22)。案内文は `notice` で表示し保存しない。モデルが生成した文だけを保存(§10) |
| 8 | WSトークンがURLクエリ(§2で規定どおり)・`_find_free_port`のTOCTOU | 低優先の既知事項として記録のみ |

### 7.3 導入すべきもの(推奨順)

1. **CI** — ✅導入済み(`.github/workflows/ci.yml`: pytest+フロントビルド)。
   ✅ **sidecarスモーク**(§5)も導入済み(2026-11-22)
2. ✅ **ruff + mypy / ESLint + Prettier**(仕様§5.4)— 導入済み(2026-07-08)。
   ruffはE/F/W/I/UP/B/SIM+`ruff format`、mypyは**strict**(`core/pyproject.toml`)。
   ESLintはflat config+react-hooks、整形はPrettier(`app/eslint.config.js`)。
   実行: `make lint` / 自動整形: `make fmt`。CIでも全チェックを強制
3. ✅ **パッケージマネージャは npm に統一**(2026-07-08)— 実体が`package-lock.json`
   だったためnpmを採用。Makefile・README・tauri.conf.json・CIすべてnpm表記に統一。
   仕様§4の「pnpm」からの意図的な逸脱として記録(uv化はPhase 2以降に検討)
4. **ログ基盤** — コアはuvicorn既定ログのみ。マスクフィルタ(仕様§13)を挟む前提の
   `logging`設定を機能追加より先に
5. **CSP** — `tauri.conf.json`の`"csp": null`は開発用。配布ビルド(S2)前に必ず設定
6. **ADR運用開始**(仕様 付録A)— 0001(2プロセス構成)〜0003(SQLite)は既に決定済みの内容
   なので、`docs/adr/`に起票して既成事実化しておく

## 8. 次の実装ステップ(このコードベースからの継続)

1. **Phase 2:** `tools/registry.py`+`files.py`(read系のみ)→ `plan_or_respond`を
   Function Calling対応に。承認ゲートは`hub`の`approval_required`イベント+
   `POST /v1/approvals/{id}` を先に固定(UIと同時に)
2. **Track X0:** Character管理UI(一覧・切替は実装済API `/v1/characters` を叩くだけ)
3. ~~**CI:** GitHub Actionsで `make test` + sidecarスモーク(§5)~~ ✅ 導入済み

## 9. 不具合修正の記録(2026-11-22)

2026-11-22 の調査で見つかった、デスクトップアプリとして起動・接続できない不具合を修正した。

| # | 不具合 | 修正 |
|---|---|---|
| B1 | managed で CORS を無効にしていたため、配布ビルドの画面からの fetch がプリフライト(OPTIONS)で 405 になり、コアに接続できない | Tauri の origin を常に許可(§6)。`tests/test_security.py` で回帰テスト |
| B2 | debug ビルドは sidecar を起動しないのに、画面は `get_core_info` の値を待つため、`make tauri-dev` が10秒でタイムアウトする | debug ビルドの `get_core_info` は dev コアの固定値(8765 / dev-token、環境変数 `SENTINEL_DEV_PORT` / `SENTINEL_DEV_TOKEN` で上書き)を返す |
| B2b | `externalBin` が基本設定にあり、sidecar 未ビルドだとビルドスクリプトが失敗する | `tauri.bundle.conf.json` に分離し、`make bundle` だけで重ねる |
| B2c | Rust がコンパイルできなかった(`sidecar.spawn()?` のエラー型不一致、`shutdown_core` のロックガードの寿命) | 修正。debug/release とも `cargo check`・clippy 通過 |
| B3 | ホットキーの押下と離上の両方で表示を切り替えるため、開いた直後に閉じる。Alt+Space は Windows のウィンドウメニューと衝突。登録失敗で起動ごと失敗する | 押下時のみ切替。既定を Ctrl+Shift+Space(失敗時 Ctrl+Alt+Space)にし、`SENTINEL_HOTKEY` で上書き可能。登録できなくても起動は続ける |
| B4 | uvicorn が WS の URL を `?token=` ごとログに出し、Rust 側が stderr に出力していた | uvicorn のロガーにマスクフィルタ |
| B5 | アイコンが 32×32 の png のみで、Windows ビルドに必要な `icon.ico` がない | `tauri icon` で一式を生成(元画像 `icons/app-icon.png`) |

**確認済(2026-11-22, Windows 実機):** `tauri dev` でdev コア接続・Ctrl+Shift+Space の開閉・トレイ、`tauri:bundle` でインストーラ生成と sidecar の自動起動(B9 は Windows では発生せず)。

## 10. 記憶の土台(2026-11-22)

2027年1月から会話を長期の一次記録として貯め始める前に、記録を汚さない・失わないための仕組みを入れた。

| # | 内容 | 実装 |
|---|---|---|
| B8 | DB の版管理がなかった | `memory/store.py` の `MIGRATIONS` に版ごとの SQL を並べ、`PRAGMA user_version` に適用済みの版を記録する。**版を上げるときは末尾に追加するだけで、既存の項目は書き換えない。** 中身のある DB を移行する前に `sentinel.db.bak-v{旧版}` へ複製する。版ごとに1トランザクションで、失敗した版は丸ごと取り消す。アプリより新しい版の DB は開かずに止める(`SchemaTooNewError`) |
| — | オフライン応答・エラー文が AI の発言として保存され、次のターンで LLM に渡っていた | LLM クライアントは推論サーバーが使えないとき `LLMUnavailableError` を送出し、`ChatService` が `notice`(warn)で表示する。保存するのはモデルが実際に生成した文だけ。途中で切れたらそこまでを保存し、何も生成されなければ assistant 発言を作らない |
| B6 | `config/config.default.yaml` が読まれず、既定値が `settings.py` と二重管理だった | 正は `settings.py` の `DEFAULTS`(sidecar 単体で動くよう外部ファイルに頼らない)。yaml は読むための写しとし、`tests/test_settings.py` で一致を検査する |
| B7 | 設定の `character.active` が起動時に反映されず、選んだキャラも再起動で汎用モードに戻った | 起動時のキャラは「前回選んだもの(DB の `kv`)> 設定の `character.active` > 汎用モード」。選び直すと `kv` に保存する。Pack が一時的に無いときは汎用モードで動くが、選択は消さない |
