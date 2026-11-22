# 0104. Brain Bus の伝送に Zenoh を採用する(2028年)

- 状態: Proposed
- 日付: 2026-11-22
- 関連: 統合ロードマップ v1.2(`/mnt/project-files/roadmap/integrated-roadmap-and-tech-selection.md`) §2.3、§4.2 基盤

## 背景
2028年に卓上身体(頭部・首・目)が加わり、頭脳と複数の身体の間でイベントを流す必要がある。2027年は EventHub + WebSocket で足りる。

## 選択肢
| 案 | 長所 | 短所 |
|---|---|---|
| Zenoh | 軽量。ROS 2 と rmw_zenoh で接続できる | 学習コスト |
| MQTT | 枯れている | ROS 2 との接続に橋渡しが要る |
| WS のまま | 変更なし | 多対多・低遅延に向かない |

## 決定
2027年はスキーマ(イベントの型)だけ先に固定し、伝送は EventHub + WS。2028年に Zenoh へ移る。

## 結果
2027年中は実装しない。イベントの型を Pydantic で定義しておけば、伝送の差し替えで済む。
