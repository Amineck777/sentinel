# 0115. VOICEVOX CORE をコアに同梱し、アプリ無しで声を出す(ENGINE は選択肢として残す)

- 状態: Accepted
- 日付: 2026-11-24
- 関連: ADR 0113(TTS の差し込み口)、ADR 0108(既製話者を既定)、ADR 0110(配布の優先度を下げる)

## 背景
ADR 0113 では、まず VOICEVOX ENGINE(アプリ)に HTTP で頼む形で声を出した。動くことは Windows 実機で確かめたが、
毎回 VOICEVOX アプリを起動しておく必要がある。常駐アシスタントとしては、SENTINEL を起動するだけで声が出てほしい。
GPU(RTX 4060 Ti 8GB)は Gemma 4 E4B が使うので、TTS は CPU で動かしたい。
SENTINEL は作者個人の PC で使うだけで、配布はしない(ADR 0110)。

## 選択肢
| 案 | 長所 | 短所 |
|---|---|---|
| ENGINE のまま(アプリを起動しておく) | 追加作業なし | 毎回アプリの起動が要る。忘れると声が出ない |
| ENGINE(run.exe)をサイドカーとして SENTINEL が起動 | API はそのまま | 1GB 超の別プロセスを管理する(起動待ち・終了・ポート衝突) |
| **VOICEVOX CORE の Python ライブラリをコアの中で動かす** | 別プロセス無し。CPU 固定にできる。必要な音声モデルだけ入れられる | wheel が PyPI に無い。ONNX Runtime・辞書・.vvm を別に取ってくる必要がある |

## 決定
- `core/sentinel_core/tts/voicevox_core_engine.py` に `VoicevoxCoreEngine` を足す(`TTSEngine` の形はそのまま。画面と口パクは変えない)
  - `voicevox_core.asyncio` を使う。合成は必ず `acceleration_mode="CPU"`
  - パッケージの import とファイルの準備は初回に行う(遅延初期化)。無くてもコアは起動する
  - .vvm は開いて話者一覧だけ読み、モデルの読み込みはそのスタイルで初めて話すときに行う。既定の声(config の `speaker_id`)だけは準備直後に裏で読み込む
  - 口パクは CORE の `AudioQuery` を ENGINE の JSON と同じ形に詰め替え、既存の `visemes_from_query` を使い回す
- config の `voice.engine` に `auto`(新しい既定)と `voicevox_core` を足す。`auto` は「CORE のパッケージと .vvm があれば CORE、無ければ ENGINE(HTTP)」。判定はコアの起動時
- 置き場所は `{APP_DATA}/sentinel/voicevox_core/`(`voice.core.dir` で変更可)。中身は公式ダウンローダーが作る並び(`onnxruntime/`・`dict/`・`models/vvms/`)
- 取得は `scripts/setup_voicevox_core.py`(版は 0.17.0 に固定し、Windows の wheel とダウンローダーは SHA-256 を照合)。音声モデルの利用規約への同意は、ダウンローダーが出す画面で**利用者本人が行う**(スクリプトは代わりに答えない)
- 既定で入れるのはエヴァの声(暁記ミタマ 122〜125)が入った `24.vvm` だけ。`--all-models` で全部
- **音声モデル・ONNX Runtime・辞書・wheel は git に入れない**。`.gitignore` に加え、CI の検査で `.vvm` `.onnx` `.whl` `.dll` などが追跡されていたら落とす
- 配布用 sidecar を作るとき、voicevox_core が入っていれば PyInstaller に `--collect-all voicevox_core` を付ける(モデル等は同梱せず `{APP_DATA}` 側を読む)
- ENGINE(HTTP)のアダプタは残す。`voice.engine: voicevox` で今まで通り使え、VOICEVOX アプリで声を聞き比べる用途にも使える
- Windows SAPI のフォールバックは今回は作らない(CORE と ENGINE の2段で足りるため。必要になったら別 ADR)

## 結果
- セットアップ後は SENTINEL を起動するだけで声が出る。初回だけ、モデルの読み込みに数秒かかる
- 音声の生成元のクレジットは変わらず `VOICEVOX:暁記ミタマ`。録音・公開するときは表記し、暁記ミタマの規約(https://yogataritobari.studio.site/#rules)を確認する。CORE の音声モデル規約は、アプリへの組み込み・再配布を許しているが、本プロジェクトは配布しないのでその条項は使わない
- CORE の版を上げるときは、`setup_voicevox_core.py` の `VERSION` と SHA-256 を変え、Python API の差分(リリースノート)を確認する
- 声の数を増やすと .vvm を開く数が増え、起動後の初回準備が少し重くなる(モデルの読み込み自体は使う声の分だけ)
