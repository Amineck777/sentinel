"""設定ロード(仕様 §8)。

既定値は下の DEFAULTS が唯一の正(sidecar 単体で動くよう、外部ファイルに頼らない)。
ユーザー差分 {APP_DATA}/sentinel/config.yaml をこれにマージする。
config/config.default.yaml は既定値を人が読むための写しで、テストで DEFAULTS と一致を検査する。
不正・欠損は起動失敗にせず既定値へフォールバック(配布後サポアビリティ)。
パス解決は platformdirs 準拠(仕様 §5.5: OS依存の隔離)。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from platformdirs import user_data_dir

APP_NAME = "sentinel"


def _default_data_dir() -> Path:
    # SENTINEL_DATA_DIR はテスト・スモークCI用の隔離手段(実データを汚さない)
    return Path(os.environ.get("SENTINEL_DATA_DIR") or user_data_dir(APP_NAME))


DEFAULTS: dict[str, Any] = {
    "llm": {
        "endpoint": "http://127.0.0.1:11434/v1",
        "chat_model": "qwen2.5:7b-instruct",  # 実名は設定で差替可・仕様はクラスのみ規定
        "request_timeout_sec": 120,
        # 考える(thinking)モデルの思考を使うか。チャットでは切る(gemma4 などは
        # 思考すると返答が数十秒遅れるため)。推論サーバーが対応していなければ無視される
        "think": False,
    },
    "character": {"active": "none"},
    "app": {"language": "ja"},
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class Settings:
    data: dict[str, Any] = field(default_factory=lambda: dict(DEFAULTS))
    data_dir: Path = field(default_factory=_default_data_dir)

    @classmethod
    def load(cls, data_dir: Path | None = None) -> Settings:
        data_dir = data_dir or _default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        user_cfg: dict[str, Any] = {}
        cfg_path = data_dir / "config.yaml"
        if cfg_path.exists():
            try:
                user_cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            except Exception:
                user_cfg = {}  # 不正configは無視して既定値で起動(警告は/healthで返す)
        return cls(data=_deep_merge(DEFAULTS, user_cfg), data_dir=data_dir)

    @property
    def llm_endpoint(self) -> str:
        return str(self.data["llm"]["endpoint"]).rstrip("/")

    @property
    def chat_model(self) -> str:
        return str(self.data["llm"]["chat_model"])

    @property
    def llm_think(self) -> bool:
        return bool(self.data["llm"].get("think", False))

    @property
    def db_path(self) -> Path:
        p = self.data_dir / "data"
        p.mkdir(parents=True, exist_ok=True)
        return p / "sentinel.db"

    @property
    def characters_dir(self) -> Path:
        p = self.data_dir / "characters"
        p.mkdir(parents=True, exist_ok=True)
        return p
