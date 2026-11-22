# 0105. 記憶は SQLite(FTS5 + sqlite-vec)に統一し、一次記録と二次記録を分ける

- 状態: Proposed
- 日付: 2026-11-22
- 関連: 統合ロードマップ v1.2(`/mnt/project-files/roadmap/integrated-roadmap-and-tech-selection.md`) C3・C13、§5

## 背景
仕様書は sqlite-vec、VT は Chroma。10年運用ではバックアップと移行の単純さが最優先。2027年1月から会話を貯め始める。

## 選択肢
| 案 | 長所 | 短所 |
|---|---|---|
| SQLite + FTS5 + sqlite-vec | 単一ファイル。全文・ベクトル・時系列・関係を1DBで | 大規模化で遅くなる可能性 |
| Chroma | ベクトル検索が手軽 | 別ストアになり、バックアップと整合性が二重 |
| PostgreSQL + pgvector | スケールする | 個人 PC の運用が重い |

## 決定
SQLite に統一する。生ログ(`messages`)は追記専用の一次記録、エピソード記憶はそこから作る二次記録として、スキーマ改良時に再生成できるようにする。Chroma の既存記憶は一度だけ移行する。

## 結果
スキーマは `user_version` で版管理済み(実装方針 §10、PR #2)。1年分で検索が遅くなったら PostgreSQL + pgvector を再検討する。
