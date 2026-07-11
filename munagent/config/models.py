"""分层配置模型. 见 docs/design/08-config.md."""

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
    base_url: str = "http://36.139.151.129:8282"


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
    epoch_l3_max_tokens: int = 3000
    cache_warmup: bool = True


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    debug_dump_prompts: bool = False


class MunagentConfig(BaseModel):
    providers: dict[str, ProviderConfig]
    roles: dict[str, RoleConfig]
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    engine: EngineConfig = Field(default_factory=EngineConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)

    def resolve_role(self, role: str) -> tuple[ProviderConfig, str]:
        """角色路由: role -> (provider配置, model名)."""
        if role not in self.roles:
            raise KeyError(f"未知角色路由: {role}")
        route = self.roles[role]
        if route.provider not in self.providers:
            raise KeyError(f"角色 {role} 引用的 provider 不存在: {route.provider}")
        return self.providers[route.provider], route.model

    def default_provider_name(self) -> str:
        if "deepseek" in self.providers:
            return "deepseek"
        return next(iter(self.providers))
