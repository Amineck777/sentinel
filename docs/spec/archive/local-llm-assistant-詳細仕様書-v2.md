# ローカルLLMパーソナルアシスタント 詳細仕様書

**プロジェクトコード名:** SENTINEL(仮)
**バージョン:** v2.0 Draft(v1.0からの改訂:詳細フォルダ構成・データモデル・API契約・アプリ展開計画を追加)
**作成日:** 2026-07-04
**対象:** 個人開発 → 将来的なアプリ配布・展開を見据えた常駐型AIアシスタント

---

## 目次

1. プロジェクト概要
2. 要件定義(サマリ)
3. システムアーキテクチャ詳細
4. リポジトリ・フォルダ構成(詳細)
5. データモデル設計
6. API契約(インターフェース定義)
7. 設定スキーマ(config.yaml)
8. 段階的実装ロードマップ(展開マイルストーン統合版)
9. アプリ展開計画(パッケージング〜配布)
10. 品質保証・テスト戦略
11. セキュリティ・プライバシー設計
12. リスク管理
13. 成功指標
- 付録A: ADR運用 / 付録B: 用語集

---

## 1. プロジェクト概要

### 1.1 ビジョン

クラウドAPIに依存せず、**完全ローカルで動作する自分専用のPCアシスタント**を構築する。プライバシーを完全に自己管理しながら、PC作業(ファイル操作、情報検索、スケジュール管理、開発補助)を自然言語で委任できる存在を目指す。

長期的には「自分専用ツール」に留めず、**配布可能なデスクトップアプリとして成立する品質**(インストーラ、自動更新、初回セットアップ体験)まで引き上げ、OSS公開または個人プロダクト化の選択肢を持つ。

### 1.2 コアバリュー(設計原則)

| 原則 | 内容 | 影響する設計判断 |
|---|---|---|
| **Privacy First** | 会話・個人データは一切外部送信しない | テレメトリはデフォルトOFF(§9.6)、データはすべてユーザーディレクトリ内 |
| **Progressive Enhancement** | 最小構成から段階拡張、各Phaseで単体価値 | ロードマップDoD(§8) |
| **Loose Coupling** | 推論・音声・ツール・記憶を疎結合に | ポート&アダプタ構成(§4.2)、OpenAI互換API統一 |
| **Standards-Based** | 業界標準準拠で資産流用性を確保 | MCP採用、GGUF、OpenAI互換 |
| **Distributable by Design** | 「自分のPCでしか動かない」実装を最初から避ける | パス・OS依存の抽象化(§4.5)、初回セットアップウィザード(§9.3) |

※ v2.0で **Distributable by Design** を追加。個人利用のみを前提にハードコードすると、展開段階で全面書き直しになるため、Phase 1から適用する。

### 1.3 展開ステージ定義(本仕様書全体を貫く軸)

以降のすべての章は、この4ステージと整合するように記述する。

| ステージ | 名称 | 状態 | 対応Phase |
|---|---|---|---|
| **S1** | Personal | 自分のPCで開発版が動く | Phase 0〜3 |
| **S2** | Portable | 他人のPCでもインストーラ1つで動く | Phase 4 |
| **S3** | Public (OSS) | GitHub公開・第三者がビルド/利用できる | Phase 5 |
| **S4** | Product | 署名済み配布・自動更新・課金導線(任意) | Phase 6(オプション) |

---

## 2. 要件定義(サマリ)

機能要件は5層モデル(入力/理解/行動/記憶/出力)でMECEに分類する。詳細な機能ID表はv1.0 §2.1を正とし、本書では変更点のみ記す。

**v2.0での追加機能要件(展開系):**

| ID | 層 | 機能 | 優先度 | Phase |
|---|---|---|---|---|
| DP-01 | 横断 | 初回セットアップウィザード(モデルDL・依存チェック) | Must(S2以降) | 4 |
| DP-02 | 横断 | 自己診断画面(GPU検出・推論速度テスト) | Should | 4 |
| DP-03 | 横断 | 設定エクスポート/インポート(移行性) | Should | 4 |
| DP-04 | 横断 | 自動更新(Tauri Updater) | Must(S3以降) | 5 |
| DP-05 | 横断 | クラッシュレポート(ローカル保存・手動送信のみ) | Could | 5 |

**非機能要件(v1.0 §2.2に以下を追加):**

| 分類 | 要件 | 目標値 |
|---|---|---|
| 移植性 | 対応OS | Windows 10+ / macOS 13+(S2時点)、Linuxはbest-effort(S3) |
| 配布性 | インストーラサイズ | 本体50MB以下(モデルは初回起動時に別途DL) |
| 配布性 | 初回セットアップ所要時間 | 回線依存を除き10分以内で対話可能に |
| 保守性 | 移行性 | ユーザーデータ一式が単一ディレクトリで、コピーだけでPC間移行可能 |

---

## 3. システムアーキテクチャ詳細

### 3.1 プロセスモデル

配布形態を考慮し、**「UIプロセス」と「コアプロセス」の2プロセス構成**とする。

