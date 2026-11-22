# 0102. エージェント基盤に Pydantic AI を採用する

- 状態: Proposed
- 日付: 2026-11-22
- 関連: 統合ロードマップ v1.2(`/mnt/project-files/roadmap/integrated-roadmap-and-tech-selection.md`) C2、仕様書 §4(LangGraph)、VT ADR-0003

## 背景
仕様書 v3 は Phase 3 で LangGraph を予定していたが、VT は Pydantic AI を採用していた。感情付きの構造化出力(`{reply, emotion_label, appraisal}`)を素直に書けることが重要。

## 選択肢
| 案 | 長所 | 短所 |
|---|---|---|
| Pydantic AI | 型付きの構造化出力が素直。薄い | 複雑な多段グラフは自前で書く |
| LangGraph | 状態機械・チェックポイントが揃う | 抽象が厚く、陳腐化したときの置き換えが重い |
| 自前のみ | 依存ゼロ | ツール呼び出しやリトライを全部作る |

## 決定
Pydantic AI を採用し、`agent/` ポート(`ChatService`)の裏に隔離する。多段の計画が必要になったら、自前の状態機械(ビヘイビアツリー)で書く。

## 結果
`core/sentinel_core/agent/service.py` が差し替え点。仕様書 §4 と同ファイルのコメントの LangGraph 記述は本 ADR で上書きする。
