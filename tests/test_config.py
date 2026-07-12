"""配置加载测试."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from munagent.config import load_config, mask_api_key, save_config
from munagent.config.models import default_config


def test_default_config_has_roles() -> None:
    cfg = default_config()
    assert "delegate" in cfg.roles
    assert cfg.roles["delegate"].model == "deepseek-v4-flash"


def test_load_yaml_merge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        yaml.safe_dump(
            {
                "providers": {
                    "deepseek": {"base_url": "https://custom.example.com", "api_key": "sk-file"},
                },
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(path=cfg_file)
    assert cfg.providers["deepseek"].base_url == "https://custom.example.com"
    assert cfg.providers["deepseek"].api_key == "sk-file"


def test_env_overrides_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        yaml.safe_dump({"providers": {"deepseek": {"base_url": "https://a.com", "api_key": "from-file"}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("MUNAGENT_API_KEY", "from-env")
    cfg = load_config(path=cfg_file)
    assert cfg.providers["deepseek"].api_key == "from-env"


def test_save_config_chmod_600(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    save_config(default_config(), path=path)
    assert oct(path.stat().st_mode & 0o777) == oct(0o600)


def test_mask_api_key() -> None:
    assert mask_api_key("") == "(未设置)"
    assert "****" in mask_api_key("sk-abcdefghijklmnop")