```
┌────────────────────────── ユーザーのPC ──────────────────────────┐
│                                                                  │
│  ┌─────────────── Tauri App(UIプロセス)───────────────┐          │
│  │  WebView (React)  ←→  Rust Core                     │          │
│  │  ・チャットUI / パレット / 設定 / 記憶管理            │          │
│  │  ・トレイ常駐 / ホットキー / OS通知 / 自動更新         │          │
│  │  ・sidecar管理(コアプロセスの起動・監視・終了)        │          │
│  └───────────────┬─────────────────────────────────────┘          │
│                  │ HTTP + WebSocket (127.0.0.1:{dynamic_port})    │
│  ┌───────────────▼──────── sentinel-core(コアプロセス)──┐         │
│  │  FastAPI + LangGraph                                  │         │
│  │  ・エージェントループ / 承認ゲート / セッション管理      │         │
│  │  ・記憶層(SQLite + sqlite-vec)                        │         │
│  │  ・ツール層(内蔵ツール + MCPクライアント)              │         │
│  │  ・音声層(STT/TTS/VAD)※Phase 4                       │         │
│  └───────┬──────────────────┬───────────────────────────┘         │
│          │ OpenAI互換API     │ MCP (stdio / HTTP)                  │
│  ┌───────▼───────┐   ┌──────▼──────────────────┐                  │
│  │ 推論ランタイム   │   │ MCPサーバー群             │                  │
│  │ Ollama(既定)   │   │ 内蔵: files, web, sys    │                  │
│  │ ※将来差替可     │   │ 外部: Notion, GitHub 等   │                  │
│  └───────────────┘   └─────────────────────────┘                  │
└──────────────────────────────────────────────────────────────────┘
```

**この構成を選ぶ理由(トレードオフ明示):**

| 観点 | 2プロセス(採用) | 単一プロセス(Rust/Tauriに全部) |
|---|---|---|
| AIエコシステム活用 | ◎ Python資産(LangGraph, faster-whisper等)を直接利用 | △ Rustバインディング待ちが多い |
| 配布の複雑さ | △ PyInstaller/sidecar同梱が必要 | ◎ 単一バイナリ |
| 開発速度 | ◎ | △ |
| 再検討条件 | — | Rust製エージェントFWが成熟したらADRで再評価 |

コアプロセスは **PyInstallerでバイナリ化し、Tauriのsidecarとして同梱**する(§9.2)。S1では通常のPythonプロセスとして起動し、S2以降でsidecar化する。両モードは同一コードで動作させる(起動スクリプトの差のみ)。

### 3.2 通信契約

- UI↔コア間は **HTTP(コマンド系)+ WebSocket(ストリーミング系)** のみ。UIがDBやファイルへ直接触ることを禁止する(責務境界の維持と、将来のリモート化=§6.4への布石)
- ポートは起動時に動的割当し、TauriがコアからハンドシェイクJSONで受領。**認証トークン(起動毎に生成)をヘッダ必須**とし、同一PC内の他プロセスからの接続を拒否する
- コア↔推論間はOpenAI互換APIに統一。`config.yaml`のエンドポイント変更のみでOllama/llama.cpp server/クラウド(opt-in)を切替可能

### 3.3 エージェント実行モデル(LangGraph)

```
[user_input]
   → contextualize(RAG検索 + 長期記憶注入)
   → plan_or_respond(LLM: 直接応答 or ツール計画)
   → (ツール計画時) risk_check(承認ゲート)
        ├─ safe        → execute_tool → observe → plan_or_respond(ループ, 最大N回)
        └─ destructive → human_approval(UI確認) → 承認時のみ execute_tool
   → respond(ストリーミング)
   → memorize(非同期: 会話保存 + 長期記憶抽出キュー)
```

- ループ上限・タイムアウト・トークン予算を`config.yaml`で制御(暴走防止)
- `risk_check`はツール宣言メタデータ(`risk: read | write | destructive | external_send`)で機械的に判定し、LLMの自己申告に依存しない

---

## 4. リポジトリ・フォルダ構成(詳細)

### 4.1 モノレポ全体像

