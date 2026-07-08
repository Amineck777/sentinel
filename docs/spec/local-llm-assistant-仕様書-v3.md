# ローカルLLMパーソナルアシスタント 仕様書

**プロジェクトコード名:** SENTINEL(仮)
**バージョン:** v3.0 Draft
**作成日:** 2026-07-04
**改訂内容:** キャラクター再現拡張(口調・ボイス)を「Character Pack」として正式仕様化。全体構成を4部構成に再編し可読性を改善。

---

## この仕様書の読み方

本書は4部構成。**どこに何が書いてあるか**を最初に示す。

| 部 | 内容 | 主な読者シーン |
|---|---|---|
| **第1部 基本仕様** | ビジョン・要件・アーキテクチャ | 全体像を掴みたいとき |
| **第2部 詳細設計** | フォルダ構成・データモデル・API・設定 | 実装するとき |
| **第3部 展開計画** | ロードマップ・パッケージング・配布・品質・セキュリティ | リリース準備のとき |
| **第4部 拡張仕様:キャラクター再現** | 口調・ボイス再現の技術選定と実装方法 | Character Packを作るとき |

**本書を貫く2つの軸(全章がこれに紐づく):**

```
軸1: 展開ステージ    S1 Personal → S2 Portable → S3 Public → S4 Product(任意)
                    自分のPC      他人のPCでも   OSS公開     署名済み配布
軸2: 機能5層モデル   入力 → 理解 → 行動 → 記憶 → 出力(MECEな機能分類)
```

---
---

# 第1部 基本仕様

## 1. プロジェクト概要

### 1.1 ビジョン

クラウドAPIに依存せず、**完全ローカルで動作する自分専用のPCアシスタント**を構築する。プライバシーを完全に自己管理しながら、PC作業(ファイル操作、情報検索、スケジュール管理、開発補助)を自然言語で委任できる存在を目指す。

さらに本バージョンから、**「好きなキャラクターの口調と声で応答する相棒」**という体験目標を拡張仕様として正式に掲げる(第4部)。汎用アシスタントとしての実用性(第1〜3部)と、キャラクター性という愛着の源泉(第4部)を、**疎結合な「Character Pack」機構**で両立させる。

### 1.2 設計原則

| 原則 | 内容 | 具体的な現れ |
|---|---|---|
| **Privacy First** | 会話・個人データ・音声モデルは一切外部送信しない | テレメトリ既定OFF(§14.6)、Character Packは配布物から技術的に除外(§19) |
| **Progressive Enhancement** | 最小構成から段階拡張、各Phaseで単体価値 | ロードマップDoD(§11) |
| **Loose Coupling** | 推論・音声・ツール・記憶・**キャラクター**を疎結合に | ポート&アダプタ(§5.2)、Character Pack(§16) |
| **Standards-Based** | 業界標準準拠で資産流用性を確保 | OpenAI互換API、MCP、GGUF |
| **Distributable by Design** | 「自分のPCでしか動かない」実装を最初から避ける | パス抽象化(§5.5)、初回ウィザード(§14.3) |
| **Rights-Respecting** *(v3.0新設)* | キャラクター・音声の権利を尊重し、私的利用と配布物を厳格に分離 | §19 権利ガイドライン |

### 1.3 スコープ

