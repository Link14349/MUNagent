"""配置加载: 环境变量 > ~/.munagent/config.yaml > 内置默认."""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

from munagent.config.models import MunagentConfig, ProviderConfig

DEFAULT_CONFIG_PATH = Path.home() / ".munagent" / "config.yaml"
DEFAULT_PROVIDER_NAME = "deepseek"


def default_config_dict() -> dict[str, Any]:
    return {
        "providers": {
            "deepseek": {
                "base_url": "https://api.deepseek.com",
                "api_key": "",
            },
        },
        "roles": {
            "delegate": {"provider": "deepseek", "model": "deepseek-v4-flash"},
            "chair": {"provider": "deepseek", "model": "deepseek-v4-pro"},
            "dm": {"provider": "deepseek", "model": "deepseek-v4-pro"},
            "recorder": {"provider": "deepseek", "model": "deepseek-v4-flash"},
            "designer": {"provider": "deepseek", "model": "deepseek-v4-pro"},
        },
        "tools": {
            "mineru": {"base_url": "http://36.139.151.129:8282"},
            "search": {"provider": "tavily", "api_key": ""},
        },
    }


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _apply_env_overrides(data: dict[str, Any]) -> None:
    """环境变量优先级最高, 覆盖文件与默认值."""
    providers = data.setdefault("providers", {})
    default_name = DEFAULT_PROVIDER_NAME if DEFAULT_PROVIDER_NAME in providers else next(
        iter(providers), DEFAULT_PROVIDER_NAME
    )
    provider = providers.setdefault(default_name, {"base_url": "", "api_key": ""})

    api_key = os.environ.get("MUNAGENT_API_KEY")
    if api_key:
        provider["api_key"] = api_key

    base_url = os.environ.get("MUNAGENT_BASE_URL")
    if base_url:
        provider["base_url"] = base_url

    mineru_url = os.environ.get("MUNAGENT_MINERU_URL")
    if mineru_url:
        data.setdefault("tools", {}).setdefault("mineru", {})["base_url"] = mineru_url

    port = os.environ.get("MUNAGENT_PORT")
    if port:
        data.setdefault("server", {})["port"] = int(port)


class EnvSettings(BaseSettings):
    """仅承载扁平环境变量快捷项, 供与 YAML 合并."""

    model_config = SettingsConfigDict(env_prefix="MUNAGENT_", extra="ignore")

    api_key: str | None = None
    base_url: str | None = None
    mineru_url: str | None = None
    port: int | None = None
    config_path: str | None = None


def config_path_from_env() -> Path:
    env = EnvSettings()
    if env.config_path:
        return Path(env.config_path).expanduser()
    return DEFAULT_CONFIG_PATH


def load_config(*, path: Path | None = None) -> MunagentConfig:
    config_path = path or config_path_from_env()
    data = _deep_merge(default_config_dict(), _load_yaml(config_path))
    _apply_env_overrides(data)
    return MunagentConfig.model_validate(data)


def mask_api_key(api_key: str) -> str:
    """设置页展示用掩码, 不回传完整 key."""
    if not api_key or api_key == "none":
        return "(未设置)"
    if len(api_key) <= 8:
        return "****"
    return f"{api_key[:3]}****{api_key[-4:]}"
