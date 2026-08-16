from __future__ import annotations

from datetime import datetime
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scenario.scenario import Scenario


class Condition:
    type: str
    content: str | datetime
    scenario: Scenario
    time: datetime | None

    def __init__(self, type: str, content: str | datetime, scenario: Scenario):
        self.type = type
        self.content = content
        self.scenario = scenario
        self.time = None
        if type == "time":
            if not isinstance(content, datetime):
                raise TypeError("time 条件的 content 须为 datetime")
            self.time = content

    def check(
        self,
        text_evaluator: Callable[[str], bool] | None = None,
    ) -> bool:
        """按当前权威状态检查条件。

        时间条件由程序确定性判断；自然语言条件需要调用方注入裁判。没有
        ``text_evaluator`` 时文本条件返回 ``False``，不会被意外提前触发。
        """
        if self.type == "time":
            if self.time is None:
                raise RuntimeError("time 条件缺少解析后的时间")
            return self.scenario.time >= self.time
        if self.type == "text":
            if text_evaluator is None:
                return False
            return bool(text_evaluator(str(self.content)))
        raise ValueError(f"未知条件类型: {self.type!r}")
