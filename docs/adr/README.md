# ADR 一覧

設計判断を1件1ファイルで記録する。番号は仕様書 v3 の 0001〜0003、AI_Vtuber_v2 の 0001〜0005 と衝突しないよう 0101 から。書き方は `.claude/skills/adr/SKILL.md`。

| ADR | 題名 | 状態 |
|---|---|---|
| [0101](0101-sentinel-as-single-codebase.md) | SENTINEL を唯一のコード基盤とし、AI_Vtuber_v2 は資産として移植する | Accepted |
| [0102](0102-pydantic-ai-for-agent.md) | エージェント基盤に Pydantic AI を採用する | Proposed |
| [0103](0103-wireguard-only-bind.md) | 頭脳を自宅サーバーへ移す際は WireGuard インタフェースにのみバインドする | Proposed |
| [0104](0104-zenoh-for-brain-bus.md) | Brain Bus の伝送に Zenoh を採用する(2028年) | Proposed |
| [0105](0105-sqlite-memory.md) | 記憶は SQLite(FTS5 + sqlite-vec)に統一し、一次記録と二次記録を分ける | Proposed |
| [0106](0106-persona-spec-is-source.md) | 人格の正は人格仕様書と学習データ、LoRA は派生物とする | Proposed |
| [0107](0107-pad-emotion.md) | 感情は PAD の内部状態とラベルの表出に分ける | Proposed |
| [0108](0108-stock-tts-voices.md) | 音声は既製話者を既定とし、学習型TTSは権利の明確な音源に限る | Proposed |
| [0109](0109-three-vrm-avatar.md) | アバターは three-vrm で描画し、VTube Studio 連携を廃止する | Proposed |
| [0110](0110-deprioritize-distribution.md) | 配布(S2〜S4)の優先度を下げ、OSS公開は 2031年と 2036年に手法のみとする | Proposed |
| [0111](0111-original-main-persona.md) | 主人格はオリジナルとし、ユウカは私的 Pack とする | Accepted |
| [0112](0112-new-ollama-persona.md) | Ollama で使う人格は新しく作り、ユウカ LoRA の GGUF 化は行わない | Accepted |
| [0113](0113-pluggable-tts-voicevox-first.md) | TTS はコアの差し込み口(アダプタ)にし、まず VOICEVOX ENGINE(HTTP)で鳴らす | Accepted |

Proposed はロードマップで決めた方針で、作者の確認後に Accepted に変える。
