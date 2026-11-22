# 0101. SENTINEL を唯一のコード基盤とし、AI_Vtuber_v2 は資産として移植する

- 状態: Accepted
- 日付: 2026-11-22
- 関連: 統合ロードマップ v1.2(`/mnt/project-files/roadmap/integrated-roadmap-and-tech-selection.md`) C1、調査報告 `sentinel-review-2026-11-22.md`

## 背景
コード基盤が2つあった。SENTINEL(Phase 1 実装・テスト・CI・Tauri あり)と、AI_Vtuber_v2 の v2 リビルド計画(テスト0件、UI が壊れている)。個人開発で同じものを2回作る余裕はない。

## 選択肢
| 案 | 長所 | 短所 |
|---|---|---|
| SENTINEL に一本化 | 実装・テスト・CI が揃う。B1〜B5 修正後は Windows 実機で動作確認済み | VT の資産を移す作業が要る |
| VT v2 をリビルド | ユウカ周りの資産が最初からある | 土台を作り直す。テストもない |
| 両方を並行 | — | 保守が倍になる |

## 決定
SENTINEL に一本化する。AI_Vtuber_v2 からは、設計判断(構造化出力・発話パイプライン・ヘキサゴナル)と資産(LoRA・学習データ・記憶ロジック・感情→声質表)だけを移植する。`vts_token.txt` は移さない。

## 結果
作業は SENTINEL の中で完結する。VT のコードは参照用として凍結する。2026-11-22 に作者が「まず SENTINEL を完成させる」と合意済み。