```
sentinel/
├── README.md
├── LICENSE                          # S3公開時に決定(§9.5)。それまでprivate
├── CHANGELOG.md                     # Keep a Changelog形式・S2から運用
├── Makefile                         # dev/test/build/packageの統一入口
├── .github/
│   └── workflows/
│       ├── ci.yml                   # lint + test(push毎)
│       ├── build.yml                # 3OSクロスビルド(tagで発火)
│       └── release.yml              # 署名 + GitHub Release + updater manifest
├── config/
│   ├── config.default.yaml          # 出荷既定値(リポジトリ管理)
│   └── config.schema.json           # 設定バリデーション用JSON Schema
├── core/                            # ═══ Pythonコアプロセス ═══
│   ├── pyproject.toml               # uv管理・依存とentry point定義
│   ├── sentinel_core/
│   │   ├── __main__.py              # 起動: ポート割当→ハンドシェイク→serve
│   │   ├── settings.py              # config読込・スキーマ検証・パス解決(§4.5)
│   │   ├── api/                     # ─ プレゼンテーション層 ─
│   │   │   ├── http/
│   │   │   │   ├── chat.py          # POST /v1/chat 等(§6.1)
│   │   │   │   ├── memory.py        # 記憶CRUD・検索
│   │   │   │   ├── tools.py         # ツール一覧・MCP接続管理
│   │   │   │   ├── system.py        # ヘルスチェック・自己診断・モデル管理
│   │   │   │   └── deps.py          # 認証トークン検証・DI
│   │   │   └── ws/
│   │   │       └── stream.py        # WSイベント配信(§6.2)
│   │   ├── agent/                   # ─ アプリケーション層 ─
│   │   │   ├── graph.py             # LangGraphグラフ定義(§3.3)
│   │   │   ├── nodes/               # contextualize / plan / execute / memorize
│   │   │   ├── approval.py          # 承認ゲート(pending状態管理・UI往復)
│   │   │   ├── router.py            # モデルルーティング(Phase 5)
│   │   │   └── prompts/             # システムプロンプト(人格・ツール方針)
│   │   │       ├── persona.md
│   │   │       └── tool_policy.md
│   │   ├── llm/                     # ─ 推論ポート ─
│   │   │   ├── client.py            # LLMClient抽象(chat/stream/embed)
│   │   │   ├── openai_compat.py     # 唯一の実装(Ollama等を包含)
│   │   │   └── model_manager.py     # モデルDL進捗・存在確認(DP-01用)
│   │   ├── memory/                  # ─ 記憶ドメイン ─
│   │   │   ├── repository.py        # Repository抽象(sqlite→pgvector移行点)
│   │   │   ├── sqlite_repo.py
│   │   │   ├── conversation.py      # 会話履歴・セッション
│   │   │   ├── knowledge.py         # RAG: 取込→分割→埋込→検索
│   │   │   ├── profile.py           # 長期記憶(抽出・統合・忘却)
│   │   │   └── migrations/          # スキーマバージョン管理(§5.4)
│   │   ├── tools/                   # ─ 行動ドメイン ─
│   │   │   ├── registry.py          # ツール登録・riskメタデータ管理
│   │   │   ├── builtin/
│   │   │   │   ├── files.py         # 検索/読取/整理(risk別に関数分割)
│   │   │   │   ├── web.py           # 検索・ページ取得
│   │   │   │   └── system.py        # アプリ起動・OS操作(OS別実装は§4.5)
│   │   │   └── mcp/
│   │   │       ├── client.py        # MCPクライアント(stdio/HTTP)
│   │   │       └── catalog.py       # 接続済みサーバー管理・ツール変換
│   │   ├── voice/                   # ─ 音声ドメイン(Phase 4)─
│   │   │   ├── stt.py               # faster-whisper抽象
│   │   │   ├── tts.py               # VOICEVOX / Style-Bert-VITS2抽象
│   │   │   ├── vad.py               # Silero VAD
│   │   │   └── pipeline.py          # wake→VAD→STT→agent→TTSの結線
│   │   ├── scheduler/               # 定期実行(朝ブリーフィング等)
│   │   │   └── jobs.py
│   │   └── platform/                # OS依存の隔離(§4.5)
│   │       ├── paths.py             # データ/キャッシュ/ログの標準パス解決
│   │       ├── win.py / mac.py / linux.py
│   │       └── __init__.py          # 実行時ディスパッチ
│   └── tests/
│       ├── unit/                    # 各ドメインの単体テスト
│       ├── integration/             # API結合・エージェントループ(モックLLM)
│       └── eval/                    # LLM評価(§10.3)ツール呼出精度スイート
├── app/                             # ═══ Tauriデスクトップアプリ ═══
│   ├── package.json                 # pnpm
│   ├── src/                         # React + TypeScript
│   │   ├── main.tsx
│   │   ├── api/                     # コアAPIクライアント(型はopenapiから生成)
│   │   │   ├── client.ts
│   │   │   └── generated/           # openapi-typescript出力(手編集禁止)
│   │   ├── features/                # 機能単位で分割(画面横断の共有を最小化)
│   │   │   ├── chat/                # メッセージリスト・入力・承認ダイアログ
│   │   │   ├── palette/             # ホットキーパレット(Spotlight風)
│   │   │   ├── memory/              # 記憶の閲覧・編集・削除(ME-05)
│   │   │   ├── knowledge/           # RAG取込元管理
│   │   │   ├── settings/            # 設定UI(config.yamlのGUI)
│   │   │   ├── onboarding/          # 初回ウィザード(DP-01)
│   │   │   └── diagnostics/         # 自己診断(DP-02)
│   │   ├── stores/                  # Zustand(セッション・接続状態)
│   │   └── ui/                      # 共通コンポーネント・テーマ
│   ├── src-tauri/
│   │   ├── tauri.conf.json          # updater・署名・バンドル設定(§9)
│   │   ├── capabilities/            # Tauri v2権限定義(最小権限)
│   │   ├── binaries/                # sidecar配置先(CI生成物・gitignore)
│   │   └── src/
│   │       ├── main.rs
│   │       ├── sidecar.rs           # コア起動・ハンドシェイク・死活監視
│   │       ├── tray.rs / hotkey.rs / notify.rs
│   │       └── updater.rs           # 自動更新(DP-04)
│   └── tests/                       # Vitest + Playwright(E2E)
├── mcp-servers/                     # ═══ 自作MCPサーバー置き場(拡張点)═══
│   └── example-notion-bridge/       # 自作ツールは全部ここに増やす
├── scripts/
│   ├── dev.py                       # S1開発起動(core直起動+UI dev server)
│   ├── build_sidecar.py             # PyInstallerビルド(OS別)
│   └── benchmark.py                 # Phase 0モデル計測スクリプト
└── docs/
    ├── spec/                        # 本仕様書(バージョン管理)
    ├── adr/                         # 設計判断記録(付録A)
    │   └── 0001-two-process-architecture.md
    └── dev-guide.md                 # S3公開時のコントリビュートガイド原型
```

