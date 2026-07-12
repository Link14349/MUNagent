"""时区归一化测试."""

from __future__ import annotations

import pytest

from munagent.core.timezone import parse_story_datetime, to_utc_iso


def test_to_utc_iso_from_offset() -> None:
    assert to_utc_iso("2026-03-15T09:00:00+08:00") == "2026-03-15T01:00:00Z"


def test_to_utc_iso_from_z() -> None:
    assert to_utc_iso("2026-03-15T01:00:00Z") == "2026-03-15T01:00:00Z"


def test_to_utc_iso_rejects_naive() -> None:
    with pytest.raises(ValueError, match="时区"):
        to_utc_iso("2026-03-15T09:00:00")


def test_parse_story_datetime_compares_offsets() -> None:
    a = parse_story_datetime("2026-03-15T09:00:00+08:00")
    b = parse_story_datetime("2026-03-15T01:00:00Z")
    assert a == b
