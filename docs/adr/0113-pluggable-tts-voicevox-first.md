# 0113. TTS はコアの差し込み口(アダプタ)にし、まず VOICEVOX ENGINE(HTTP)で鳴らす

- 状態: Accepted
- 日付: 2026-11-23
- 関連: ADR 0108(既製話者を既定)、ADR 0109(three-vrm)、仕様書 §7(audio_chunk)・§18.4(文単位TTS)、ロードマップ「VOICEVOX で声を出す+口パク」

## 背景
エヴァに声を付ける。作者の決定(2026-11-23):今は TTS の差し込み口を作って VOICEVOX で試し、将来は Style-Bert-VITS2 か、その時点で最有力の音声システムに替える。
GPU は RTX 4060 Ti 8GB で Gemma 4 E4B が使うので、TTS は CPU で動くものがよい。口パクはエンジンが替わっても作り直さずに済むようにしたい。

## 選択肢
| 案 | 長所 | 短所 |
|---|---|---|
| VOICEVOX ENGINE(アプリ/エンジンを別に起動し HTTP で呼ぶ) | コアに依存が増えない(httpx のみ)。VOICEVOX アプリで声を聞き比べられる。CPU 版がある | 利用者が VOICEVOX を入れて起動しておく必要がある |
| VOICEVOX CORE を sidecar に同梱 | 別アプリ不要。配布版で完結 | wheel が PyPI に無く、ONNX Runtime・辞書・音声モデル(VVM)の取得と規約同意の仕組みが要る。PyInstaller 同梱の検証が重い |
| Windows 標準音声(SAPI) | 追加インストール不要 | 声が機械的。母音の情報が無い |

## 決定
- コアに `sentinel_core/tts/` を作り、エンジンは `TTSEngine`(`base.py`)の形を満たせば差し替えられるようにする。選ぶのは config の `voice.engine`(`factory.py`)
- 最初のエンジンは **VOICEVOX ENGINE の HTTP API**(`voicevox.py`)。CORE 同梱は、声と口パクの体験が固まってから別 PR で足す(同じ `TTSEngine` の形にするだけで、画面側は変えない)
- エンジンは「WAV」と、分かるなら「母音と時刻の列(viseme)」を返す。口パクはこの列だけを見る。母音を返さないエンジン(SAPI など)は `visemes=null` を返し、画面が文字から推測する
- 返答は文ごとに合成し、WS の `audio_chunk` で送る(仕様 §7 の型に `session_id`・`turn`・`text`・`duration`・`visemes` を追加。追加のみなので互換)
- 音を鳴らすのはチャット窓。アバター窓には Tauri の窓間イベントで口パクだけを渡す(アバター窓にコアへの接続権限を持たせない、ADR 0109 の方針を保つ)
- 声のオン/オフとキャラごとの声は画面で選び、コアの kv に保存する。既定はオフ

## 結果
- 利用者は VOICEVOX を起動しておく必要がある(繋がらないときは1ターンに1回だけ通知し、文字の会話は続く)
- 音声モデル・辞書はリポジトリにも配布物にも入らない(VOICEVOX 側が持つ)
- 声ごとに利用規約とクレジット表記(`VOICEVOX:キャラ名`)が違う。設定画面にクレジットを出し、公開前に規約を確認する運用にする
- Style-Bert-VITS2 などへの切り替えは `tts/` にエンジンを1つ足し、`factory.py` に1行足す作業になる
- 追記(2026-11-24): CORE 同梱は ADR 0115 で行った。ENGINE(HTTP)は `voice.engine: voicevox` で引き続き使える
