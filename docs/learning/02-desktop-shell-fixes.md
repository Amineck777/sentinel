# 02 デスクトップアプリが動かなかった理由(B1〜B5)

2026-11-22 の調査で、Python 側のテストは全部通っていたのに、**デスクトップアプリとしては一度も動いたことがなかった**と分かりました。
「テストが通る」と「製品として動く」は別物、というのがこのノートの一番の学びです。修正は PR #1。

---

## B1:配布版だけ画面がコアにつながらない(CORS)

**一言で:** 画面(`http://tauri.localhost`)とコア(`http://127.0.0.1:xxxx`)は「別のサイト」扱いなので、コアが許可を返さないとブラウザが通信を止める。

**しくみ:**
- ブラウザは、別 origin への「普通でない」リクエスト(独自ヘッダ `X-Sentinel-Token` 付きなど)の前に、**OPTIONS で事前確認(プリフライト)** を送る
- サーバーが `Access-Control-Allow-Origin` などを返さないと、本番のリクエストは送られない
- 以前は「CORS は dev のみ」という方針で、managed モードでは CORS ミドルウェア自体を付けていなかった → OPTIONS が 405 → 接続不可
- 修正:Tauri の origin(`http://tauri.localhost`、`https://tauri.localhost`、`tauri://localhost`)だけを常に許可(`core/sentinel_core/api/app.py` の `allowed_origins`)

**やってみる:**
```bash
curl -i -X OPTIONS http://127.0.0.1:8765/v1/chat \
  -H "Origin: http://tauri.localhost" -H "Access-Control-Request-Method: POST"
# 200 と access-control-allow-origin が返れば OK。Origin を http://evil.example にすると拒否される
```

**ハマりどころ:** origin は OS で違う(Windows は `http://tauri.localhost`、macOS/Linux は `tauri://localhost`)。

---

## B2:`tauri dev` で10秒後にタイムアウト

**一言で:** Rust の `#[cfg(debug_assertions)]` で debug と release の動きを分けていたのに、片方の道が行き止まりだった。

- release:sidecar を起動 → handshake の値を `get_core_info` が返す
- debug:sidecar を起動しない → `get_core_info` が返す値が無い → 画面が待ち続けてタイムアウト
- 修正:debug では dev コアの固定値(8765 / dev-token)を返す(`app/src-tauri/src/sidecar.rs` の `dev_core_info`)

あわせて見つかったこと:
- **B2b** `tauri.conf.json` の `externalBin`(同梱する sidecar)が基本設定にあり、sidecar を作っていないと dev ビルドまで失敗した → 配布用の `tauri.bundle.conf.json` に分けて `npm run tauri:bundle` だけで重ねる
- **B2c** Rust のコードがそもそもコンパイルできなかった(エラー型の変換漏れ、`Mutex` のロックが変数より長生きする問題)。**CI で一度もビルドしていなかった**のが根本原因 → Windows で clippy を回す CI ジョブを追加

---

## B3:ホットキーを押すと開いてすぐ閉じる

**一言で:** グローバルショートカットのコールバックは「押した」と「離した」の**2回**呼ばれる。両方で表示を切り替えると、開いて閉じる。

- 修正:`event.state() == ShortcutState::Pressed` のときだけ切り替え(`app/src-tauri/src/main.rs` の `register_hotkey`)
- ついでに既定キーを Alt+Space → **Ctrl+Shift+Space** へ。Alt+Space は Windows のウィンドウメニュー、Ctrl+Space は日本語 IME の切替と衝突する
- 他のアプリが使っていて登録できなくても、アプリは起動を続ける(トレイから使える)

**学び:** ライブラリのイベントが「何回・どの状態で」来るかは、README とソースで確かめる。

---

## B4:トークンがログに出る

- uvicorn は WebSocket の接続を `"WebSocket /v1/stream?token=..."` と記録する。URL にトークンがある(ノート 01 参照)ので、そのまま漏れる
- 修正:uvicorn のロガーに、`token=` の後ろを `***` に置き換えるフィルタを付けた(`core/sentinel_core/logging_setup.py`)

**学び:** 秘密は「出力する側」で消す。読む側で気をつけるのは無理。

---

## B5:Windows でビルドできない(アイコン)

- Windows のインストーラには `icon.ico` が必要。32×32 の png しかなかった
- 修正:`npx tauri icon app-icon.png` で一式を生成

---

## Windows 実機で踏んだこと(ドキュメントに無い落とし穴)

| 症状 | 原因 | 対処 |
|---|---|---|
| `py -3.12` で「No suitable Python runtime found」 | 入っているのは 3.13 だけ | `py -3.13` を使う。`py --list` で確認 |
| `Activate.ps1` が「スクリプトの実行が無効」 | PowerShell の実行ポリシー | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`(自分のユーザーだけ) |
| `tauri build` が「version mismatched Tauri packages」 | Rust の `tauri` 2.12 と npm の `@tauri-apps/api` 2.11 | 同じ minor に揃える。Tauri は Rust crate と npm パッケージを **ペアで** 上げる |
| `npm run tauri build -- --config x` で `--config` が消える | PowerShell の npm は `--` を取り除く | 引数ごと npm script にする(`npm run tauri:bundle`) |
| CI の Windows だけ日本語の print で落ちる | パイプ出力の文字コードが cp1252 | スクリプトの先頭で `sys.stdout.reconfigure(encoding="utf-8")` |

## 確認問題

1. CORS のプリフライトはどんなときに送られる? 405 が返ると何が起きる?
2. `#[cfg(debug_assertions)]` で処理を分けるとき、気をつけることは?
3. ホットキーのコールバックが2回呼ばれるのはなぜ?
4. Tauri をバージョンアップするときに、一緒に上げる必要があるものは?