- **In:** ローカルLLM対話/PC内操作/RAG/音声対話/**キャラクター口調・ボイス再現(私的利用)**
- **Out:** マルチユーザー対応/クラウド常用(opt-in拡張のみ)/**キャラクター音声モデルの配布・公開**

## 2. 要件定義

### 2.1 機能要件 — 5層モデルによるMECE分類

全機能を「入力→理解→行動→記憶→出力」の5層のいずれか1層に分類する(横断機能はDP系として別掲)。

```
① 入力層  テキスト / ホットキー / 音声 / 画面キャプチャ
② 理解層  LLM推論 / タスク分解 / ルーティング / ★口調生成(ペルソナ)
③ 行動層  内蔵ツール / MCP / 承認ゲート
④ 記憶層  会話履歴 / RAG / 長期記憶 / ★キャラクター設定知識
⑤ 出力層  ストリーミング応答 / 通知 / TTS / ★キャラクターボイス
                                    ★=第4部の拡張が乗る場所
```

**機能ID一覧(優先度と実装Phase):**

| 層 | ID | 機能 | 優先度 | Phase |
|---|---|---|---|---|
| 入力 | IN-01 | テキストチャット | Must | 1 |
| 入力 | IN-02 | グローバルホットキーパレット | Must | 2 |
| 入力 | IN-03 | 音声入力(VAD+STT) | Should | 4 |
| 入力 | IN-04 | 画面キャプチャ理解(VLM) | Could | 5 |
| 理解 | CG-01 | ローカルLLM対話 | Must | 1 |
| 理解 | CG-02 | 人格・振る舞いのプロンプト定義 | Must | 1 |
| 理解 | CG-03 | Function Calling | Must | 2 |
| 理解 | CG-04 | マルチステップエージェント | Should | 3 |
| 理解 | CG-05 | モデルルーティング | Could | 5 |
| 行動 | AC-01 | ファイル操作(ホワイトリスト) | Must | 2 |
| 行動 | AC-02 | Web検索・取得 | Should | 2 |
| 行動 | AC-03 | アプリ起動・OS操作 | Should | 3 |
| 行動 | AC-04 | MCP外部ツール接続 | Should | 3 |
| 行動 | AC-05 | 定期実行(朝ブリーフィング) | Could | 4 |
| 行動 | AC-06 | **承認ゲート(破壊的操作の確認)** | **Must** | **2** |
| 記憶 | ME-01 | セッション内履歴 | Must | 1 |
| 記憶 | ME-02 | 履歴の永続化・横断検索 | Should | 3 |
| 記憶 | ME-03 | 個人文書RAG | Should | 3 |
| 記憶 | ME-04 | 長期記憶(自動抽出) | Could | 4 |
| 記憶 | ME-05 | 記憶の閲覧・編集・削除UI | Should | 4 |
| 出力 | EX-01 | ストリーミング応答 | Must | 1 |
| 出力 | EX-02 | Markdownレンダリング | Must | 1 |
| 出力 | EX-03 | OS通知 | Should | 3 |
| 出力 | EX-04 | TTS読み上げ | Should | 4 |
| 出力 | EX-05 | トレイ常駐UI | Should | 2 |
| 横断 | DP-01 | 初回セットアップウィザード | Must(S2) | 4 |
| 横断 | DP-02 | 自己診断(GPU・速度) | Should | 4 |
| 横断 | DP-03 | 設定エクスポート/インポート | Should | 4 |
| 横断 | DP-04 | 自動更新 | Must(S3) | 5 |
| 横断 | DP-05 | クラッシュレポート(手動送信のみ) | Could | 5 |

**キャラクター再現拡張(CHシリーズ・詳細は第4部):**

| ID | 機能 | 優先度 | 拡張Phase |
|---|---|---|---|
| CH-01 | Character Pack機構(切替・管理UI) | Must(拡張の基盤) | X0 |
| CH-02 | 口調再現 Lv1:プロンプト定義 | Must | X1 |
| CH-03 | 口調再現 Lv2:対話例few-shot+口調RAG+文体検査 | Should | X1 |
| CH-04 | 口調再現 Lv3:LoRA微調整 | Could | X2 |
| CH-05 | ボイス再現:学習型TTS(Style-Bert-VITS2等) | Should | X2 |
| CH-06 | リアルタイム音声対話への統合(文単位合成) | Should | X3 |
| CH-07 | 口調・音声の品質評価スイート | Should | X1〜 |

### 2.2 非機能要件

| 分類 | 要件 | 目標値 |
|---|---|---|
| 性能 | 初回トークンまで(TTFT) | 2秒以内(7B級・GPU) |
| 性能 | 生成スループット | 20 tok/s 以上 |
| 性能 | **音声応答の口が開くまで**(発話終了→再生開始) | **2.5秒以内**(§18.4のレイテンシ予算) |
| リソース | アイドル時メモリ(モデル除く) | 500MB以下 |
| 可用性 | オフライン動作 | コア機能+キャラクター機能はネット遮断でも動作 |
| 移植性 | 対応OS | Win10+/macOS13+(S2)、Linux best-effort(S3) |
| 配布性 | インストーラサイズ / 初回セットアップ | 50MB以下 / 10分以内 |
| 保守性 | 移行性 | ユーザーデータ(Character Pack含む)は単一ディレクトリのコピーで移行完了 |
| セキュリティ | データ境界 | 会話・埋め込み・音声モデルはローカルのみ。破壊的操作は承認必須 |
| **権利** | **配布分離** | **Character Pack(私的学習物)は配布パッケージ・リポジトリに混入しない技術的措置(§19)** |

### 2.3 制約条件

- 開発者1名・週末開発。各Phaseは2〜6週間で完結する粒度
- 想定HW:VRAM 8〜16GBのコンシューマGPU(またはApple Silicon 16GB+)。**TTS学習時のみ12GB以上推奨**
- 言語:Python(コア)+ TypeScript(UI)+ Rust(Tauri薄皮)

## 3. システムアーキテクチャ

### 3.1 プロセスモデル(2プロセス構成)

```
┌────────────────────────── ユーザーのPC ──────────────────────────┐
│  ┌─────────── Tauri App(UIプロセス)────────────┐                 │
│  │ React UI / トレイ / ホットキー / 通知 / 自動更新 │                 │
│  │ sidecar管理(コアの起動・監視・終了)            │                 │
│  └──────────────┬───────────────────────────────┘                 │
│                 │ HTTP+WS (127.0.0.1:{動的port}+token)             │
│  ┌──────────────▼─── sentinel-core(コアプロセス)──────────┐        │
│  │ FastAPI + LangGraph                                     │        │
│  │ ┌─────────┐┌─────────┐┌──────────┐┌─────────────────┐  │        │
│  │ │ agent    ││ memory   ││ tools    ││ voice            │  │        │
│  │ │ ループ/  ││ SQLite+  ││ 内蔵+MCP ││ STT/VAD/TTS      │  │        │
│  │ │ 承認ゲート││ sqlite-vec││          ││ ★TTSはアダプタ制 │  │        │
│  │ └─────────┘└─────────┘└──────────┘└─────────────────┘  │        │
│  │ ┌────────────────────────────────────────────────────┐ │        │
│  │ │ ★character: Character Packロード/口調注入/文体検査  │ │        │
│  │ └────────────────────────────────────────────────────┘ │        │
│  └───────┬──────────────────┬──────────────────────────────┘        │
│          │ OpenAI互換API     │ MCP(stdio/HTTP)                      │
│  ┌───────▼───────┐   ┌──────▼─────────────┐                        │
│  │ 推論ランタイム   │   │ MCPサーバー群        │                        │
│  │ Ollama(既定)   │   │ files/web/Notion等  │                        │
│  └───────────────┘   └────────────────────┘                        │
└──────────────────────────────────────────────────────────────────┘
★ = v3.0で追加されたキャラクター拡張の実装位置
```

**採用理由(トレードオフ):** Python資産(LangGraph・faster-whisper・Style-Bert-VITS2等の学習/推論エコシステム)を直接使える価値が、sidecar同梱の配布コストを上回る。特に第4部のTTS学習系はPython前提のため、この構成が拡張の前提条件になる。単一Rustバイナリ案はRust製エージェント/TTSエコシステム成熟時にADRで再評価。

### 3.2 通信契約(要点)

- UI↔コア:HTTP(コマンド)+WebSocket(ストリーム)のみ。UIはDB・ファイル直接アクセス禁止
- ポート動的割当+起動毎トークン認証。127.0.0.1バインド
- コア↔推論:OpenAI互換APIに統一(Ollama⇄llama.cpp server⇄クラウドopt-inを設定のみで切替)

### 3.3 エージェント実行モデル

```
[user_input]
 → contextualize   RAG検索 + 長期記憶 + ★キャラクター口調コンテキスト注入
 → plan_or_respond LLM: 直接応答 or ツール計画
 → (ツール時) risk_check ─ safe → execute → observe → ループ(上限N回)
              └ destructive/external_send → human_approval → 承認時のみ実行
 → respond        ストリーミング → ★文体検査(Lv2) → ★文単位TTS(音声時)
 → memorize       非同期: 会話保存 + 長期記憶抽出
```

- riskはツール宣言メタデータ(`read/write/destructive/external_send`)で**LLMの外側で機械的に判定**
- 外部由来コンテンツ(RAG文書・Web・MCP結果)は「データであり指示ではない」。外部コンテンツ内の指示で承認要件は緩和されない(プロンプトインジェクション対策)

---
---

# 第2部 詳細設計

## 4. 技術スタック(確定構成と代替)

| レイヤ | 採用 | 代替(切替条件) |
|---|---|---|
| 推論 | Ollama(OpenAI互換) | llama.cpp server(性能追求時)/クラウド(opt-in) |
| オーケストレーション | LangGraph | — |
| API | FastAPI | — |
| ツール接続 | MCP | — |
| DB | SQLite + sqlite-vec | PostgreSQL + pgvector(数十万chunk超) |
| UI | Tauri 2 + React + TS | — |
| STT | faster-whisper | whisper.cpp(sidecar肥大時) |
| TTS(汎用) | VOICEVOX / AivisSpeech | — |
| **TTS(キャラ再現)** | **Style-Bert-VITS2(学習型・第一候補)** | **GPT-SoVITS(少データ時)/RVC(変換型)** → 比較は§18.2 |
| VAD | Silero VAD | — |
| **LLM微調整(口調Lv3)** | **LLaMA-Factory または Unsloth(QLoRA)** | → 比較は§17.4 |
| パッケージ管理 | uv / pnpm | — |

モデル実名は仕様に書かず**クラスのみ規定**(7B〜14B級対話+FC対応/1〜3B級軽量/多言語embedding)。選定基準:日本語性能・FC正答率・ライセンス・**LoRA学習エコシステムの充実度**(第4部の前提)。

## 5. リポジトリ・フォルダ構成

### 5.1 モノレポ全体像

```
sentinel/
├── README.md / LICENSE / CHANGELOG.md / Makefile
├── .github/workflows/          # ci.yml / build.yml / release.yml
├── config/
│   ├── config.default.yaml
│   └── config.schema.json
├── core/                        # ═══ Pythonコア ═══
│   ├── pyproject.toml
│   ├── sentinel_core/
│   │   ├── __main__.py          # 起動→ポート割当→ハンドシェイク
│   │   ├── settings.py          # config読込・検証・パス解決
│   │   ├── api/
│   │   │   ├── http/            # chat/memory/tools/system/characters ★
│   │   │   └── ws/stream.py
│   │   ├── agent/
│   │   │   ├── graph.py         # §3.3のグラフ
│   │   │   ├── nodes/           # contextualize/plan/execute/memorize
│   │   │   ├── approval.py      # 承認ゲート
│   │   │   └── prompts/         # 基本人格・ツール方針(キャラ非依存の土台)
│   │   ├── character/           # ═ ★キャラクター拡張(第4部)═
│   │   │   ├── pack.py          # Character Packのロード・検証・切替
│   │   │   ├── persona.py       # 口調コンテキスト合成(Lv1/Lv2)
│   │   │   ├── style_check.py   # 文体検査(語尾・一人称・禁止語)
│   │   │   ├── style_rag.py     # セリフ検索(口調RAG)
│   │   │   └── schema.py        # character.yaml スキーマ
│   │   ├── llm/
│   │   │   ├── client.py        # 抽象(chat/stream/embed)
│   │   │   ├── openai_compat.py
│   │   │   ├── lora.py          # ★口調LoRAのロード指定(Lv3)
│   │   │   └── model_manager.py
│   │   ├── memory/
│   │   │   ├── repository.py    # 抽象(SQLite→pgvector移行点)
│   │   │   ├── sqlite_repo.py / conversation.py / knowledge.py / profile.py
│   │   │   └── migrations/
│   │   ├── tools/
│   │   │   ├── registry.py      # riskメタデータ管理
│   │   │   ├── builtin/         # files.py / web.py / system.py
│   │   │   └── mcp/             # client.py / catalog.py
│   │   ├── voice/
│   │   │   ├── stt.py / vad.py / pipeline.py
│   │   │   ├── tts/             # ═ ★TTSアダプタ制 ═
│   │   │   │   ├── base.py      # TTSEngine抽象(synthesize/stream)
│   │   │   │   ├── voicevox.py  # 汎用(ライセンス明確)
│   │   │   │   ├── sbv2.py      # Style-Bert-VITS2(キャラ再現)
│   │   │   │   └── gpt_sovits.py# 少データ・比較用
│   │   │   └── player.py        # 再生キュー(文単位・割込停止)
│   │   ├── scheduler/jobs.py
│   │   └── platform/            # OS依存の完全隔離(paths/win/mac/linux)
│   └── tests/                   # unit / integration / eval(§13.3, §17.6)
├── app/                         # ═══ Tauri UI ═══
│   ├── src/
│   │   ├── api/generated/       # OpenAPIから型生成(手編集禁止)
│   │   ├── features/
│   │   │   ├── chat / palette / memory / knowledge / settings
│   │   │   ├── onboarding / diagnostics
│   │   │   └── character/       # ★Pack切替・口調テスト・音声試聴UI
│   │   └── stores/ ui/
│   ├── src-tauri/               # sidecar.rs / tray.rs / hotkey.rs / updater.rs
│   └── tests/
├── training/                    # ═══ ★学習パイプライン(配布物に含めない)═══
│   ├── style_lora/              # 口調LoRA: データ整形→学習→評価(§17.4)
│   │   ├── prepare_dataset.py   # examples.jsonl→学習形式変換
│   │   ├── configs/             # LLaMA-Factory/Unsloth設定
│   │   └── evaluate.py          # 口調評価スイート実行
│   └── voice_tts/               # TTS学習: 前処理→学習→書出し(§18.3)
│       ├── preprocess.py        # 音声正規化・無音分割・書き起こし整合
│       └── notes.md             # 学習手順・ハイパラ記録
├── mcp-servers/                 # 自作MCPサーバー置き場(拡張の主戦場)
├── scripts/                     # dev.py / build_sidecar.py / benchmark.py
└── docs/                        # spec / adr / dev-guide / eval-history
```

### 5.2 構成の設計意図

- **ポート&アダプタ:** `llm/client.py`・`memory/repository.py`・`voice/tts/base.py` が抽象。上位層は実装名を知らない。**キャラボイス追加=`tts/`にアダプタ1ファイル追加**で完結
- **`character/`は独立ドメイン:** agentは「口調コンテキストを受け取る」だけで、Packの中身を知らない。**キャラ機能を丸ごとOFFにしても汎用アシスタントとして完全動作**(疎結合の検証条件)
- **`training/`はランタイムから分離:** 学習はオフライン作業。配布ビルド(§14)の対象外とし、リポジトリ公開時(S3)も学習済み成果物は含まれない
- **OS依存は`platform/`のみ**。`sys.platform`分岐の散在を規約で禁止

### 5.3 ユーザーデータディレクトリ(実行時)

```
{APP_DATA}/sentinel/            # Win: %APPDATA% / mac: ~/Library/Application Support
├── config.yaml                 # ユーザー差分のみ
├── data/
│   ├── sentinel.db             # SQLite(§6)
│   └── attachments/
├── models/                     # LLM(Ollama委譲も可)
├── characters/                 # ═══ ★Character Pack置き場(§16.2)═══
│   └── {char_id}/              # 1キャラ=1フォルダ=コピーで移行可能
├── logs/  backups/
```

**移行性:** このディレクトリの丸コピーでPC間移行が完了する(Character Pack含む)。

### 5.4 規約(一貫性の担保)

| 対象 | 規約 |
|---|---|
| Python | ruff + mypy strict。ドメイン層はFastAPI/SQLiteをimport禁止(依存方向強制) |
| TS | ESLint + Prettier。API型は`generated/`以外から使用禁止 |
| コミット | Conventional Commits → CHANGELOG自動生成 |
| ツールID | `{namespace}.{verb}_{object}`(例: `files.search_files`) |
| **キャラID** | **`{char_id}`は英数小文字スネークケース。Pack内ファイル名は§16.2に固定** |

### 5.5 クロスプラットフォーム戦略

パスは`platform/paths.py`(platformdirs準拠)経由のみ/トレイ・ホットキー・通知はRust側に集約/OS未対応ツールはエラーでなく非登録/GPU検出は自己診断(DP-02)で行い推奨構成を提示(**TTS学習可否もここで判定**)。

## 6. データモデル(SQLite)

```sql
-- 会話系
sessions(id, title, character_id, created_at, updated_at, archived)   -- ★どのキャラとの会話か
messages(id, session_id, role, content, token_count, created_at)
tool_calls(id, message_id, tool_id, arguments, result, risk, status, duration_ms)
approvals(id, tool_call_id, requested_at, decided_at, decision)        -- 追記専用監査ログ

-- RAG系
documents(id, source_type, source_uri, title, content_hash, ingested_at)
chunks(id, document_id, seq, text)
-- 埋め込みは sqlite-vec 仮想テーブル chunk_embeddings に分離(埋込モデル変更時の再生成を局所化)

-- 長期記憶
profile_facts(id, category, fact, confidence, source_message_id, status, created_at, updated_at)
-- 出典と論理削除を持つ=「なぜそう記憶したか」を提示可能・ユーザー主権で即削除

-- ★口調RAG(Character Pack由来・キャラ毎に名前空間分離)
style_lines(id, character_id, situation, line_text)
-- 埋め込みは style_embeddings(sqlite-vec)。Packの examples.jsonl から取込
```

マイグレーションは連番SQL+`PRAGMA user_version`で自動適用。追加的変更を原則とし、破壊的変更は1バージョン併存猶予(配布後にDBを壊さない規律)。

## 7. API契約

正はOpenAPI自動生成(UI型はそこから生成)。主要エンドポイントのサマリ:

| Method | Path | 概要 |
|---|---|---|
| POST | `/v1/chat` | 送信(応答はWS)。`{session_id?, content, character_id?}` |
| POST | `/v1/approvals/{id}` | 承認応答 `{decision}` |
| GET | `/v1/sessions` `/v1/sessions/{id}` | 履歴 |
| GET/PATCH/DELETE | `/v1/memory/facts…` | 長期記憶CRUD(ME-05) |
| POST | `/v1/knowledge/sources` | RAG取込(非同期ジョブ) |
| GET | `/v1/tools` / POST `/v1/mcp/servers` | ツール・MCP管理 |
| GET | `/v1/system/health` `/diagnostics` | 死活・自己診断 |
| **GET** | **`/v1/characters`** | **★Pack一覧(検証結果含む)** |
| **POST** | **`/v1/characters/{id}/activate`** | **★キャラ切替(モデル/LoRA/TTSの再構成)** |
| **POST** | **`/v1/characters/{id}/tts_preview`** | **★試聴合成(character UIから)** |

**WSイベント(`/v1/stream`)** — `type`追加のみ許可(削除・意味変更禁止=更新時互換):

```jsonc
{"type":"token","delta":"…"}  {"type":"message_done","message_id":"…"}
{"type":"tool_started","tool_id":"…"}  {"type":"tool_finished","status":"ok"}
{"type":"approval_required","approval_id":"…","risk":"destructive","summary":"…"}
{"type":"job_progress","job":"model_pull|ingest|tts_synth","percent":42}
{"type":"audio_chunk","seq":1,"format":"wav","data_b64":"…"}   // ★文単位TTS(§18.4)
{"type":"notice","level":"info|warn|error","text":"…"}
```

## 8. 設定スキーマ(config.yaml 抜粋)

```yaml
llm:
  endpoint: "http://127.0.0.1:11434/v1"
  chat_model: "your-main-model"        # 実名は設定で・仕様はクラスのみ規定
  light_model: "your-light-model"
  embed_model: "your-embed-model"
  max_tool_loops: 6

character:                              # ★第4部
  active: "none"                        # none=汎用モード / {char_id}
  style_check: true                     # Lv2文体検査のON/OFF
  style_rag_top_k: 3

memory:
  rag: { enabled: true, top_k: 6, chunk_size: 800 }
  profile: { auto_extract: true }

tools:
  files: { allowed_roots: ["~/Documents","~/Downloads"], allow_write: false }
  web: { enabled: true }
  mcp_servers:
    - { name: "notion", transport: "http", url: "https://mcp.notion.com/mcp", enabled: false }

voice:
  enabled: false
  stt: { engine: "faster-whisper", model_size: "small" }
  tts: { engine: "voicevox", speaker_id: 1 }   # Pack有効時はPack側設定が優先(§16.3)

app: { hotkey: "Alt+Space", language: "ja", telemetry: false }
updates: { channel: "stable", auto_check: true }
```

不正値は起動失敗ではなく**既定値フォールバック+診断画面へ警告**(配布後サポアビリティ)。

---
---

# 第3部 展開計画

## 11. ロードマップ(本編Phase+拡張Track)

**本編PhaseとキャラクターTrackを分離**し、拡張が本編の頓挫要因にならない構造とする。TrackはPhase 4完了後いつでも着手可能(X0のみPhase 1完了で着手可)。

### 本編Phase

| Phase | ゴール | 主要スコープ | DoD(機能/展開) | ステージ |
|---|---|---|---|---|
| **0** 検証(〜1週) | 見極め | benchmark.pyでモデル3種計測(日本語/FC/速度) | 選定ADR化 / — | S1 |
| **1** 対話コア(2〜3週) | 話せる | ストリーミング対話・人格・履歴永続化・簡易UI | 毎日使える / `make dev`一発 | S1 |
| **2** 手足+常駐(3〜4週) | 動ける | FC・files/webツール・**承認ゲート**・Tauri常駐 | 「先週のPDF探して」が通る / UIコア分離契約準拠 | S1 |
| **3** 知識+自律(4〜6週) | 考えられる | RAG・LangGraphループ・MCP→Notion・横断検索 | 「Notionの学習ログ踏まえて計画を」が通る / データレイアウト準拠 | S1 |
| **4** 記憶+声+可搬化(4〜6週) | 相棒になる | 長期記憶+管理UI・音声対話・ブリーフィング・**sidecar化+インストーラ+ウィザード** | 音声で予定確認 / **他人のPCへ導入成功** | **S2** |
| **5** 公開+視覚(継続) | 配れる | VLM・ルーティング・自動更新・リリースCI・OSS判断 | 画面理解が通る / Release+updater稼働 | **S3** |
| **6** 製品化(任意) | 届ける | 署名・公証・配布サイト | §14.5の判断基準充足時のみ | S4 |

### キャラクター拡張Track(第4部の実装順)

| Track | 内容 | 前提 | 期間目安 |
|---|---|---|---|
| **X0** Pack基盤 | Character Pack機構・切替UI・汎用TTSでの音声切替 | Phase 1 | 1〜2週 |
| **X1** 口調 | Lv1プロンプト → Lv2 few-shot+口調RAG+文体検査 → 評価スイート | X0 | 2〜3週 |
| **X2** 声と文体の深化 | TTS学習(SBV2)→ アダプタ統合 /(任意)口調LoRA | X0, Phase 4 | 3〜6週 |
| **X3** リアルタイム統合 | 文単位ストリーミング合成・割込(barge-in)・レイテンシ予算達成 | X2 | 2〜3週 |

```
本編:   P0─P1────P2────P3────P4━━━━P5──────▶
拡張:        └X0──────X1 ‥‥‥‥‥┗X2────X3──▶
                 (X0/X1は本編と並走可・X2はPhase4の音声基盤に合流)
```

## 12〜14. 品質・セキュリティ・展開(要点)

### 12. 品質保証

| レイヤ | 対象 | ツール | ゲート |
|---|---|---|---|
| Unit | risk判定・chunk分割・パス解決・**文体検査** | pytest/Vitest | CI必須 |
| Integration | API契約・エージェントループ(**モックLLM**で決定的に) | pytest+httpx | CI必須 |
| E2E | 起動→対話→承認→終了 | Playwright | リリース前 |
| Smoke | ビルド成果物の起動+/health(3OS) | CI | S2以降ゲート |
| Eval | ツール呼出精度50ケース+**口調評価(§17.6)** | 自作スイート | モデル/プロンプト/LoRA変更時 |

### 13. セキュリティ・プライバシー

- 127.0.0.1+トークン/`allowed_roots`外は不可視/削除はゴミ箱経由/承認ゲートはLLM外で機械適用/外部コンテンツは指示扱いしない/ログはマスクフィルタ経由/OSディスク暗号化をウィザードで確認/S3公開前に依存ライセンス・脆弱性監査をCI化
- **音声データの扱い(v3.0追加):** 学習用音声・学習済み音声モデルは`characters/`と`training/`内に限定し、ログ・クラッシュレポート・バックアップ外部保存の対象から除外可能とする

### 14. パッケージング・配布

- **14.1 配布物:** インストーラ(UI+Rust+sidecarコア、〜50MB)。LLM/音声モデルは初回ウィザードでDL。**Character Packは配布物に決して同梱しない(§19)**
- **14.2 パイプライン:** tag→3OSビルド(PyInstaller onedir→Tauri sidecar同梱)→Release+署名付きupdater manifest。既知の難所:ネイティブ依存同梱漏れ(**CTranslate2に加えSBV2系の依存が増えるため、sidecarスモークCIをX2着手前に増強**)/孤児プロセス(相互死活監視)/未署名警告(S3で署名検討)
- **14.3 初回ウィザード:** ようこそ(全データローカル明示)→環境診断→ランタイム確認→モデルDL→疎通テスト→ホットキー許可。10分以内
- **14.4 更新:** Tauri Updater+署名manifest。UIとコアは同梱ゆえ常に同一版。DB自動マイグレーション+直前バックアップ
- **14.5 チャネル/ライセンス:** S2手渡し→S3 GitHub Releases(**Apache-2.0 or PolyForm NC、公開前ADR+依存棚卸し必須**)→S4署名配布(**判断基準:自分以外の継続利用者が存在し開発継続意思がある場合のみ**。ストアはサンドボックス制約と衝突するため優先度低)。収益化はコアのローカル無料を原則維持
- **14.6 テレメトリ:** 既定OFF・opt-inのみ。会話・パス・記憶・**音声**は送信経路をコードレベルで持たない

---
---

# 第4部 拡張仕様:キャラクター再現(口調・ボイス)

> **位置づけ:** 本拡張は**私的利用(自分のPC)を前提**とする。権利面の方針(§19)が全設計の前提であり、技術仕様(§16〜18)はその枠内で成立する。

## 15. 拡張の全体像

### 15.1 目標体験

「好きなキャラクターの**口調**で応答し、そのキャラクターの**声**で喋る」アシスタント。ただし——

- **中身はSENTINELのまま:** ツール実行・RAG・記憶などの実用機能はキャラクターに依存しない。キャラはあくまで**表現層のスキン+理解層のスタイル**
- **切替可能:** 汎用モード⇄キャラモードをワンタップで切替。複数キャラの共存も可能
- **段階的品質:** 口調はLv1(即日)→Lv3(高忠実)、声は既製→学習型へ、投資対効果を見て深化

### 15.2 「キャラクター再現」の分解(MECE)

キャラクター再現を4要素に分解し、それぞれ独立に実装・評価できるようにする。

| 要素 | 内容 | 実装位置 | 対応§ |
|---|---|---|---|
| **① 口調(文体)** | 一人称・語尾・敬語レベル・口癖・言い回し | 理解層(プロンプト/LoRA)+出力検査 | §17 |
| **② 人格(判断傾向)** | 性格・価値観・反応パターン | 理解層(persona.md) | §17.2 |
| **③ 知識(設定)** | キャラの背景・関係性・世界観 | 記憶層(口調RAG/設定RAG) | §17.3 |
| **④ 声(音響)** | 声質・話し方・抑揚・スタイル | 出力層(TTSアダプタ) | §18 |

**再現度の議論はこの4要素を混同しないこと。**「声は似てるが口調が崩れる」「口調は完璧だが設定を間違える」は別の問題であり、対処も別(④はTTS、①は文体検査/LoRA、③はRAG)。

## 16. Character Pack機構(CH-01)

### 16.1 コンセプト

キャラクターに関わる全アセットを**1フォルダに完結**させ、「フォルダを置けばキャラが増え、消せば消える」状態にする。コア本体はキャラ固有情報を一切持たない。

### 16.2 Packのフォルダ構成(規格)

```
{APP_DATA}/sentinel/characters/{char_id}/
├── character.yaml          # マニフェスト(下記)— これだけは必須
├── persona/
│   ├── persona.md          # ②人格: 性格・価値観・応答方針(自然文)
│   ├── speech_style.md     # ①口調: 一人称/二人称/語尾/敬語/口癖/禁止表現(規則)
│   ├── examples.jsonl      # ①few-shot兼学習データ: {"situation","user","reply"}
│   └── knowledge.md        # ③設定: 背景・関係性(設定RAGへ取込)
├── voice/
│   ├── model/              # ④学習済みTTSモデル(SBV2 safetensors等)
│   └── reference/          # 参照音声(GPT-SoVITS用・数秒〜)
├── lora/                   # ①口調LoRA(Lv3・任意)
│   └── adapter/            # PEFT形式
└── assets/
    └── avatar.png          # UI表示用(任意)
```

```yaml
# character.yaml(マニフェスト)
schema_version: 1
id: "my_char"
display_name: "○○"
style:
  level: 2                      # 1=プロンプトのみ 2=+few-shot/RAG/検査 3=+LoRA
  first_person: "私"            # 文体検査(§17.5)が参照する機械可読ルール
  sentence_endings: ["〜わ", "〜のよ"]
  forbidden: ["っす", "であります"]
voice:
  engine: "sbv2"                # voicevox | sbv2 | gpt_sovits
  model_path: "voice/model"
  style: "Neutral"              # SBV2のスタイル名
  speed: 1.0
llm:
  lora_path: null               # "lora/adapter" でLv3有効化
notes: "私的利用限定。出典・学習データのメモ(§19.4の台帳を兼ねる)"
```

### 16.3 ロードと切替の動作仕様

1. 起動時に`characters/`を走査し、`character.yaml`をスキーマ検証(不正Packは**無効化+診断画面に理由表示**、起動は止めない)
2. `POST /v1/characters/{id}/activate`で:①persona/speech_styleをシステムプロンプトへ合成 ②examples.jsonlを口調RAG(style_lines)へ同期 ③TTSアダプタをPack設定で再構成 ④(Lv3)LoRAロード指示
3. **フォールバック連鎖:** LoRAロード失敗→Lv2動作/TTSモデル失敗→汎用TTS/Pack全体失敗→汎用モード。**どの失敗でもアシスタント本体は動き続ける**
4. セッションには`character_id`を記録(§6)。キャラ切替は新セッション開始を推奨(履歴混線防止)

## 17. 口調・人格の再現(CH-02〜04)

### 17.1 3レベル戦略(投資対効果で段階選択)

| | **Lv1 プロンプト** | **Lv2 +few-shot/RAG/検査** | **Lv3 +LoRA微調整** |
|---|---|---|---|
| 手法 | speech_style.md+persona.mdをシステムプロンプト注入 | Lv1+類似場面のセリフをRAG注入+出力の文体検査&リトライ | Lv2+対話データでQLoRA学習 |
| 必要データ | 設定文章のみ | 対話例 30〜100件 | 対話例 500〜3,000件 |
| 再現度 | 中(長会話で崩れやすい) | 中高(崩れを検査で矯正) | 高(素の出力が既に口調) |
| コスト | 0(即日) | 低(数日) | 中(データ作成が支配的+学習数時間) |
| リスク | 崩れ・カタコト化 | RAG依存でトークン消費増 | 過学習で汎用能力低下(→評価§17.6で監視) |
| 適用判断 | まず全キャラこれ | 常用キャラ | Lv2で崩れ率が目標未達のキャラのみ |

**重要な設計判断:Lv3でもLv1/Lv2の仕組みは併用する。** LoRAは「素の傾向」を作り、プロンプトとRAGが「設定の正確さ」を、文体検査が「最後の砦」を担う。層別防御。

### 17.2 persona.md / speech_style.md の書き方(規格)

- **persona.md(人格):** 自然文で「性格・価値観・ユーザーとの関係・やらないこと」。**アシスタント業務との整合節を必須とする**(例:「ツール実行や承認確認などの実務説明は、キャラの口調を保ちつつ正確さを優先する」)。キャラ演技が承認ゲートの文言を曖昧にすることを禁止
- **speech_style.md(口調):** 規則の列挙——一人称/二人称/語尾パターン(頻度感も)/敬語レベル/口癖(乱用禁止の注記)/感情別の変化/**禁止表現**。character.yamlの機械可読ルールと一致させる(検査と定義の二重管理を防ぐため、yaml側が正でmdは説明)

### 17.3 examples.jsonl と口調RAG(Lv2)

```jsonl
{"situation":"朝の挨拶","user":"おはよう","reply":"おはよう。今日も頑張りましょうね。"}
{"situation":"タスク完了報告","user":"","reply":"終わったわよ。次は何をすればいい?"}
{"situation":"エラー発生","user":"","reply":"…少し問題が起きたみたい。原因を調べるわね。"}
```

- **場面(situation)を必ず付与**する。実行時は「現在の会話状況」をクエリに`style_lines`をベクトル検索し、類似場面のセリフをtop-k件プロンプトへ注入(「このように話す」参照例として)
- **アシスタント特有場面を必ずカバー:** 挨拶/作業報告/エラー/承認依頼/雑談/励まし。既存作品のセリフだけでは「PCアシスタント文脈」が欠けるため、**自分で書き下ろす二次創作的作業が品質の核心**になる(ここは自動化できない工程として計画に織り込む)

### 17.4 口調LoRA(Lv3・CH-04)

| 項目 | 仕様 |
|---|---|
| 手法 | QLoRA(4bit)。対象:メイン対話モデル(FC対応7B〜14B級) |
| ツール比較 | **LLaMA-Factory**(GUI/設定ファイル型・再現性◎・第一候補)/ **Unsloth**(高速・省VRAM・Colab逃しも可) |
| データ | examples.jsonl拡張(500件〜)。**多様な場面×口調一貫**が枚数より重要。既存セリフ流用+書き下ろし+**Lv2運用ログから良回答を昇格**(運用がデータを育てる循環) |
| 学習環境 | ローカルGPU(12GB+目安)。不足時はクラウドGPU利用可だが**学習データに個人会話を含める場合はローカル限定**(Privacy First) |
| 重要な検証 | **FC能力の劣化検査を必須ゲートに:** 口調学習後に本編evalスイート(ツール呼出50ケース)を再実行し、一致率低下が閾値超なら不採用。「可愛くなったが仕事ができなくなった」を数値で防ぐ |
| 運用 | 成果物はPackの`lora/adapter/`へ。ベースモデル更新時は再学習前提(ADRに学習条件を記録) |

### 17.5 文体検査(style_check・Lv2の要)

- 生成テキストに対し**機械検査**(character.yamlのルール):一人称不一致/禁止表現/語尾逸脱率
- 逸脱検出時は①軽微→自動置換 ②重度→「口調を維持して言い直し」を1回だけリトライ(無限ループ禁止)
- 検査はストリーミングと両立させるため**文単位**で実施(§18.4のTTS分割と同じ境界を使う=実装共通化)

### 17.6 口調品質の評価スイート(CH-07)

| 指標 | 測り方 | 目標 |
|---|---|---|
| 文体遵守率 | 固定50プロンプト→機械検査(§17.5)の通過率 | 95%以上 |
| 人格一貫性 | LLM-as-judge(汎用モデルに「このキャラらしいか」5段階評価) | 平均4.0以上 |
| 長会話劣化 | 30往復会話の後半10往復の文体遵守率 | 前半比-5pt以内 |
| **業務能力維持** | **本編ツール呼出eval一致率(Lv3のみ)** | **ベース比-3pt以内** |

結果は`docs/eval-history.md`へ記録し、Lv2→Lv3移行判断・LoRA採否を数値で行う。

## 18. ボイス再現(CH-05〜06)

### 18.1 前提:2つのアプローチ

```
A) 既製キャラクター音声   VOICEVOX / AivisSpeech等の公式配布音声
   → 権利が明確・即日・ただし「そのキャラ」ではない
B) 学習型再現            対象キャラの音声データからTTSモデルを学習
   → 「そのキャラ」の声・ただし私的利用限定(§19)・データと学習の工数
```

**方針:** X0でAを導入して音声体験を先に完成させ、X2でBへ深化する。Bが失敗してもAへフォールバック(§16.3)。

### 18.2 学習型TTSの技術選定(B)

| | **Style-Bert-VITS2(第一候補)** | **GPT-SoVITS** | **RVC(声質変換)** |
|---|---|---|---|
| 方式 | テキスト→音声(学習型TTS) | テキスト→音声(few-shot参照型) | 音声→音声(既存TTS出力や自声を変換) |
| 必要データ | **クリーン音声 30分〜2時間+書き起こし** | 参照数秒〜1分(zero/few-shot)、微調整なら数分〜 | 10分〜1時間(書き起こし不要) |
| 日本語品質 | ◎(日本語特化系譜・アクセント自然) | ○〜◎(少データで驚異的だが安定性に波) | 変換元の読み上げ品質に依存 |
| スタイル制御 | ◎(感情スタイルを名前で切替→character.yamlのstyleと直結) | △ | ×(声質のみ) |
| 推論速度 | ○(GPUでRTF<1、文単位なら体感良好) | △〜○ | ◎(軽量) |
| 実装統合 | ◎ Python API/サーバー化容易=`tts/sbv2.py` | ○ =`tts/gpt_sovits.py` | パイプライン段として(TTS→RVC直列) |
| 位置づけ | **本命。**データが集められるならこれ | データが数分しかない時の**先行検証・つなぎ** | 「自分の声で喋って変換」等の**遊び幅・補完** |

**選定フロー:** 集められた音声データ量で決める——(a)数秒〜数分:GPT-SoVITSで検証→(b)30分以上をクリーン化できた:SBV2本学習→(c)スタイル演技が必要:SBV2のスタイル別データ追加。

### 18.3 学習パイプライン(training/voice_tts/・SBV2想定)

```
① 収集   対象キャラの音声を適法に入手(自己所有メディア等・§19)
② 前処理 preprocess.py:
          ボーカル/BGM分離(音源分離) → 無音・ノイズ区間除去
          → 発話単位分割(2〜12秒) → ラウドネス正規化
③ 書起し faster-whisperで自動書き起こし → 人手修正(品質の分水嶺・妥協しない)
④ 学習   SBV2学習スクリプト(VRAM 12GB目安・数時間〜)
          スタイル分類(平静/喜び/怒り等)はデータにスタイルラベルを付与
⑤ 評価   固定20文の合成→主観5段階(自然さ/声の類似/キャラらしさ)を記録
⑥ 書出し Pack の voice/model/ へ配置 → character.yaml の style名を同期
```

- 手順・ハイパラ・データ構成は`training/voice_tts/notes.md`に必ず記録(再現性・§19.4の台帳を兼ねる)
- **品質が出ない時の切り分け:** 声が似ない→データの声質純度(分離品質)/棒読み→データの感情多様性不足/ノイズ→前処理見直し。**モデルより先にデータを疑う**

### 18.4 リアルタイム統合(CH-06)— レイテンシ予算

音声対話の体感は「合計待ち時間」で決まる。**発話終了→再生開始 2.5秒以内**を次の予算配分で達成する:

```
VAD終端検出   0.3s ┐
STT(small)    0.6s │ 逐次実行だが、
LLM TTFT      1.0s │ LLMは全文完了を待たず——
初文TTS合成    0.6s ┘ 「最初の文」が閉じた時点で合成開始
──────────────────
体感開始      ≈2.5s   以降は 合成と再生を文単位パイプライン化
```

- **文単位ストリーミング:** LLMトークン列を文境界(。!?)でチャンク化→`audio_chunk`イベントで順次配信→UI側キュー再生。文体検査(§17.5)も同じ境界で実施
- **barge-in(割込):** 再生中のユーザー発話検出で再生停止+生成キャンセル(WSに`cancel`)
- **長文の扱い:** ツール実行を伴う長応答は「まず一言(『調べるわね』等=examples.jsonlの報告場面)を即発話→結果は要約して発話+詳細はテキスト」。音声UXとして全文読み上げを既定にしない

## 19. 権利・倫理ガイドライン(本拡張の前提条件)

> 本節は法的助言ではなく、本プロジェクトが自らに課す運用方針である。

### 19.1 基本方針

| # | 方針 |
|---|---|
| 1 | **私的利用限定:** 学習型で再現したキャラクター口調・音声は、自分のPC上での私的な利用に限る。生成音声の公開・配信・共有は行わない |
| 2 | **配布分離:** Character Pack(persona・examples・音声モデル・LoRA)は、アプリ本体の配布物(S2〜S4)およびリポジトリ(S3)に**含めない**。§19.3の技術的措置で担保 |
| 3 | **適法入手:** 学習データは自己が適法にアクセスできる音源・テキストのみを用い、出所を台帳(§19.4)に記録する |
| 4 | **人格への配慮:** 声は声優という実在の人物に帰属する。実在人物の声の再現は、なりすまし・本人や第三者を害する用途に絶対に用いない |
| 5 | **公開したくなったら:** 利用規約上それが許諾された音声(例:規約に基づくVOICEVOX/AivisSpeech話者、公開許諾コーパス由来モデル)へ差し替える。学習型再現モデルのまま公開はしない |

### 19.2 アプローチ別の扱い

| アプローチ | 私的利用 | 配布・公開 |
|---|---|---|
| A: 既製音声(VOICEVOX等) | ○(各話者規約に従う) | 話者規約の範囲で可(クレジット等) |
| B: 学習型(SBV2/GPT-SoVITS/RVC) | ○(本方針の枠内) | **不可(本プロジェクトの方針として)** |

### 19.3 技術的措置(方針をコードで担保)

- `characters/` と `training/` の成果物は**配布ビルドの収集対象パスから構造的に除外**(ビルドスクリプトで白リスト方式=「含めるものを列挙」し、うっかり同梱を原理的に防ぐ)
- リポジトリは`.gitignore`で`characters/`相当・音声データ・学習成果物を除外。S3公開前チェックリストに「Pack混入なし」を追加
- Packの`character.yaml`に`distribution: private`フィールドを必須化し、将来もし共有可能Pack(規約許諾音声のみ使用)を作る場合と明示的に区別

### 19.4 データ台帳

Packごとに`notes`(character.yaml)+`training/*/notes.md`へ、**何を・どこから・いつ・どう使ったか**を記録する。将来の自分が「これは公開して良いものか」を判断できる状態を維持する。

## 20. リスク管理(拡張分)

| リスク | 影響 | 対策 |
|---|---|---|
| 口調LoRAで業務能力劣化 | ツール誤実行増 | FC evalを採用ゲート化(§17.4)・層別防御で LoRA単独依存を回避 |
| 音声データ品質不足 | 声が似ない・棒読み | §18.3の切り分け手順・GPT-SoVITSで先行検証してから本学習 |
| VRAM競合(LLM+TTS同時常駐) | 応答劣化 | 自己診断でVRAM実測→TTSのCPU推論フォールバック/モデル量子化調整 |
| キャラ演技が安全機構を曖昧化 | 承認の見落とし | persona.mdに業務整合節を必須化(§17.2)・承認UIはキャラ非依存の定型表示 |
| Pack混入事故(配布物へ) | 権利問題 | 白リスト式ビルド+公開前チェックリスト(§19.3) |
| 拡張に熱中し本編停滞 | 実用性未完 | Track分離(§11)・X2以降はPhase 4完了を前提条件化 |

## 21. 成功指標(拡張分)

| Track | 指標 | 目標 |
|---|---|---|
| X1 | 文体遵守率 / 人格一貫性 | 95%以上 / judge平均4.0以上 |
| X2 | 音声主観評価(自然さ・類似・らしさ) | 各4.0/5以上(固定20文) |
| X2 | 業務能力維持(Lv3時) | FC eval低下 -3pt以内 |
| X3 | 音声応答レイテンシ | 発話終了→再生開始 2.5秒以内 |
| 総合 | 「キャラモードのまま日常業務を任せられる」 | キャラモードでの日次利用が汎用モードを上回る |

---
---

# 付録

## 付録A: ADR運用

`docs/adr/`に1判断1ファイル(背景/選択肢/決定/トレードオフ/再検討条件)。初期起票:

- 0001 2プロセス構成(Tauri+Python sidecar)
- 0002 推論=Ollama(OpenAI互換統一)
- 0003 SQLite+sqlite-vec(pgvector移行条件付き)
- 0004 モデル選定(Phase 0計測結果添付)
- 0005 ライセンス選定(S3公開前)
- **0006 キャラボイスTTS選定(X2着手時・§18.2のフローで判断)**
- **0007 口調Lv3移行判断(X1の評価結果添付)**

## 付録B: 用語集

| 用語 | 定義 |
|---|---|
| S1〜S4 | 展開ステージ(Personal/Portable/Public/Product) |
| Phase / Track | 本編の実装段階 / キャラ拡張の実装段階(X0〜X3) |
| Character Pack | キャラ再現アセット一式を格納する規格化フォルダ(§16.2)。私的利用限定・配布物から除外 |
| 口調Lv1/2/3 | プロンプト/+few-shot・RAG・文体検査/+LoRA の3段階戦略(§17.1) |
| 文体検査 | 生成文の一人称・語尾・禁止語を機械検査し矯正する仕組み(§17.5) |
| 口調RAG | 場面付きセリフ集(examples.jsonl)をベクトル検索してプロンプトへ注入する仕組み(§17.3) |
| SBV2 | Style-Bert-VITS2。日本語に強い学習型TTS。キャラボイスの第一候補(§18.2) |
| barge-in | 音声再生中のユーザー発話による割込(再生停止+生成キャンセル)(§18.4) |
| 承認ゲート | 破壊的操作の実行前確認。LLM・キャラ演技の外側で機械的に適用される |
| sidecar | Tauriが同梱・起動管理する外部バイナリ(PyInstaller化したコア) |
| ポート&アダプタ | 差し替え対象を抽象+実装に分離する構成(推論/DB/TTSに適用) |
