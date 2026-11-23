# 06 エヴァに声を付ける:TTS の差し込み口と、音に合わせた口パク

## 一言で

コアに **TTS の差し込み口**(`core/sentinel_core/tts/`)を作り、最初のエンジンとして **VOICEVOX** をつないだ。
LLM の返答を**文ごと**に合成して画面へ送り、チャット窓が鳴らすのと同時に、アバター窓へ**母音と時刻の列**を渡して口を動かす。

## 背景

- 決めたこと(2026-11-23):今は差し込み口を作って VOICEVOX で試す。将来は Style-Bert-VITS2 か、その時点で一番よい音声システムに替える(ADR 0113)
- だから「VOICEVOX 専用の作り」にすると、替えるときに口パクまで作り直しになる。**エンジンが返すもの**と**口パクが受け取るもの**の形を先に決めた
- GPU(8GB)は Gemma が使う。VOICEVOX は CPU で動くので取り合わない
- 返答を全部待ってから読むと、話し始めが遅い(仕様 §18.4 の目標は「口が開くまで 2.5 秒」)

## しくみ

```
LLM のトークン ──► ChatService ──► token イベント(文字)
                      │ feed()
                      ▼
                 SentenceSplitter(。!?で切る、ト書き（…）や絵文字は読まない)
                      │ 1文
                      ▼
                 SpeechService の列 ──► 作業タスクが1文ずつ合成
                                         │ TTSEngine.synthesize()
                                         ▼
                                   VOICEVOX ENGINE(http://127.0.0.1:50021)
                                     1. /audio_query  拍ごとの母音と長さ
                                     2. /synthesis    WAV
                                         │
                      audio_chunk イベント(WAV を base64 + visemes)
                                         ▼
チャット窓 VoicePlayer ── Web Audio で前の文の終わりに続けて予約再生
            │ 鳴り始めに
            ▼ emitTo("avatar", "avatar://lipsync")   (ブラウザでは BroadcastChannel)
アバター窓 AvatarStage.speakTimeline() ── 毎フレーム「いまの母音」を引いて口を動かす
```

1. **差し込み口**(`tts/base.py`):エンジンは `is_available` / `speakers` / `synthesize` / `aclose` を持てばよい。`synthesize` は `Speech(wav, duration, visemes)` を返す
   - `visemes` は `[母音, 開始秒, 終了秒]` の列。母音が分からないエンジンは `None` を返し、アバター側が文字から推測する(`lipsync.ts` の `fitText`)
   - どのエンジンを使うかは config の `voice.engine`(`tts/factory.py`)。新しいエンジンはここに1行足す
2. **VOICEVOX**(`tts/voicevox.py`):合成は2段階。1 で得た音声クエリの `accent_phrases[].moras[]` に、拍ごとの `vowel`(a/i/u/e/o/N/cl)と `consonant_length` + `vowel_length`(秒)が入っている
   - これを順に足して口のタイムラインにする(`visemes_from_query`)。子音の間もその拍の母音の口にする(子音で口を閉じるとパクパクしすぎる)
   - 長さは `speedScale` で割る(速く話すほど短い)。読点の間(`pause_mora`)は口を閉じる
   - 無声化した母音は大文字(`I` など)で来るので小文字にそろえる
3. **文で切る**(`tts/sentences.py`):「。」が来ても、次の文字が来るまで確定しない(`」` が続くかもしれないから)。80 文字を超えたら読点で切る
4. **列と作業タスク**(`tts/service.py`):合成は1本のタスクが順番に行う(順番が入れ替わらない)
   - ターンごとに番号(`turn`)を振る。新しいターンが始まったら、古いターンの未合成の文は捨てる
   - VOICEVOX に繋がらないときは、そのターンで1回だけ通知を出す。文字の会話は止めない
5. **鳴らす**(`app/src/features/voice/voicePlayer.ts`):`<audio>` を1つずつ鳴らすと文の継ぎ目で途切れるので、Web Audio の `AudioBufferSourceNode.start(時刻)` で「前の文の終わり」に次を予約する
   - デコードは非同期なので、Promise を1本につないで届いた順に処理する
   - こちらが話しかけたら(`send`)、キャラを替えたら、声をオフにしたら `stop()`
6. **窓をまたぐ**(`lipsyncChannel.ts`):音はチャット窓が鳴らし、アバター窓には口の形だけを送る。アバター窓にコアのトークンを渡さずに済む(ADR 0109)
7. **設定**:オン/オフとキャラごとの声はコアの kv(`voice.enabled`、`voice.speaker.<キャラID>`)に保存。声の優先順は「画面で選んだ声 > Pack の `voice.speaker_id` > config の `voice.speaker_id` > エンジンの最初の声」

## やってみる

```powershell
# 1. VOICEVOX を入れて起動する(https://voicevox.hiroshiba.jp/ 。CPU 版で十分)
#    起動している間、http://127.0.0.1:50021 で待ち受ける
# 2. SENTINEL を起動
cd app
npm run tauri dev
# 3. 右上の歯車 → 「声」 → 「返事を声で読み上げる」をオン → 声を選んで「試聴」
```

- 画面上部の `VOICE ON / OFF` を押してもオン/オフできる。黄色の `NO ENGINE` は「オンだが VOICEVOX に繋がらない」
- コアだけで試すなら:`Invoke-RestMethod http://127.0.0.1:8765/v1/voice -Headers @{"X-Sentinel-Token"="dev-token"}`(dev モード)
- Pack の `character.yaml` の `voice.speed` / `voice.pitch` で話す速さ・高さを変えられる(落ち着いた声なら speed 0.95 前後)

## 声の規約

- VOICEVOX はソフトの規約に加えて、**キャラ(話者)ごとに規約がある**。生成した音声を公開・配信するときは `VOICEVOX:キャラ名` のクレジットが要る。設定画面に表記を出している
- 手元で聞くだけ(私的利用)なら公開に当たらない。録音して動画などに使う前に、そのキャラの規約ページを読む
- 音声モデル・辞書は VOICEVOX 側が持つので、リポジトリにも SENTINEL の配布物にも入らない

## ハマりどころ

- **AudioContext は勝手に鳴らせない**:ブラウザは「利用者の操作の後」でないと音を出さない(自動再生の制限)。起動直後の挨拶が鳴らないことがある。最初のクリックかキー入力で `resume()` するようにした
- **eslint の `set-state-in-effect`**:`useEffect(() => void refresh(), …)` は「effect の中で直接 setState」と見なされて落ちた。effect の中で fetch して、`.then` の中で setState する形にした
- **mypy の `no-any-return`**:`wave` の戻り値の型が緩く、`float` を返す関数で落ちた。`float()` で包んだ

## 確認問題

1. エンジンを Style-Bert-VITS2 に替えるとき、触るファイルはどこか。画面側は変える必要があるか
2. VOICEVOX の拍の長さを `speedScale` で割るのはなぜか
3. 音をアバター窓ではなくチャット窓で鳴らしているのはなぜか
4. 返事の途中でこちらが話しかけたら、コアと画面はそれぞれ何をするか
