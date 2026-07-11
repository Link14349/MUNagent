"""用户配置文件持久化(chmod 600)."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from munagent.config.load import DEFAULT_CONFIG_PATH
from munagent.config.models import MunagentConfig


def save_config(config: MunagentConfig, *, path: Path | None = None) -> Path:
    target = path or DEFAULT_CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = config.model_dump(mode="json")
    target.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    os.chmod(target, 0o600)
    return target
