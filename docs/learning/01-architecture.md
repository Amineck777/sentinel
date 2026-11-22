# 01 全体像:2つのプロセスが握手して動く

## 一言で

SENTINEL は **Python のコア(頭脳)** と **Tauri のシェル(身体)** の2プロセスでできています。
シェルがコアを起動し、コアが「準備できた、ここにいる」と1行で知らせ(handshake)、
画面はそのポートとトークンを使って HTTP と WebSocket でコアと話します。

## 背景:なぜ2プロセスなのか

- LLM・記憶・人格の処理は Python のエコシステム(FastAPI、Ollama 連携、将来の Pydantic AI)が強い
- 透明な窓、トレイ常駐、グローバルホットキーはネイティブ側(Rust/Tauri)が得意
- 分けておくと、**コアだけを将来の自宅サーバーへ引っ越せる**(ロードマップ 2027 Q3)。画面は接続先を変えるだけ

## しくみ

```
┌──────────── Tauri シェル(Rust) ────────────┐
│ main.rs   : トレイ、ホットキー、窓            │
│ sidecar.rs: コアを起動し handshake を待つ      │──起動──┐
│                                               │         ▼
│  ┌──── 画面(React / WebView) ────┐         │   ┌──── コア(Python / FastAPI) ────┐
│  │ get_core_info → port, token     │◀─ invoke │   │ __main__.py: handshake を出力    │
│  │ fetch  /v1/chat   (HTTP)        │──────────┼──▶│ api/http/   : 受付(薄い)         │
│  │ WS     /v1/stream (token 付き)  │◀─────────┼───│ agent/      : 会話ターンの生成     │
│  └─────────────────────────────────┘         │   │ events.py   : 文字を WS へ放送     │
└──────────────────────────────────────────────┘   │ memory/     : SQLite に保存         │
                                                     │ character/  : Character Pack        │
                                                     └─────────────────────────────────────┘
```

1回の会話の流れ:

1. 画面が `POST /v1/chat` を送る。コアは発話を保存し、**すぐに** `session_id` を返す(`agent/service.py` の `start_turn`)
2. 生成はバックグラウンドで進み、1文字ずつ `token` イベントとして EventHub → WebSocket で画面に届く
3. 生成が終わったら `message_done`。失敗したら `notice`(警告)

「すぐ返して、中身は後から流す」のは、LLM の応答に数秒〜数十秒かかっても画面を固めないためです。

## 起動の握手(handshake)

- 配布版では、Tauri がコアを **managed モード**で起動する。ポートは空いている番号、トークンは毎回ランダム
- コアは uvicorn が実際に待ち受けを始めてから `SENTINEL_HANDSHAKE {"port":…, "token":…}` を出す(`core/sentinel_core/__main__.py` の `_serve_with_handshake`)。早すぎると画面の最初の接続が失敗するため
- Tauri はこの行を読んで `get_core_info` で画面に渡す(`app/src-tauri/src/sidecar.rs`)
- Tauri が終了すると、コアの標準入力が閉じる(EOF)。コアはそれを見て自分で終了する。**孤児プロセスを残さない**ための工夫

開発中(`tauri dev`)は sidecar を起動せず、手で起動した dev モードのコア(8765 / dev-token)へつなぎます(ノート 02 の B2)。

## やってみる

```powershell
# ターミナル1: コアを dev モードで起動
python scripts/dev.py
# ターミナル2: 生のAPIを叩く
curl -H "X-Sentinel-Token: dev-token" http://127.0.0.1:8765/v1/system/health
```

## ハマりどころ

- トークンは HTTP ではヘッダ `X-Sentinel-Token`、WebSocket では URL の `?token=`(ブラウザの WS はヘッダを付けられないため)。だから URL がログに出るとトークンが漏れる(ノート 02 の B4)
- コアの同期 SQLite はイベントループ上で動いている。今は軽いので問題ないが、記憶検索が重くなったら非同期化する(実装方針 §7.2-4)

## 確認問題

1. `POST /v1/chat` が生成完了を待たずに返るのはなぜ?
2. handshake を「待ち受け開始の後」に出さないと何が起きる?
3. Tauri が強制終了されたとき、コアはどうやって自分も終わる?