### 4.2 構成の設計意図(ポート&アダプタ)

- **`llm/` `memory/repository.py` `voice/` は「ポート(抽象)+アダプタ(実装)」構造。** 差し替え対象(推論・DB・音声)は必ず抽象を経由し、上位層(agent/api)は実装名を知らない
- **`api/` はHTTP/WSの皮のみ**でロジックを持たない。将来UIをリモート化(スマホクライアント等)しても`agent/`以下は無変更
- **`platform/` にOS依存を完全隔離。** `win.py/mac.py/linux.py` 以外のファイルで `sys.platform` 分岐を書くことを禁止(レビュー規約)
- **`app/src/features/` は画面機能単位**。チャットと記憶管理が密結合しない
- **`mcp-servers/` が拡張の主戦場。** コア改修なしでツールが増える構造を物理的に示す

### 4.3 ユーザーデータディレクトリ(実行時レイアウト)

リポジトリとは別に、実行時データは**単一のユーザーディレクトリに集約**する(移行性要件)。

```
{APP_DATA}/sentinel/                 # Win: %APPDATA%  mac: ~/Library/Application Support
├── config.yaml                      # ユーザー設定(default+ユーザー差分のマージ結果ではなく差分のみ)
├── data/
│   ├── sentinel.db                  # SQLite本体(§5)
│   └── attachments/                 # 取込文書の原本コピー
├── models/                          # GGUF等(config でOllama管理に委譲も可)
├── logs/
│   ├── app-YYYYMMDD.log             # ローテーション・個人情報マスク(§11)
│   └── crash/                       # クラッシュダンプ(手動送信のみ)
└── backups/                         # 自動バックアップ(世代管理)
```

- **このディレクトリを丸ごとコピーすればPC間移行が完了**する状態を維持(非機能要件)
- `paths.py` が唯一のパス解決点。コード中の絶対パス直書きを禁止

### 4.4 命名・コード規約(一貫性の担保)

| 対象 | 規約 |
|---|---|
| Python | ruff + mypy strict。ドメイン層はFastAPI/SQLiteをimportしない(依存方向の強制) |
| TypeScript | ESLint + Prettier。API型は`generated/`から以外使用禁止 |
| コミット | Conventional Commits(`feat:` `fix:` 等)→ CHANGELOGとリリースノート自動生成に接続 |
| ブランチ | trunk-based(main + 短命feature)。個人開発だがS3公開時の履歴品質を担保 |
| ツールID | `{namespace}.{verb}_{object}` 例: `files.search_files`, `notion.create_page` |

### 4.5 クロスプラットフォーム戦略

| 関心事 | 方針 |
|---|---|
| パス | `platform/paths.py`(platformdirs準拠)経由のみ |
| ホットキー/トレイ/通知 | Tauri側(Rust)に集約。Pythonでは扱わない |
| アプリ起動・OS操作ツール | `tools/builtin/system.py`→`platform/`ディスパッチ。未対応OSでは当該ツールを登録しない(エラーでなく非表示) |
| GPU検出 | 自己診断(DP-02)でCUDA/Metal/CPUを判定し、推奨モデル・量子化を提示 |

---

## 5. データモデル設計

### 5.1 ER概要

```
sessions 1─* messages *─1 tool_calls(0..*)
sessions *─1 (なし: セッションは独立)
documents 1─* chunks(埋め込みは chunk_embeddings に分離)
profile_facts(長期記憶・独立テーブル)
approvals(承認ゲート監査ログ)
```

### 5.2 主要テーブル定義(SQLite)

