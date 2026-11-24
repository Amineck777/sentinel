# 08 VOICEVOX をアプリに同梱する:ENGINE から CORE へ

## 一言で

VOICEVOX の**音声合成の中身(VOICEVOX CORE)**を Python ライブラリとしてコアの中で動かすようにした。
セットアップを1回すれば、VOICEVOX アプリを起動しなくてもエヴァが話す。アプリ(ENGINE)を使う道も残してある。

## 背景

- 06 では、別に起動した VOICEVOX アプリに HTTP で「この文を読んで」と頼んでいた。アプリを起動し忘れると声が出ない
- GPU(8GB)は Gemma が使うので、TTS は CPU で動かしたい。CORE は CPU を明示して動かせる
- SENTINEL は自分の PC で使うだけ(配布しない)。それでも音声モデルや DLL を git に入れないのは同じ(規約と容量のため)

## ENGINE と CORE のちがい

| | VOICEVOX ENGINE(06) | VOICEVOX CORE(今回) |
|---|---|---|
| 正体 | 合成サーバー(VOICEVOX アプリが中で起動する) | 合成ライブラリ(ENGINE の中身そのもの) |
| 呼び方 | HTTP `POST /audio_query` → `POST /synthesis` | Python `create_audio_query()` → `synthesis()` |
| 起動 | アプリを起動しておく | コアが自分で読み込む |
| ファイル | アプリが全部持っている | ONNX Runtime・辞書・音声モデル(.vvm)を自分で取ってくる |
| コード | `tts/voicevox.py` | `tts/voicevox_core_engine.py` |

どちらも「音声クエリ(拍ごとの母音と長さ)を作る → WAV にする」という同じ2段階なので、
口パクの作り方(`visemes_from_query`)はそのまま使い回せる。CORE の音声クエリは Python のデータクラスで
名前の書き方(`speed_scale` と `speedScale`)が違うだけなので、`query_to_engine_dict()` で詰め替えている。

## しくみ

```
scripts/setup_voicevox_core.py(1回だけ)
  1. pip install voicevox_core-0.17.0-cp310-abi3-win_amd64.whl  ← GitHub Releases から(PyPI に無い)
  2. download-windows-x64.exe --exclude c-api --devices cpu --models-pattern 24.vvm
       └ 利用規約の画面 → 自分で y
  3. 試しに1文合成して test.wav

%LOCALAPPDATA%\sentinel\sentinel\voicevox_core\   ← git の外({APP_DATA}/sentinel/voicevox_core)
  onnxruntime\lib\voicevox_onnxruntime.dll   推論ランタイム(ニューラルネットを動かす部品)
  dict\open_jtalk_dic_utf_8-1.11\            辞書(漢字の読みとアクセント)
  models\vvms\24.vvm                         音声モデル(暁記ミタマ 122〜125 が入っている)

コアの起動時(tts/factory.py)
  voice.engine = auto
    ├ voicevox_core パッケージがあり .vvm もある → VoicevoxCoreEngine
    └ 無い → VoicevoxEngine(HTTP、今まで通り)
```

`VoicevoxCoreEngine` の中(`tts/voicevox_core_engine.py`):

1. **遅延初期化**(`_ensure`):最初に使われたときに import → ONNX Runtime → 辞書 → .vvm を開く。
   パッケージが無くてもコア自体は起動できる。失敗したら文面を覚えておき、10 秒は試し直さない(設定画面が何度も状態を聞いてくるため)
2. **.vvm は開くだけ**:開くと中のメタ情報(話者名・スタイル ID)が読める。ここで「スタイル ID → どの .vvm か」の表を作る
3. **読み込みは話すときに**(`_load_for`):モデル本体の読み込みは数秒かかり、メモリも使う。使う声の .vvm だけを1回だけ読み込む
4. **既定の声は先に**:config の `speaker_id`(122)の .vvm だけは、準備が済んだ直後に裏のタスクで読み込み始める。最初の返事で待たされにくい
5. **CPU 固定**:`Synthesizer(..., acceleration_mode="CPU")`。AUTO にすると GPU を使おうとして LLM と VRAM を取り合うかもしれない

## やってみる

PowerShell で、リポジトリ直下(`C:\Myself_Project\AI_Assistant`)から1行ずつ:

```powershell
cd C:\Myself_Project\AI_Assistant
```

```powershell
core\.venv\Scripts\python.exe scripts\setup_voicevox_core.py
```

途中で規約が出たら読んで `q`、同意するなら `y` と Enter。最後に `OK: … test.wav に書き出しました` と出れば成功。

```powershell
start $env:LOCALAPPDATA\sentinel\sentinel\voicevox_core\test.wav
```

あとはいつも通り起動して、歯車 → 声 の「エンジン」が「VOICEVOX CORE 同梱版(アプリ不要)」になっていれば CORE で鳴っている。

- ほかの声も入れたいとき:`--all-models`(全部で 1GB 以上)か `--models 0.vvm`(ずんだもん等)
- アプリで鳴らしたいとき:`%LOCALAPPDATA%\sentinel\sentinel\config.yaml` に `voice:` → `engine: voicevox`

## ハマりどころ

- **wheel が pip で見つからない**:`pip install voicevox_core` は PyPI に無いので失敗する。GitHub Releases の .whl を URL かファイルで指定する。ファイル名の `cp310-abi3` は「Python 3.10 以上ならどれでも使える」という意味なので、3.13 でも入る
- **規約の画面で固まったように見える**:ダウンローダーはページャー(上下キーで読む画面)を出す。`q` で抜けると同意の質問が出る
- **ENGINE と CORE で話者 ID は同じか**:同じ。122 はどちらでも暁記ミタマ(ノーマル)。どの ID がどの .vvm に入っているかは voicevox_vvm の README の対応表にある
- **セットアップしたのに切り替わらない**:`auto` の判定はコアの起動時だけ。コア(`scripts\dev.py`)を再起動する。`config.yaml` に `engine: voicevox` と書いてあるとそちらが優先される
- **配布用の実行ファイル**:`importlib` で実行時に import しているので、PyInstaller は自動では見つけない。`scripts/build_sidecar.py` が `--collect-all voicevox_core` を足す(未確認:Windows の sidecar ビルドで CORE が鳴るかはまだ試していない)

## 確認問題

1. ENGINE と CORE は、それぞれ何をどう呼んで音声を作っているか
2. .vvm を「開く」ことと「読み込む」ことは何が違い、なぜ分けているか
3. `voice.engine: auto` は、いつ・何を見て CORE か ENGINE かを決めるか
4. 音声モデルの利用規約への同意を、セットアップスクリプトが自動で答えないのはなぜか
5. なぜ `acceleration_mode` を AUTO ではなく CPU にしているか
