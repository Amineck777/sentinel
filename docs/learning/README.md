# 学習ノート

個人開発で SENTINEL を育てながら、**自分で説明できるようになる**ための教材です。
仕様書(`docs/spec/`)や実装方針(`docs/implementation-policy.md`)は「何をどう作るか」を決める文書、
こちらは「なぜそうなっているか・何を学んだか」を残す文書です。

## 読む順番

| # | ノート | 内容 | 前提 |
|---|---|---|---|
| 01 | [全体像](01-architecture.md) | 2プロセス構成、起動の握手、イベントの流れ、どこに何があるか | なし |
| 02 | [デスクトップアプリが動かなかった理由](02-desktop-shell-fixes.md) | CORS、debug/release の違い、ホットキー、ログ、Windows ビルド | 01 |
| 03 | [記憶の土台](03-memory-foundation.md) | DB の版管理、何を保存するか、設定の優先順位、配布版の自動テスト | 01 |
| 04 | [アバターの試作](04-avatar-prototype.md) | three-vrm で VRM 表示、表情・瞬き・口パク、モデルの規約確認 | 01 |
| 05 | [主人格をチャットにつなぐ](05-connect-main-persona.md) | Modelfile の人格を活かす、思考オフ、私的 Pack、会話をモデル名つきで残す | 01, 03 |
| 06 | [エヴァに声を付ける](06-voice-and-lipsync.md) | TTS の差し込み口、VOICEVOX、文ごとの合成、音と口パクを窓をまたいで合わせる | 01, 04 |

## ノートの書き方(自分用ルール)

新しく学んだことがあったら `NN-題名.md` を足し、上の表に1行追加します。
Claude Code では `/learn-note` で下書きを作れます(`.claude/skills/learn-note/`)。

各ノートは次の形に揃えます。

1. **一言で:** 結論を1〜2文で
2. **背景:** なぜ必要か、何が困っていたか
3. **しくみ:** 図か手順で。コードは `ファイル:行` で指す(コピーしない。古くなるため)
4. **やってみる:** 手元で確かめるコマンド
5. **ハマりどころ:** 実際につまずいたこと
6. **確認問題:** 答えられなければ読み直す

## 用語集

| 用語 | 意味 |
|---|---|
| コア(core) | Python の FastAPI サーバー。頭脳の本体。`core/sentinel_core/` |
| シェル(shell) | Tauri(Rust)のデスクトップアプリ。窓・トレイ・ホットキー・コアの起動係。`app/src-tauri/` |
| sidecar | アプリに同梱して一緒に起動する別プログラム。ここでは PyInstaller で1ファイルにしたコア |
| handshake | コアが起動完了時に標準出力へ1行出す `SENTINEL_HANDSHAKE {...}`。ポートとトークンを伝える |
| dev / managed | コアの起動モード。dev は人が起動(固定ポート 8765)、managed は Tauri が起動(ポート・トークンが毎回変わる) |
| EventHub | コア内の放送係。生成中の文字を WebSocket で画面へ流す。`events.py` |
| Character Pack | キャラの人格・口調をまとめたフォルダ。置けば増え、消せば消える |
| ADR | Architecture Decision Record。設計判断を1件1ファイルで残す記録 |
| マイグレーション | DB の形(スキーマ)を版ごとに順番に変えていく手順 |
| VRM | 人型 3D アバターの形式。中身は glTF に骨・表情・視線・ライセンスを足したもの。0.x と 1.0 がある |
| three-vrm | pixiv 製の、three.js で VRM を扱うライブラリ。`@pixiv/three-vrm` |
| 正規化ボーン | モデルごとの骨の向きの違いを吸収した仮想の骨。同じ角度で同じ姿勢になる |
| Modelfile | Ollama のモデル定義。元のモデル(FROM)・パラメータ・人格(SYSTEM)を書く |
| 思考(thinking) | 返答の前にモデルが内側で考える段階。賢くなるが遅い。gemma4 などが持つ |
| ビゼム(viseme) | 口の形の単位。ここでは 5 母音(aa/ih/ou/ee/oh)と「閉じ」 |
| TTS | Text To Speech。文字から音声を作る。ここでは VOICEVOX。`core/sentinel_core/tts/` |
| モーラ(拍) | 日本語の音の長さの単位。「きゃ」「ん」「っ」もそれぞれ1拍。VOICEVOX は拍ごとの母音と長さを返す |
| 音声クエリ | VOICEVOX の合成の中間データ。読み・アクセント・拍ごとの長さが入った JSON |
