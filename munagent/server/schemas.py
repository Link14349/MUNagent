"""配置 API 的公开 schema — key 掩码, 不回传明文."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from munagent.config.models import (
    AdjudicationThresholds,
    AppConfig,
    EngineConfig,
    RoleConfig,
    ServerConfig,
)


class ProviderPublic(BaseModel):
    base_url: str
    api_key_masked: str
    has_key: bool


class SearchToolPublic(BaseModel):
    provider: Literal["tavily", "serper", "bocha"]
    api_key_masked: str
    has_key: bool


class MineruToolPublic(BaseModel):
    base_url: str


class ToolsPublic(BaseModel):
    mineru: MineruToolPublic
    search: SearchToolPublic


class ConfigPublic(BaseModel):
    providers: dict[str, ProviderPublic]
    roles: dict[str, RoleConfig]
    tools: ToolsPublic
    engine: EngineConfig
    server: ServerConfig


class ConfigUpdate(BaseModel):
    providers: dict[str, dict[str, str]] | None = None
    roles: dict[str, RoleConfig] | None = None
    tools: dict | None = None
    engine: EngineConfig | None = None
    server: ServerConfig | None = None


class ConfigTestRequest(BaseModel):
    target: str = Field(description="provider:<name> | tool:mineru | tool:search")


class ConfigTestResponse(BaseModel):
    ok: bool
    message: str


def to_public(config: AppConfig) -> ConfigPublic:
    from munagent.config import mask_api_key

    providers = {
        name: ProviderPublic(
            base_url=p.base_url,
            api_key_masked=mask_api_key(p.api_key),
            has_key=bool(p.api_key and p.api_key != "none"),
        )
        for name, p in config.providers.items()
    }
    tools = ToolsPublic(
        mineru=MineruToolPublic(base_url=config.tools.mineru.base_url),
        search=SearchToolPublic(
            provider=config.tools.search.provider,
            api_key_masked=mask_api_key(config.tools.search.api_key),
            has_key=bool(config.tools.search.api_key),
        ),
    )
    return ConfigPublic(
        providers=providers,
        roles=config.roles,
        tools=tools,
        engine=config.engine,
        server=config.server,
    )
