from __future__ import annotations

from agent.rep_agent_tools import RepresentativeToolExecutor
from scenario.representative import Representative


class RepresentativeAgent:
    """单个代表的 Agent;由 ``Simulator`` 在独立线程中调用 ``run``."""

    rep: Representative
    tools: RepresentativeToolExecutor

    def __init__(self, rep: Representative) -> None:
        self.rep = rep
        self.tools = RepresentativeToolExecutor(rep)

    def run(self) -> None:
        """代表 Agent 主循环(当前为空实现,由后续里程碑填充)."""
        return
