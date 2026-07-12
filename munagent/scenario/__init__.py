"""场景包库 — designer 产出、deducer 消费的共享契约.

子模块: package(元信息/加载/校验/保存)、files(单文件操作与文件树)、
history(.history 版本快照)、chats(设计对话 JSONL 持久化).
"""

from munagent.scenario.package import (
    DuplicateScenarioRequest,
    Manifest,
    ScenarioCreate,
    ScenarioDetail,
    ScenarioSummary,
)

__all__ = [
    "DuplicateScenarioRequest",
    "Manifest",
    "ScenarioCreate",
    "ScenarioDetail",
    "ScenarioSummary",
]
