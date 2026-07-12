"""FastAPI 路由."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from munagent.scenario import chats as chat_svc
from munagent.scenario import package as scenario_svc
from munagent.scenario.package import ScenarioCreate, ScenarioDetail, ScenarioSummary
from munagent.server.config_service import get_config_public, put_config, test_config
from munagent.server.design_schemas import ScenarioSummaryEnriched
from munagent.server.schemas import ConfigPublic, ConfigTestRequest, ConfigTestResponse, ConfigUpdate

router = APIRouter(prefix="/api")


@router.get("/scenarios", response_model=list[ScenarioSummary])
def list_scenarios() -> list[ScenarioSummary]:
    return scenario_svc.list_scenarios()


@router.get("/scenarios-enriched", response_model=list[ScenarioSummaryEnriched])
def list_scenarios_enriched() -> list[ScenarioSummaryEnriched]:
    items: list[ScenarioSummaryEnriched] = []
    for s in scenario_svc.list_scenarios():
        try:
            chats = chat_svc.list_chats(s.id)
        except FileNotFoundError:
            chats = []
        items.append(
            ScenarioSummaryEnriched(
                id=s.id,
                title=s.title,
                author=s.author,
                version=s.version,
                source=s.source,
                readonly=s.readonly,
                chat_count=len(chats),
                last_chat_at=chats[0].updated_at if chats else None,
            )
        )
    return items


@router.post("/scenarios", response_model=ScenarioDetail)
def create_scenario(body: ScenarioCreate) -> ScenarioDetail:
    try:
        return scenario_svc.create_scenario(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/scenarios/{scenario_id}", response_model=ScenarioDetail)
def get_scenario(scenario_id: str) -> ScenarioDetail:
    try:
        return scenario_svc.load_scenario(scenario_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/scenarios/{scenario_id}", response_model=ScenarioDetail)
def update_scenario(scenario_id: str, body: dict[str, str]) -> ScenarioDetail:
    try:
        return scenario_svc.save_scenario_files(scenario_id, body)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/scenarios/{scenario_id}")
def delete_scenario(scenario_id: str) -> dict[str, str]:
    try:
        scenario_svc.delete_scenario(scenario_id)
        return {"status": "deleted"}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/config", response_model=ConfigPublic)
def get_config() -> ConfigPublic:
    return get_config_public()


@router.put("/config", response_model=ConfigPublic)
def update_config(body: ConfigUpdate) -> ConfigPublic:
    try:
        return put_config(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/config/test", response_model=ConfigTestResponse)
async def config_test(body: ConfigTestRequest) -> ConfigTestResponse:
    return await test_config(body)
