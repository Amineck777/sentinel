# 03 記憶の土台:10年分の会話を汚さず・失わない

2027年1月から、会話を長期の一次記録として貯め始めます(ロードマップ §5)。
その前に入れた仕組みのノートです。修正は PR #2。

---

## DB の版管理(マイグレーション)

**一言で:** DB に「今どの版の形か」を記録し、アプリが起動するたびに足りない版の変更だけを順番に当てる。

**背景:** 10年使えば、テーブルの形は何度も変わります。版の記録がないと「この DB に何が適用済みか」が分からず、移行で記録を壊します。

**しくみ:**(`core/sentinel_core/memory/store.py`)

- SQLite には `PRAGMA user_version` という、自由に使える整数が1つある。ここに「適用済みの版」を入れる
- `MIGRATIONS = [版1のSQL, 版2のSQL, ...]`。**新しい版は末尾に足すだけ。既存の項目は書き換えない**(書き換えると、すでに適用済みの DB と食い違う)
- 起動時:
  1. `user_version` を読む
  2. アプリより新しい版なら **開かずに止める**(古いアプリで新しい DB を触ると壊すため。`SchemaTooNewError`)
  3. 中身のある DB なら、移行の前に `sentinel.db.bak-v{旧版}` へ**丸ごと複製**
  4. 足りない版を1つずつ、**版ごとに1トランザクション**で適用。失敗したらその版は丸ごと取り消し

**やってみる:**
```powershell
# DB の場所は Windows なら %LOCALAPPDATA%\sentinel\sentinel\data\sentinel.db(platformdirs の規則)
python -c "import sqlite3,os;p=os.path.expandvars(r'%LOCALAPPDATA%\sentinel\sentinel\data\sentinel.db');print(sqlite3.connect(p).execute('PRAGMA user_version').fetchone())"
```

**ハマりどころ:**
- Python の `sqlite3` は、既定では自動でトランザクションを始める。移行で `BEGIN`/`COMMIT` を自分で書くときは `isolation_level=None`(自動にしない)の接続を使う
- 版管理を入れる前に作られた DB は `user_version = 0` だが中身はある。だから「版が0なら新規」とは判定せず、「テーブルがあるか」で退避するか決めている

---

## 何を「記憶」として保存するか

**一言で:** 保存するのは**モデルが実際に話した言葉だけ**。「サーバーにつながりません」のような案内文は、画面に出すが保存しない。

**背景:** 以前はオフライン応答も AI の発言として保存していました。すると次のターンで、LLM は自分が「接続できません」と言った履歴を読んでしまう。10年残す記録には混ぜたくないものです。

**しくみ:**
- LLM クライアントは、推論サーバーが使えないとき文字を返す代わりに `LLMUnavailableError` を投げる(`core/sentinel_core/llm/client.py`)
- `ChatService` はそれを受けて `notice`(警告)として画面へ出すだけ(`core/sentinel_core/agent/service.py`)
- 途中で切れた場合は、そこまでに生成された文だけを保存。何も生成されなければ AI の発言を作らない

**学び:** 「表示するもの」と「記録するもの」は別。例外(エラー)は、正常な値に紛れ込ませずに型で分けると扱いやすい。

---

## 設定の優先順位と、アプリが覚えておく状態

- 既定値の正は `settings.py` の `DEFAULTS`。`config/config.default.yaml` は人が読むための写しで、**テストで一致を検査**している(片方だけ変えると落ちる)。sidecar は1ファイルで配るので、外部の yaml に頼らない
- **設定ファイル(`config.yaml`)はユーザーが書くもの、DB の `kv` テーブルはアプリが書くもの**、と分けた。アプリが設定ファイルを書き換えると、ユーザーのコメントや書式を壊すため
- 起動時のキャラ:前回選んだもの(`kv`)> 設定の `character.active` > 汎用モード
- Pack を一時的に外しても選択は消さない。戻せば次の起動で復帰する

---

## 配布版の自動テスト(sidecar スモーク)

**一言で:** 実際に配る1ファイルのコアを CI で作って起動し、「握手して、応答して、親が消えたら終わる」ことを確かめる。

- PyInstaller で1ファイルにすると、動的に import されるモジュール(uvicorn の一部など)が漏れて、**配布版だけ起動しない**ことがある。単体テストでは見つからない
- `scripts/smoke_sidecar.py`:起動 → handshake → `/v1/system/health` → 標準入力を閉じて終了を確認
- CI の `sidecar` ジョブが Windows と Linux の両方で実行する

```powershell
python scripts/build_sidecar.py
python scripts/smoke_sidecar.py
```

## 確認問題

1. マイグレーションの既存の版を書き換えてはいけないのはなぜ?
2. アプリより新しい版の DB を開かないのはなぜ?
3. オフライン応答を保存すると、次のターンで何が起きる?
4. 設定ファイルと `kv` テーブルを分けた理由は?
5. 単体テストが全部通っているのに、配布版だけ起動しないのはどんなとき?
