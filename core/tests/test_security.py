"""セキュリティ回りの回帰テスト(CORS許可範囲・ログのトークンマスク)。"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sentinel_core.api.app import create_app
from sentinel_core.logging_setup import TokenRedactionFilter, redact
from sentinel_core.settings import Settings

TOKEN = "test-token"
PREFLIGHT = {
    "Access-Control-Request-Method": "GET",
    "Access-Control-Request-Headers": "x-sentinel-token,content-type",
}


def _client(tmp_path: Path, dev: bool) -> TestClient:
    return TestClient(create_app(Settings.load(data_dir=tmp_path), token=TOKEN, dev=dev))


@pytest.mark.parametrize("origin", ["http://tauri.localhost", "tauri://localhost"])
def test_managed_allows_tauri_origin(tmp_path: Path, origin: str):
    """配布ビルド(managed)でもTauriの画面からのfetchがプリフライトを通ること。"""
    with _client(tmp_path, dev=False) as c:
        r = c.options("/v1/system/health", headers={"Origin": origin, **PREFLIGHT})
        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize("dev", [False, True])
def test_other_origins_are_not_allowed(tmp_path: Path, dev: bool):
    with _client(tmp_path, dev=dev) as c:
        r = c.options("/v1/system/health", headers={"Origin": "https://evil.example", **PREFLIGHT})
        assert "access-control-allow-origin" not in r.headers


def test_vite_origin_only_in_dev(tmp_path: Path):
    origin = "http://localhost:5173"
    with _client(tmp_path, dev=True) as c:
        r = c.options("/v1/system/health", headers={"Origin": origin, **PREFLIGHT})
        assert r.headers.get("access-control-allow-origin") == origin
    with _client(tmp_path, dev=False) as c:
        r = c.options("/v1/system/health", headers={"Origin": origin, **PREFLIGHT})
        assert "access-control-allow-origin" not in r.headers


def test_redact_masks_token_in_query():
    line = '127.0.0.1:5 - "WebSocket /v1/stream?token=abc-DEF_123&x=1" [accepted]'
    assert redact(line) == '127.0.0.1:5 - "WebSocket /v1/stream?token=***&x=1" [accepted]'


def test_filter_rewrites_uvicorn_style_record():
    # uvicorn は msg のテンプレートと args を分けて記録する
    record = logging.LogRecord(
        "uvicorn.error",
        logging.INFO,
        __file__,
        1,
        '%s - "WebSocket %s" [accepted]',
        ("127.0.0.1:5", "/v1/stream?token=secret"),
        None,
    )
    assert TokenRedactionFilter().filter(record)
    assert record.getMessage() == '127.0.0.1:5 - "WebSocket /v1/stream?token=***" [accepted]'
