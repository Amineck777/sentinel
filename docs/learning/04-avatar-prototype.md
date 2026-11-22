# 04 アバターの試作:VRM を表示して、表情と口パクを付ける

ロードマップ v1.2 段階A(表示・表情・口パク)の試作ノートです。ブランチは `feat/avatar-prototype`。
ADR 0109(three-vrm で描く)の最初の一歩で、Tauri の透明窓に載せるのは次の段階です。

---

## 一言で

`three.js` が 3D の描画、`@pixiv/three-vrm` が「VRM という人型モデルの決まりごと」(骨・表情・視線)を受け持つ。
SENTINEL 側は毎フレーム「感情・瞬き・口の形の重み」を合成して `expressionManager.setValue()` に渡すだけ。

## 背景

- 以前は VTube Studio に描画を任せる案だったが、別アプリとトークン管理が要る。透明窓・クリック透過・表情を自前で握りたいので、three-vrm にした(ADR 0109)
- 本番の人格モデル(ミルティナ)の前に、無料配布モデルで「表示できる・表情が変わる・口が動く」を確かめる
- テストモデルは puppet end さんの無料配布「ぱぺこ」(下の「規約の確認」)。**モデルファイルはリポジトリに入れない**

## しくみ

```
avatar.html ─ src/avatar.tsx ─ AvatarApp.tsx(操作パネル, React)
                                   │ load / setEmotion / speak / attachAudio
                                   ▼
                            avatarStage.ts(three.js の舞台。毎フレーム動く)
                                   │ 文字 → 母音の並び
                                   ▼
                            lipsync.ts(three.js に依存しない純粋な関数)
```

1. **読み込み**(`AvatarStage.load`):`GLTFLoader` に `VRMLoaderPlugin` を登録して読むと、`gltf.userData.vrm` に VRM が入る
   - VRM は中身が glTF(3D の標準形式)で、そこに「骨の名前・表情・視線・ライセンス」を足した拡張
   - VRM 0.x のモデルは前後が逆向きなので `VRMUtils.rotateVRM0` で 1.0 と同じ向きに回す(1.0 なら何もしない)
   - 表情名も three-vrm が 1.0 の名前に読み替える(0.x の `a` → `aa`、`joy` → `happy`、`sorrow` → `sad`、`fun` → `relaxed`)
2. **姿勢**:読み込んだ直後は T ポーズ。`humanoid.getNormalizedBoneNode("leftUpperArm")` の回転で腕を下ろす
   - 「normalized(正規化)ボーン」はモデルごとの骨の向きの違いを吸収した仮想の骨。どのモデルでも同じ角度で同じ姿勢になる
3. **毎フレーム**(`AvatarStage.animate`):目標の重みを決めて、`approach()` で滑らかに近づける
   - 感情はゆっくり(速さ 8)、口は速く(25)、瞬きはもっと速く(60)
   - 速さに `dt`(前フレームからの秒数)を掛けるので、60fps でも 144fps でも同じ速さになる
   - 最後に `vrm.update(dt)` を呼ぶ。これを忘れると表情も揺れもの(髪の物理)も反映されない
4. **口パク(文字から)**(`lipsync.ts`):
   - `textToVisemes`:かな1拍ごとに母音(aa/ih/ou/ee/oh)に変える。「きゃ」の小さい字は前の拍の母音を上書き、「ん・っ」は口を閉じる、「ー」は前の母音を伸ばす
   - 漢字は読みが分からないので、1文字2拍の仮の母音を回して当てる(見た目が動けば十分な段階A用)
   - `buildTimeline` で拍に時刻を付け、`sampleTimeline` で「いまの母音と開き具合」を引く。拍の中央で最大になる山型にして、パタパタしすぎないようにした
5. **口パク(音声から)**:`AnalyserNode` で音声の波形を取り、RMS(音の大きさの平均)を口の開きにする。母音は分からないので「あ」だけ

## やってみる

```powershell
# 1. モデルの場所を教える(このファイルは .gitignore 済み。作者の PC には作成済み)
#    メモ帳で app\.env.local を作り、次の1行を書いて保存する
#    SENTINEL_AVATAR_VRM=C:/Users/harut/Downloads/vrd000_papeco_ver3/vrd000_papeco_ver3/■VRM/vrd000_papeco_ver2_ps.vrm
# 2. 開発サーバー
cd app; npm run dev
# 3. ブラウザで http://localhost:5173/avatar.html
```