```sql
-- 会話
CREATE TABLE sessions (
  id TEXT PRIMARY KEY,              -- ULID
  title TEXT,                       -- 自動要約タイトル
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  archived INTEGER DEFAULT 0
);

CREATE TABLE messages (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  role TEXT NOT NULL CHECK(role IN ('user','assistant','tool','system')),
  content TEXT NOT NULL,
  token_count INTEGER,
  created_at TEXT NOT NULL
);

CREATE TABLE tool_calls (
  id TEXT PRIMARY KEY,
  message_id TEXT NOT NULL REFERENCES messages(id),
  tool_id TEXT NOT NULL,            -- 例: files.search_files
  arguments TEXT NOT NULL,          -- JSON
  result TEXT,                      -- JSON(打切りサイズ上限あり)
  risk TEXT NOT NULL,               -- read/write/destructive/external_send
  status TEXT NOT NULL,             -- ok/error/denied/timeout
  duration_ms INTEGER
);

-- 承認ゲート監査ログ(消さない・改変しない)
CREATE TABLE approvals (
  id TEXT PRIMARY KEY,
  tool_call_id TEXT NOT NULL REFERENCES tool_calls(id),
  requested_at TEXT NOT NULL,
  decided_at TEXT,
  decision TEXT CHECK(decision IN ('approved','denied','expired'))
);

-- RAG
CREATE TABLE documents (
  id TEXT PRIMARY KEY,
  source_type TEXT NOT NULL,        -- file/notion/url/manual
  source_uri TEXT NOT NULL,
  title TEXT,
  content_hash TEXT NOT NULL,       -- 差分再取込判定
  ingested_at TEXT NOT NULL
);

CREATE TABLE chunks (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id),
  seq INTEGER NOT NULL,
  text TEXT NOT NULL
);
-- 埋め込みは sqlite-vec 仮想テーブル chunk_embeddings(chunk_id, embedding)

-- 長期記憶
CREATE TABLE profile_facts (
  id TEXT PRIMARY KEY,
  category TEXT NOT NULL,           -- preference/context/skill/schedule 等
  fact TEXT NOT NULL,
  confidence REAL NOT NULL,         -- 抽出信頼度
  source_message_id TEXT,           -- 出典(説明可能性)
  status TEXT DEFAULT 'active',     -- active/superseded/deleted(論理削除)
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

### 5.3 設計判断

- **埋め込みをchunksから分離:** 埋め込みモデル変更時に`chunk_embeddings`のみ再生成すれば済む(モデル陳腐化対策の物理設計)
- **profile_factsに出典と論理削除:** 「なぜそう記憶しているか」を提示可能にし(ME-05のUI要件)、削除はユーザー主権として即時反映
- **approvalsは追記専用:** 破壊的操作の監査証跡。アプリからの削除UIを提供しない

### 5.4 マイグレーション

- `memory/migrations/` に連番SQL。起動時に`PRAGMA user_version`と突合し自動適用
- **後方互換ルール:** マイグレーションは追加的変更を原則とし、破壊的変更は1バージョンの猶予(旧カラム併存)を挟む。S2以降、他人のPCのDBを壊さないための必須規律

---

## 6. API契約(インターフェース定義)

### 6.1 HTTP API(主要エンドポイント)

OpenAPIスキーマを`core`が自動生成し、UIの型(`app/src/api/generated/`)はそこから生成する。**契約の正はOpenAPI、本表はサマリ。**

| Method | Path | 概要 |
|---|---|---|
| POST | `/v1/chat` | メッセージ送信(応答はWSで受信)。body: `{session_id?, content, attachments?}` |
| POST | `/v1/approvals/{id}` | 承認ゲート応答 `{decision: approved\|denied}` |
| GET | `/v1/sessions` / `/v1/sessions/{id}` | 履歴一覧・詳細 |
| GET | `/v1/memory/facts` | 長期記憶一覧(category filter) |
| PATCH/DELETE | `/v1/memory/facts/{id}` | 記憶の修正・削除(ME-05) |
| POST | `/v1/knowledge/sources` | RAG取込元登録(取込は非同期ジョブ) |
| GET | `/v1/tools` | 利用可能ツール一覧(risk含む) |
| POST | `/v1/mcp/servers` | MCPサーバー追加(設定へ永続化) |
| GET | `/v1/system/health` | 死活・推論疎通・DB状態 |
| GET | `/v1/system/diagnostics` | GPU/速度計測(DP-02) |
| POST | `/v1/system/models/pull` | モデルDL開始(進捗はWS) |

### 6.2 WebSocketイベント(`/v1/stream`)

```jsonc
// server → client(type判別のUnion型)
{"type":"token",          "session_id":"…", "delta":"こん"}
{"type":"message_done",   "session_id":"…", "message_id":"…"}
{"type":"tool_started",   "tool_id":"files.search_files", "arguments_preview":"…"}
{"type":"tool_finished",  "tool_call_id":"…", "status":"ok"}
{"type":"approval_required","approval_id":"…","tool_id":"files.delete_file",
 "risk":"destructive","summary":"report_old.pdf をゴミ箱へ移動します"}
{"type":"job_progress",   "job":"model_pull|ingest", "percent":42}
{"type":"notice",         "level":"info|warn|error", "text":"…"}
```

- イベントスキーマは`type`の追加のみ許可(既存フィールドの削除・意味変更は禁止)。自動更新でUIとコアのバージョンが一時的にズレても壊れないための互換規約

### 6.3 ツール定義契約(内蔵・MCP共通の内部表現)

```jsonc
{
  "id": "files.delete_file",
  "description": "ファイルをゴミ箱へ移動する",
  "parameters": { /* JSON Schema */ },
  "risk": "destructive",        // read | write | destructive | external_send
  "requires_approval": true,     // riskから既定導出、個別上書き可
  "platforms": ["win","mac"]    // 省略時は全OS
}
```

MCP経由のツールは`catalog.py`がこの内部表現へ変換し、**外部MCPツールの既定riskは`external_send`扱い(=要承認)**とする。安全側デフォルト。

### 6.4 将来のリモート化(拡張予約)

本APIは`127.0.0.1`限定だが、契約上リモート化を妨げない設計とする(認証トークン必須・状態レス設計)。S3以降、Tailscale等でのスマホシンクライアント化を追加ADRで検討。

---

## 7. 設定スキーマ(config.yaml)

```yaml
# {APP_DATA}/sentinel/config.yaml — ユーザー差分のみ記述(既定はconfig.default.yaml)
llm:
  endpoint: "http://127.0.0.1:11434/v1"   # OpenAI互換なら何でも可
  chat_model: "your-main-model"            # クラスのみ仕様化・実名は設定で
  light_model: "your-light-model"          # ルーティング用(Phase 5)
  embed_model: "your-embed-model"
  max_tool_loops: 6
  request_timeout_sec: 120

