"""設定: 既定値の写し(config.default.yaml)が DEFAULTS と食い違っていないこと(B6)。"""

from __future__ import annotations

from pathlib import Path

import yaml

from sentinel_core.settings import DEFAULTS, Settings

DEFAULT_YAML = Path(__file__).resolve().parents[2] / "config" / "config.default.yaml"


def test_default_yaml_matches_defaults():
    assert yaml.safe_load(DEFAULT_YAML.read_text(encoding="utf-8")) == DEFAULTS


def test_user_config_overrides_defaults(tmp_path: Path):
    (tmp_path / "config.yaml").write_text("character:\n  active: sera\n", encoding="utf-8")
    s = Settings.load(data_dir=tmp_path)
    assert s.data["character"]["active"] == "sera"
    assert s.data["llm"] == DEFAULTS["llm"]  # 書いていない項目は既定値のまま
