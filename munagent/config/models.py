"""配置 schema — 与 docs/design/08-config.md 对齐."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ProviderConfig(BaseModel):
    base_url: str
    api_key: str


class RoleConfig(BaseModel):
    provider: str
    model: str


class MineruToolConfig(BaseModel):
    base_url: str = ""


class SearchToolConfig(BaseModel):
    provider: Literal["tavily", "serper", "bocha"] = "tavily"
    api_key: str = ""


class ToolsConfig(BaseModel):
    mineru: MineruToolConfig = Field(default_factory=MineruToolConfig)
    search: SearchToolConfig = Field(default_factory=SearchToolConfig)


class AdjudicationThresholds(BaseModel):
    great: int = 40
    success: int = 10
    partial: int = 0
    fail: int = -20


class EngineConfig(BaseModel):
    unmod_rounds: int = 4
    mod_max_speeches: int = 12
    session_max_tokens: int = 2_000_000
    human_timeout_s: int = 300
    human_timeout_fallback: Literal["ai_delegate", "pass"] = "ai_delegate"
    adjudication_thresholds: AdjudicationThresholds = Field(default_factory=AdjudicationThresholds)
    epoch_l3_max_tokens: int = 8192
    cache_warmup: bool = True


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    debug_dump_prompts: bool = False


class AppConfig(BaseModel):
    """运行时全局配置(不含会话级快照)."""

    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    roles: dict[str, RoleConfig] = Field(default_factory=dict)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    engine: EngineConfig = Field(default_factory=EngineConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)


def default_config() -> AppConfig:
    """内置默认值 — 无 key, 供 env/yaml 覆盖."""
    return AppConfig(
        providers={
            "deepseek": ProviderConfig(
                base_url="https://api.deepseek.com",
                api_key="",
            ),
        },
        roles={
            "delegate": RoleConfig(provider="deepseek", model="deepseek-v4-flash"),
            "chair": RoleConfig(provider="deepseek", model="deepseek-v4-pro"),
            "dm": RoleConfig(provider="deepseek", model="deepseek-v4-pro"),
            "recorder": RoleConfig(provider="deepseek", model="deepseek-v4-flash"),
            "designer": RoleConfig(provider="deepseek", model="deepseek-v4-pro"),
        },
    )
