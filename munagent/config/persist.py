"""配置持久化 — 写入用户主目录并 chmod 600."""

from __future__ import annotations

from pathlib import Path

import yaml

from munagent.config.load import CONFIG_DIR, CONFIG_PATH
from munagent.config.models import AppConfig


def save_config(config: AppConfig, *, path: Path | None = None) -> Path:
    """将配置写入 yaml; 单机单人场景靠文件权限保护 key."""
    cfg_path = path or CONFIG_PATH
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = config.model_dump(mode="json")
    text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    cfg_path.write_text(text, encoding="utf-8")
    cfg_path.chmod(0o600)
    return cfg_path