memory:
  rag:
    enabled: true
    top_k: 6
    chunk_size: 800
  profile:
    auto_extract: true          # 長期記憶の自動抽出ON/OFF(ユーザー主権)

tools:
  files:
    allowed_roots:              # ホワイトリスト(これ以外は見えない)
      - "~/Documents"
      - "~/Downloads"
    allow_write: false          # Phase 2既定は読取専用
  web:
    enabled: true
  mcp_servers:
    - name: "notion"
      transport: "http"
      url: "https://mcp.notion.com/mcp"
      enabled: false

voice:                          # Phase 4
  enabled: false
  stt: { engine: "faster-whisper", model_size: "small" }
  tts: { engine: "voicevox", speaker_id: 1 }

app:
  hotkey: "Alt+Space"
  language: "ja"
  telemetry: false              # 既定OFF・S4でもopt-inのみ(§9.6)

updates:                        # S3以降
  channel: "stable"             # stable | beta
  auto_check: true
```

- 起動時に`config.schema.json`で検証し、不正値は**起動失敗ではなく既定値フォールバック+診断画面へ警告**(配布後のサポアビリティ)

---

## 8. 段階的実装ロードマップ(展開マイルストーン統合版)

各PhaseのDoDに**機能の完成条件**と**展開ステージ条件**を併記する。

| Phase | ゴール | 主要スコープ | DoD(機能) | DoD(展開) | ステージ |
|---|---|---|---|---|---|
| **0** 検証(〜1週) | 実用性見極め | `scripts/benchmark.py`でモデル3種計測(日本語/FC精度/速度) | 選定記録がADR化 | — | S1 |
| **1** 対話コア(2〜3週) | 話せる | FastAPI+WS+ストリーミング、人格プロンプト、sessions/messages永続化、簡易ブラウザUI | 毎日使える対話 | `make dev`一発で起動 | S1 |
| **2** 手足+常駐(3〜4週) | 動ける | Function Calling、files/webツール、**承認ゲート+approvals監査**、Tauri移行(トレイ/ホットキー) | 「先週のPDF探して」が通る | UI/コア分離が§3.2契約に準拠 | S1 |
| **3** 知識+自律(4〜6週) | 考えられる | RAG(sqlite-vec)、LangGraphループ、MCPクライアント→Notion接続、履歴横断検索 | 「Notionの学習ログ踏まえて計画立てて」が通る | データが§4.3レイアウトに完全準拠(移行可能) | S1 |
| **4** 記憶+声+可搬化(4〜6週) | 相棒になる | 長期記憶(抽出+管理UI)、音声パイプライン、朝ブリーフィング。**sidecar化+インストーラ+初回ウィザード(DP-01/02/03)** | 音声で予定確認できる | **他人のPCにインストーラだけで導入成功**(友人テスト1名以上) | **S2** |
| **5** 公開+視覚(継続) | 見える・配れる | VLM画面理解、モデルルーティング、**自動更新(DP-04)、CI/CDリリースパイプライン、OSS公開判断** | 「今見てるエラー何?」が通る | GitHub Release+updater稼働、README/dev-guide整備 | **S3** |
| **6** 製品化(任意) | 届ける | コード署名/公証、配布サイト、課金導線検討 | — | §9.5の判断基準を満たした場合のみ着手 | S4 |

```
S1 Personal ────────────────► S2 Portable ──► S3 Public ──► S4 Product(任意)
P0   P1        P2        P3        P4              P5              P6
検証  対話      手足+常駐  知識+自律  記憶+声+可搬化   公開+視覚        製品化
```

---

## 9. アプリ展開計画(パッケージング〜配布)

### 9.1 配布物の構成

| 成果物 | 内容 | サイズ目安 |
|---|---|---|
| インストーラ | Tauriバンドル(UI + Rust + **sidecar化コア**) | 〜50MB |
| モデル | 初回ウィザードでDL(Ollama pull委譲 or 直接GGUF) | 2〜10GB(ユーザー選択) |
| 音声モデル | Phase 4機能ON時のみ追加DL | 〜2GB |

**方針:モデルはインストーラに同梱しない。** サイズ・ライセンス・更新頻度の3点で分離が合理的。初回ウィザード(DP-01)が「GPU検出→推奨モデル提示→DL進捗表示→疎通テスト」までを担う。

### 9.2 パッケージングパイプライン

```
[tag push v*]
  → build.yml(GitHub Actions・3OSマトリクス)
     ├─ core: PyInstaller onedir → app/src-tauri/binaries/{target-triple}/
     ├─ app:  pnpm build → tauri build(sidecar同梱)
     └─ 成果物: .msi/.exe(Win), .dmg(mac), .AppImage/.deb(Linux)
  → release.yml
     ├─ (S4) コード署名・公証(§9.4)
     ├─ GitHub Release作成 + CHANGELOG自動添付
     └─ updater manifest(latest.json)生成・署名
