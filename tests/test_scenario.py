"""场景包加载测试."""

from __future__ import annotations

from pathlib import Path

import pytest

from munagent.core import scenario as svc
from munagent.core.scenario import ScenarioCreate


def test_list_includes_builtin() -> None:
    items = svc.list_scenarios()
    ids = [s.id for s in items]
    assert "cabinet-crisis" in ids


def test_load_builtin_detail() -> None:
    detail = svc.load_scenario("cabinet-crisis")
    assert detail.title == "三人内阁危机"
    assert detail.readonly is True
    assert "manifest.yaml" in detail.files
    assert "seats/premier.yaml" in detail.files


def test_create_and_delete_user_scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "user_scenarios_dir", lambda: tmp_path)
    created = svc.create_scenario(ScenarioCreate(id="test-scenario", title="测试场景"))
    assert created.id == "test-scenario"
    assert (tmp_path / "test-scenario" / "manifest.yaml").is_file()
    svc.delete_scenario("test-scenario")
    assert not (tmp_path / "test-scenario").exists()
