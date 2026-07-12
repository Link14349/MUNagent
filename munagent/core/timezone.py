"""时区工具: UTC→会场本地时间转换. 见 04§5.

内部一律 UTC, 渲染给代表/用户时按会场 timezone 转本地.
转换是确定性纯函数, 不破坏缓存纪律(11§4).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def to_local_time(utc_str: str, timezone: str = "UTC") -> str:
    """UTC ISO 字符串 → 指定时区的本地时间 ISO 字符串.

    输入: "2026-03-15T01:00:00+00:00" 或 "2026-03-15T09:00:00+08:00"
    输出: "2026-03-15T09:00:00+08:00" (按 Asia/Shanghai 转换)
    """
    if not utc_str:
        return utc_str
    try:
        dt = datetime.fromisoformat(utc_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        local_dt = dt.astimezone(ZoneInfo(timezone))
        return local_dt.isoformat()
    except Exception:
        return utc_str


def local_time_short(utc_str: str, timezone: str = "UTC") -> str:
    """简短格式: "09:00" 用于 CLI 显示."""
    local = to_local_time(utc_str, timezone)
    try:
        dt = datetime.fromisoformat(local)
        return dt.strftime("%H:%M")
    except Exception:
        return local
