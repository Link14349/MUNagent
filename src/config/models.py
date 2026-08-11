"""配置 schema - providers 与可选默认模型."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProviderConfig:
    base_url: str
    api_key: str = ""


@dataclass
class AppConfig:
    """~/.munagent/config.yaml 解析结果."""

    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    default_provider: str = "deepseek"
    default_model: str = "deepseek-v4-flash"


def default_config() -> AppConfig:
    return AppConfig(
        providers={
            "deepseek": ProviderConfig(
                base_url="https://api.deepseek.com",
                api_key="",
            ),
        },
    )