```

**既知の難所と対策(先に仕様化しておく):**

| 難所 | 対策 |
|---|---|
| PyInstallerとネイティブ依存(sqlite-vec, faster-whisper/CTranslate2)の同梱漏れ | Phase 4冒頭に「sidecarスモークテスト」CIを先行構築(起動→/health応答のみ検証) |
| sidecarの孤児プロセス化 | Tauri終了フックでgraceful shutdown→タイムアウト後kill。逆にコア側もparent監視で自殺 |
| ウイルス対策ソフトの誤検知(未署名exe) | S2ではSmartScreen警告を README に明記。S3で署名検討、S4で必須化 |

### 9.3 初回セットアップ体験(DP-01詳細)

```
起動 → ①ようこそ+プライバシー方針(全データローカルの明示)
     → ②環境診断(GPU/VRAM/空き容量) → 推奨構成提示
     → ③推論ランタイム確認(Ollama検出 or 同梱llama.cpp serverへフォールバック)
     → ④モデルDL(進捗+中断再開可)
     → ⑤疎通テスト(1問応答+速度表示)
     → ⑥ホットキー設定・許可(mac: アクセシビリティ権限誘導)
     → 完了(所要10分以内・非機能要件)
```

失敗時は各ステップで「診断ログのコピー」ボタンを提示(DP-05のローカル版)。

### 9.4 更新戦略(DP-04)

- **Tauri Updater + 署名付きlatest.json**(GitHub Releases配信)。チャネルは`stable/beta`
- **UIとコアは常に同一バージョンで配布**(sidecar同梱のため原理的に一致)。ただしWSイベント互換規約(§6.2)により更新直後の再接続も安全
- **DBは自動マイグレーション+直前バックアップ**(`backups/`へ世代保存)。ダウングレードは非サポートと明記

### 9.5 配布チャネルとライセンス戦略

| ステージ | チャネル | ライセンス/条件 |
|---|---|---|
| S2 | 手渡し(知人テスト) | private |
| S3 | GitHub Releases(OSS) | **候補: Apache-2.0(採用実績・特許条項)or PolyForm Noncommercial(商用余地を残す場合)**。公開前にADRで確定。依存(VOICEVOX利用規約・モデルライセンス)の棚卸しを必須タスク化 |
| S4 | 配布サイト+署名済みバイナリ | Win: OVコード署名証明書 / mac: Apple Developer Program(公証)。**年間固定費が発生するため、S4移行判断基準:S3で月間アクティブ利用者(自分以外)が一定数を超え、継続開発意思がある場合のみ** |
| S4+ | ストア(Microsoft Store / Mac App Store) | サンドボックス制約(グローバルホットキー・ファイルアクセス)が本アプリの性質と衝突するため**優先度低**。直接配布を主とする |

**収益化の選択肢(S4・任意):** ①寄付(GitHub Sponsors)②Pro版(クラウドハイブリッド・高度エージェント機能をopt-in提供)③サポート付きライセンス。コア機能のローカル無料は原則として維持(Privacy Firstの信頼が製品価値の源泉のため)。

### 9.6 テレメトリ方針(配布時の信頼設計)

- **既定OFF・opt-inのみ。** 収集する場合も匿名の起動回数・クラッシュ有無程度に限定し、会話内容・ファイルパス・記憶は技術的に送信経路を持たない(コードレベルで送信先を持たない)ことをREADMEに明記
- クラッシュレポート(DP-05)はローカル保存し、ユーザーが内容確認の上で手動添付する方式のみ

---

## 10. 品質保証・テスト戦略

### 10.1 テストピラミッド

| レイヤ | 対象 | ツール | ゲート |
|---|---|---|---|
| Unit | ドメインロジック(risk判定・chunk分割・パス解決) | pytest / Vitest | CI必須・カバレッジ計測 |
| Integration | API契約・エージェントループ(**モックLLM**で決定的に) | pytest + httpx | CI必須 |
| E2E | 起動→対話→承認→終了の主要動線 | Playwright(tauri-driver) | リリース前必須 |
| Smoke(sidecar) | ビルド成果物が起動し/healthが返る | CI(3OS) | S2以降のリリースゲート |

### 10.2 モックLLMの規約

エージェントループのテストは実LLMを使わず、**「入力パターン→固定のツール呼出/応答」を返すFakeClient**で決定的に検証する(LLMClient抽象があるから可能=§4.2の配当)。

### 10.3 LLM評価スイート(eval)

- `tests/eval/`に**ツール呼出精度スイート**(日本語指示50ケース→期待ツール・引数の一致率)を常備
- 実行タイミング:モデル変更時・プロンプト変更時・四半期ごと。結果は`docs/eval-history.md`に記録し、**モデル差替の可否判断を勘でなく数値で行う**

---

## 11. セキュリティ・プライバシー設計

| 領域 | 設計 |
|---|---|
| ネットワーク境界 | コアは127.0.0.1バインド+起動毎トークン認証(§3.2)。外部通信はwebツール・MCP・モデルDL・更新チェックのみで、すべて設定でOFF可能 |
| ファイルアクセス | `allowed_roots`ホワイトリスト外は存在自体を隠蔽。書込みは既定OFF、削除は常にゴミ箱経由 |
| 承認ゲート | risk=destructive/external_sendは必ずUI承認。approvalsテーブルに追記専用監査ログ |
| プロンプトインジェクション | RAG文書・Webページ・MCP結果は「データであり指示ではない」旨をtool_policy.mdで明示+外部由来コンテキスト内の指示でrequires_approvalを緩和しない(ゲートはLLM判断の外側で機械的に適用=§3.3) |
| ログ | パス・メール等をマスクするフィルタを通してから記録。ログレベルで生データ出力を禁止 |
| 保存時保護 | 前提:OSディスク暗号化(BitLocker/FileVault)を初回ウィザードで確認・推奨。S4でSQLCipher再評価 |
| 依存監査 | S3公開前にライセンス・脆弱性スキャン(pip-audit / pnpm audit)をCIへ組込 |

---

## 12. リスク管理

| リスク | 影響 | 対策 | 監視指標 |
|---|---|---|---|
| ローカルモデルのFC精度不足 | ツール誤実行 | evalスイートで閾値管理(§10.3)。未達なら構造化出力+リトライ方式へ切替。承認ゲートが実害を遮断 | eval一致率 |
| VRAM不足・性能劣化 | 応答遅延 | 診断画面で推奨構成提示、量子化調整、軽量ルーティング | TTFT実測 |
| 破壊的操作の暴走 | データ損失 | ホワイトリスト+承認ゲート+ゴミ箱経由+監査ログ | approvals denied率 |
| スコープ肥大で頓挫 | 未完成 | Phase DoD厳守・「毎日使える」状態維持 | 日次利用継続 |
| **配布後の環境差異バグ** | サポート負荷 | 自己診断(DP-02)+診断ログコピー+Smoke CI(3OS) | issue再現率 |
| **依存ライセンス問題(S3)** | 公開差止 | 公開前棚卸しをリリースゲート化(§11) | — |
| **署名・公証の固定費(S4)** | 費用倒れ | S4移行判断基準(§9.5)を満たすまで着手しない | 外部利用者数 |
| 推論エコシステムの変化 | 技術陳腐化 | ポート&アダプタ+OpenAI互換統一。データはプレーン形式維持 | — |

---

## 13. 成功指標(KPI)

| ステージ | 指標 | 目標 |
|---|---|---|
| S1 | 日次利用率 | Phase 2以降、週5日以上自然に起動 |
| S1 | タスク委任成功率 | ツール実行依頼の80%が承認1回以内で完了 |
| S1 | 応答体感 | TTFT 2秒以内維持 |
| S2 | 可搬性 | 自分以外のPCへの導入成功(手順書なし・ウィザードのみ) |
| S3 | 公開品質 | クリーンな環境でREADMEのみでビルド成功/GitHub Star・issueによる外部フィードバック獲得 |
| S3 | 拡張実績 | 月1個ペースでMCPツール追加 |
| S4 | 移行判断 | §9.5の基準充足(自分以外の継続利用者の存在) |

---

## 付録A: 設計判断記録(ADR)運用

大きな技術選定は `docs/adr/` に1判断1ファイルで記録する。フォーマット:**背景 / 選択肢 / 決定 / トレードオフ / 再検討条件**。

初期ADRとして最低限以下を起票する:
- 0001: 2プロセス構成(Tauri + Python sidecar)の採用
- 0002: 推論ランタイムにOllama(OpenAI互換API統一)
- 0003: SQLite + sqlite-vec(pgvector移行条件付き)
- 0004: モデル選定(Phase 0計測結果とともに)
- 0005: ライセンス選定(S3公開前)

## 付録B: 用語集

| 用語 | 定義 |
|---|---|
| sidecar | Tauriアプリに同梱され、アプリが起動・管理する外部バイナリ(本書ではPyInstaller化したコアプロセス) |
| 承認ゲート | risk=destructive/external_sendのツール実行前に必ずユーザー確認を挟む機構。LLMの判断の外側で機械的に適用される |
| ポート&アダプタ | 差し替え対象を抽象(ポート)と実装(アダプタ)に分離する構成。推論・DB・音声に適用 |
| MCP | Model Context Protocol。ツール接続の業界標準。拡張の主経路 |
| S1〜S4 | 展開ステージ(Personal / Portable / Public / Product)。本仕様書全体を貫く軸 |
| DoD | Definition of Done。各Phaseの完了条件(機能+展開の2軸) |
