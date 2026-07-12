"""FastAPI 路由测试."""

from __future__ import annotations

from fastapi.testclient import TestClient

from munagent.server.app import create_app


def test_list_scenarios_api() -> None:
    client = TestClient(create_app())
    res = client.get("/api/scenarios")
    assert res.status_code == 200
    data = res.json()
    assert any(s["id"] == "cabinet-crisis" for s in data)


def test_get_scenario_detail() -> None:
    client = TestClient(create_app())
    res = client.get("/api/scenarios/cabinet-crisis")
    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "三人内阁危机"
    assert "background.md" in body["files"]


def test_config_mask_key() -> None:
    client = TestClient(create_app())
    res = client.get("/api/config")
    assert res.status_code == 200
    ds = res.json()["providers"]["deepseek"]
    assert "api_key_masked" in ds
    assert "api_key" not in ds


def test_spa_index_when_built() -> None:
    from munagent.server.app import WEB_DIST

    if not WEB_DIST.is_dir():
        return
    client = TestClient(create_app())
    res = client.get("/")
    assert res.status_code == 200
    assert "MUNagent" in res.text


def test_design_put_file(tmp_path, monkeypatch) -> None:
    from munagent.core import scenario as svc
    from munagent.core.scenario import ScenarioCreate

    monkeypatch.setattr(svc, "user_scenarios_dir", lambda: tmp_path)
    svc.create_scenario(ScenarioCreate(id="api-test", title="API 测试"))
    client = TestClient(create_app())
    design = client.get("/api/scenarios/api-test/design")
    assert design.status_code == 200
    assert design.json()["readonly"] is False
    put = client.put("/api/scenarios/api-test/files/notes.md", json={"content": "# n\n"})
    assert put.status_code == 200
    got = client.get("/api/scenarios/api-test/files/notes.md")
    assert got.status_code == 200
    assert got.json()["content"].startswith("# n")
