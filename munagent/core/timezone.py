"""时区工具: UTC 归一化与 UTC→会场本地时间转换. 见 04§5.

内部一律 UTC(ISO 带 Z), 渲染给代表/用户时按会场 timezone 转本地.
转换是确定性纯函数, 不破坏缓存纪律(11§4).
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def parse_story_datetime(iso_str: str) -> datetime | None:
    """解析故事时间 ISO 串为 aware datetime(统一转到 UTC). 非法返回 None."""
    if not iso_str:
        return None
    try:
        s = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(UTC)


def to_utc_iso(iso_str: str) -> str:
    """任意带时区的 ISO 时间 → UTC ISO(末尾 Z). 加载场景包与事件落库用."""
    dt = parse_story_datetime(iso_str)
    if dt is None:
        raise ValueError(f"时间必须带时区偏移或 Z: {iso_str}")
    text = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        text += f".{dt.microsecond:06d}".rstrip("0").rstrip(".")
    return f"{text}Z"


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
