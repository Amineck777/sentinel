# 0109. アバターは three-vrm で描画し、VTube Studio 連携を廃止する

- 状態: Proposed
- 日付: 2026-11-22
- 関連: 統合ロードマップ v1.2(`/mnt/project-files/roadmap/integrated-roadmap-and-tech-selection.md`) C8、§4.2 身体 #0

## 背景
VT は VTube Studio 経由、デザイン canvas は three.js で VRM を描く案。透明窓・クリック透過・表情・口パクを自前で制御したい。

## 選択肢
| 案 | 長所 | 短所 |
|---|---|---|
| three-vrm(VRM 1.0) | 別アプリ不要。Tauri の窓で完結 | 描画を自前で作る |
| VTube Studio | 表現力が高い | 別アプリ必須。トークン管理が要る |

## 決定
three.js + @pixiv/three-vrm で描画し、VTube Studio 連携は廃止する。モデルはミルティナの前に、フリーの3Dモデル(VRoid 自作、VRM 変換可の無料 VRChat アバター)で表示・表情・口形・変換手順を検証する。

## 結果
モデルファイルはリポジトリに入れない。使う前に配布規約と VRM メタ情報を確認して記録する。

## 記録
- 2026-11-22 テストモデル「ぱぺこ」(puppet end, 作:ぬぁろ, VRM 0.x)を確認。VRM メタは商用・性的・暴力 Disallow、再配布禁止。VRoid Hub 表記はアバター利用・改変 OK、再配布 NG。手元のテスト表示に限って使い、リポジトリには入れない。詳細は `docs/learning/04-avatar-prototype.md`
