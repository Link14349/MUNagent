"""设计器场景包 — 磁盘上的场景包 CRUD、单文件编辑、历史与对话持久化.

子模块: package(元信息/加载/校验/保存)、files(单文件操作与文件树)、
history(.history 版本快照)、chats(.chats 设计对话 JSONL 持久化).
"""

from munagent.designer.scenario.package import (
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
