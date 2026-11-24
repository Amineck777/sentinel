"""プロンプトのトークン数の見積もり(ADR 0116 のトークン配分で使う)。

正確なトークン数はモデルのトークナイザーでしか分からないが、コアからは手軽に呼べない。
そこで「多めに見積もる」簡単な規則で数える。多めにしておけば、文脈(num_ctx)から
あふれて古い発言が黙って切り捨てられることを防げる(少なめだと、それが起きる)。

- 日本語などの非 ASCII 文字: 1文字 = 1トークン(実際は gemma 系で 0.6〜0.8 ほど)
- ASCII(英数字・記号・空白): 4文字 = 1トークン(英語の一般的な目安)
- 1発言ごとに、役割などの区切りの分として 4トークン足す
"""

from __future__ import annotations

# 1発言あたりの区切り(<start_of_turn>user など)の分
MESSAGE_OVERHEAD_TOKENS = 4


def estimate_tokens(text: str) -> int:
    """text のトークン数を多めに見積もる。"""
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    other_chars = len(text) - ascii_chars
    # ASCII は4文字で1トークン。端数は切り上げる(多めに見積もるため)
    return other_chars + (ascii_chars + 3) // 4


def estimate_message_tokens(content: str) -> int:
    """チャットの1発言分(区切りを含む)のトークン数の見積もり。"""
    return estimate_tokens(content) + MESSAGE_OVERHEAD_TOKENS
