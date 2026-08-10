"""配置加载: 环境变量 > ~/.munagent/config.yaml > 内置默认."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from config.models import AppConfig, ProviderConfig, default_config

CONFIG_DIR = Path.home() / ".munagent"
CONFIG_PATH = CONFIG_DIR / "config.yaml"

_ENV_PREFIX = "MUNAGENT_"


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in overlay.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    providers = dict(out.get("providers") or {})
    deepseek = dict(providers.get("deepseek") or {})

    api_key = os.environ.get(f"{_ENV_PREFIX}API_KEY")
    if api_key is not None:
        deepseek["api_key"] = api_key

    base_url = os.environ.get(f"{_ENV_PREFIX}BASE_URL")
    if base_url is not None:
        deepseek["base_url"] = base_url

    if deepseek:
        providers["deepseek"] = deepseek
        out["providers"] = providers

    return out


def _parse_providers(raw: dict[str, Any]) -> dict[str, ProviderConfig]:
    providers: dict[str, ProviderConfig] = {}
    for name, cfg in (raw.get("providers") or {}).items():
        if not isinstance(cfg, dict):
            raise ValueError(f"providers.{name} 须为对象")
        base_url = cfg.get("base_url")
        if not base_url or not isinstance(base_url, str):
            raise ValueError(f"providers.{name}.base_url 缺失或非字符串")
        api_key = cfg.get("api_key") or ""
        if not isinstance(api_key, str):
            raise ValueError(f"providers.{name}.api_key 须为字符串")
        providers[str(name)] = ProviderConfig(base_url=base_url, api_key=api_key)
    return providers


def load_config(*, path: Path | None = None) -> AppConfig:
    """加载配置: env > yaml > 默认."""
    cfg_path = path or CONFIG_PATH
    base = default_config()
    merged: dict[str, Any] = {
        "default_provider": base.default_provider,
        "default_model": base.default_model,
        "providers": {
            k: {"base_url": v.base_url, "api_key": v.api_key}
            for k, v in base.providers.items()
        },
    }
    merged = _deep_merge(merged, _load_yaml(cfg_path))
    merged = _apply_env_overrides(merged)

    providers = _parse_providers(merged)
    if not providers:
        providers = default_config().providers

    default_provider = str(merged.get("default_provider") or "deepseek")
    default_model = str(merged.get("default_model") or "deepseek-v4-flash")

    return AppConfig(
        providers=providers,
        default_provider=default_provider,
        default_model=default_model,
    )
