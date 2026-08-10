"""场景领域模型与加载入口。"""

from __future__ import annotations

__all__ = ["Scenario", "load_scenario", "populate_scenario"]


def __getattr__(name: str):
    if name == "Scenario":
        from scenario.scenario import Scenario

        return Scenario
    if name == "load_scenario":
        from scenario.load import load_scenario

        return load_scenario
    if name == "populate_scenario":
        from scenario.load import populate_scenario

        return populate_scenario
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
