"""配置加载单元测试."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from munagent.config.load import load_config, mask_api_key
from munagent.config.persist import save_config
from munagent.config.models import MunagentConfig, ProviderConfig, RoleConfig


def test_load_config_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = tmp_path / "missing.yaml"
    monkeypatch.setenv("MUNAGENT_CONFIG_PATH", str(missing))
    monkeypatch.delenv("MUNAGENT_API_KEY", raising=False)
    cfg = load_config(path=missing)
    assert cfg.roles["delegate"].model == "deepseek-v4-flash"
    assert cfg.tools.mineru.base_url == "http://36.139.151.129:8282"


def test_env_overrides_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"providers": {"deepseek": {"api_key": "from-file"}}}))
    monkeypatch.setenv("MUNAGENT_CONFIG_PATH", str(path))
    monkeypatch.setenv("MUNAGENT_API_KEY", "sk-from-env")
    cfg = load_config(path=path)
    assert cfg.providers["deepseek"].api_key == "sk-from-env"


def test_save_config_chmod_600(tmp_path: Path) -> None:
    target = tmp_path / "config.yaml"
    cfg = MunagentConfig(
        providers={"deepseek": ProviderConfig(base_url="https://api.deepseek.com", api_key="sk-x")},
        roles={"delegate": RoleConfig(provider="deepseek", model="deepseek-v4-flash")},
    )
    save_config(cfg, path=target)
    assert target.exists()
    assert oct(target.stat().st_mode & 0o777) == oct(0o600)


def test_mask_api_key() -> None:
    assert mask_api_key("sk-abcdefghijklmnop") == "sk-****mnop"
