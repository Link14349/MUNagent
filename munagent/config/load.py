"""配置加载: 环境变量 > ~/.munagent/config.yaml > 内置默认."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from munagent.config.models import AppConfig, default_config

CONFIG_DIR = Path.home() / ".munagent"
CONFIG_PATH = CONFIG_DIR / "config.yaml"

_ENV_PREFIX = "MUNAGENT_"


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """递归合并 overlay 到 base 副本."""
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
    """常用环境变量快捷覆盖(优先级最高)."""
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

    tools = dict(out.get("tools") or {})
    mineru = dict(tools.get("mineru") or {})
    mineru_url = os.environ.get(f"{_ENV_PREFIX}MINERU_URL")
    if mineru_url is not None:
        mineru["base_url"] = mineru_url
        tools["mineru"] = mineru
        out["tools"] = tools

    server = dict(out.get("server") or {})
    port = os.environ.get(f"{_ENV_PREFIX}PORT")
    if port is not None:
        server["port"] = int(port)
        out["server"] = server

    return out


def load_config(*, path: Path | None = None) -> AppConfig:
    """加载配置: env > yaml > 默认."""
    cfg_path = path or CONFIG_PATH
    merged = default_config().model_dump()
    merged = _deep_merge(merged, _load_yaml(cfg_path))
    merged = _apply_env_overrides(merged)
    try:
        return AppConfig.model_validate(merged)
    except ValidationError as exc:
        raise ValueError(f"配置校验失败 ({cfg_path}): {exc}") from exc


def mask_api_key(key: str) -> str:
    """展示用掩码 — key 不回传明文."""
    if not key or key == "none":
        return "(未设置)"
    if len(key) <= 8:
        return "****"
    return f"{key[:3]}****{key[-4:]}"