- 右のパネルで表情ボタン・強さ・自動まばたき・「話す」を試す。ドラッグで回転、ホイールで拡大
- `.env.local` を書かなくても、画面に `.vrm` をドロップすれば読める
- 開発中はブラウザのコンソールで `__avatarStage.speak("あいうえお", 0.2)` のように直接呼べる

`.env.local` の値は `vite.config.ts` の `localAvatarModel` プラグインが読み、`/__avatar/model.vrm` でファイルを返す。
**開発サーバーだけ**の仕組み(`apply: "serve"`)なので、`npm run build` の成果物にモデルが混ざることはない。

## 規約の確認(2026-11-22)

使う前に配布規約と VRM のメタ情報を見る、と ADR 0109 で決めている。結果:

| 確認元 | 内容 |
|---|---|
| 同梱 `Readme.txt` | VN3 ライセンスを元にした puppet end 規約に従う。追記で「テクスチャを使った VRoid データ・テクスチャの販売・再配布の禁止」「自作発言の禁止」 |
| VRM 内のメタ(VRM 0.x) | 商用 Disallow、再配布禁止(`Redistribution_Prohibited`)、性的・暴力表現 Disallow、利用者は「明示的に許可された人」 |
| VRoid Hub の配布ページ | アバター利用 OK、改変 OK、再配布 NG、クレジット不要(性的・暴力・商用は OK 表記で、VRM メタより緩い) |
| puppet end 規約本文(Web) | ページは開けたが、本文を表示する部品が「App Unavailable」で**読めなかった**(未確認) |

判断:**手元でテスト表示するだけなら問題ない**。いちばん厳しい VRM メタに合わせて、次を守る。

- モデル・テクスチャをリポジトリ・インストーラ・Release に入れない(`.gitignore` に `*.vrm` `*.vroid` を追加)
- 商用利用しない。性的・暴力的な表現に使わない
- 画面写真を公開するなら「puppet end ぱぺこ(作:ぬぁろ)」と明記し、自作と言わない
- 規約本文は未確認なので、配信・公開に使う前に作者の X(@NoaaRo_)か BOOTH で本文を確かめる

## ハマりどころ

- **腕が上がる**:腕を下ろすつもりで `leftUpperArm` の z 回転を負にしたらバンザイになった。正規化ボーンでは左腕は **+z** で下がる(右腕は −z)
- **「おどろき」が効かない**:VRM 0.x には `surprised` のプリセットが無い。このモデルは作者が独自に `Surprised`(先頭大文字)を足していたので、同名の独自表情で代用するようにした(`resolveExpression`)
- **表情が 70 個ある**:ARKit(iPhone の顔追跡)由来の 52 個が入っている。将来、顔追跡を使うなら役に立つ
- **`.env.local` を PowerShell 5.1 の `Set-Content -Encoding utf8` で作ると読めない**:先頭に BOM(目に見えない印)が付き、変数名が `﻿SENTINEL_...` になってしまう。メモ帳か VS Code で作る
- **`THREE.Clock` が非推奨の警告**:three r187 で `Timer` に置き換え中。依存を減らすため `performance.now()` で dt を計算した
- **ビルドで 500kB 超の警告**:three.js が大きいため。アバターは別ページ(`avatar.html`)に分けたので、チャット画面の読み込みは重くならない
- **最初の1回だけ自動読み込みされない**ことがあった:開発サーバーの起動直後で `/__avatar/model.vrm` がまだ返らなかったため。再読み込みで直る

## 次の段階(未着手)

1. Tauri に透明・枠なし・最前面の `avatar` 窓を足し、この画面を載せる(クリック透過は別途)
2. VOICEVOX の `audio_query` はモーラごとに母音と長さを返すので、文字からの推測をやめて正確な口パクにする
3. コアの感情(PAD → ラベル、ADR 0107)を WebSocket で受けて `setEmotion` に流す

## 確認問題

1. three.js と three-vrm はそれぞれ何を受け持っているか
2. VRM 0.x のモデルを読むときに必要な一手間は何か。なぜ必要か
3. 表情の重みを `dt` を使って近づけるのはなぜか
4. 「きゃ」「ん」「ー」はそれぞれ口の形にどう変換されるか
5. このテストモデルで、してはいけないことを3つ挙げよ
