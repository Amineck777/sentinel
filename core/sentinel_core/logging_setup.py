"""ログ設定(実装方針 §6: ログにトークンを出さない)。

uvicorn は WebSocket 接続を `"WebSocket /v1/stream?token=..."` の形で記録する。
WSの認証トークンはクエリで渡す契約(実装方針 §2)なので、そのままだと
ログ(managedモードでは Tauri 側の stderr)に実トークンが残る。
uvicorn のロガーにフィルタを挟んでマスクする。
"""

from __future__ import annotations

import logging
import re

_TOKEN_RE = re.compile(r"(token=)[^&\s\"']+")
MASK = r"\1***"

UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def redact(text: str) -> str:
    """URLクエリ中の token=... を token=*** に置き換える。"""
    return _TOKEN_RE.sub(MASK, text)


class TokenRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        masked = redact(message)
        if masked != message:
            record.msg = masked
            record.args = None
        return True


def install_token_redaction() -> None:
    """uvicorn の各ロガーにマスクフィルタを付ける(重複登録はしない)。"""
    for name in UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(f, TokenRedactionFilter) for f in logger.filters):
            logger.addFilter(TokenRedactionFilter())
