"""设计器 REST 路由 — 薄封装, 业务在 core/."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from munagent.core import chats as chat_svc
from munagent.core import scenario as scenario_svc
from munagent.core import scenario_files as file_svc
from munagent.core import scenario_history as history_svc
from munagent.core.scenario import DuplicateScenarioRequest
from munagent.core.scenario_files import FileContent, RenameFileRequest
from munagent.core.scenario_history import CreateSnapshotRequest
from munagent.server.design_schemas import (
    ChatCreateRequest,
    ChatRenameRequest,
    DesignerState,
    PutFileBody,
)

router = APIRouter(prefix="/api/scenarios/{scenario_id}")


def _http_from_exc(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=409, detail=str(exc))
    raise exc


@router.get("/design", response_model=DesignerState)
def get_design_state(scenario_id: str) -> DesignerState:
    try:
        title, readonly, file_tree, validation = file_svc.scenario_design_meta(scenario_id)
        chats = chat_svc.list_chats(scenario_id)
        return DesignerState(
            title=title,
            readonly=readonly,
            active_task=None,
            chats=chats,
            validation=validation,
            file_tree=file_tree,
        )
    except Exception as exc:
        raise _http_from_exc(exc) from exc


@router.get("/files/{file_path:path}", response_model=FileContent)
def get_file(scenario_id: str, file_path: str) -> FileContent:
    try:
        return file_svc.get_file(scenario_id, file_path)
    except Exception as exc:
        raise _http_from_exc(exc) from exc


@router.put("/files/{file_path:path}")
def put_file(scenario_id: str, file_path: str, body: PutFileBody) -> dict:
    try:
        result = file_svc.put_file(scenario_id, file_path, body.content)
        return {"validation": result.validation}
    except Exception as exc:
        raise _http_from_exc(exc) from exc


@router.delete("/files/{file_path:path}")
def delete_file(scenario_id: str, file_path: str) -> dict:
    try:
        result = file_svc.delete_file(scenario_id, file_path)
        return {"validation": result.validation}
    except Exception as exc:
        raise _http_from_exc(exc) from exc


@router.post("/files/{file_path:path}/rename")
def rename_file(scenario_id: str, file_path: str, body: RenameFileRequest) -> dict:
    try:
        result = file_svc.rename_file(scenario_id, file_path, body.new_path)
        return {"validation": result.validation}
    except Exception as exc:
        raise _http_from_exc(exc) from exc


@router.post("/duplicate")
def duplicate_scenario(scenario_id: str, body: DuplicateScenarioRequest) -> dict:
    try:
        detail = scenario_svc.duplicate_scenario(scenario_id, body.new_id, body.new_title)
        return {"id": detail.id}
    except Exception as exc:
        raise _http_from_exc(exc) from exc


@router.post("/export")
def export_scenario(scenario_id: str, include_raw: bool = Query(False)) -> Response:
    try:
        data = scenario_svc.export_scenario_zip(scenario_id, include_raw=include_raw)
        return Response(
            content=data,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{scenario_id}.zip"'},
        )
    except Exception as exc:
        raise _http_from_exc(exc) from exc


@router.get("/history")
def list_history(scenario_id: str) -> list:
    try:
        return [s.model_dump() for s in history_svc.list_snapshots(scenario_id)]
    except Exception as exc:
        raise _http_from_exc(exc) from exc


@router.post("/history")
def create_history(scenario_id: str, body: CreateSnapshotRequest) -> dict:
    try:
        snap = history_svc.create_snapshot(scenario_id, kind="manual", note=body.note)
        return snap.model_dump()
    except Exception as exc:
        raise _http_from_exc(exc) from exc


@router.get("/history/{snap_id}/diff")
def history_diff(scenario_id: str, snap_id: str) -> list:
    try:
        return [e.model_dump() for e in history_svc.history_diff(scenario_id, snap_id)]
    except Exception as exc:
        raise _http_from_exc(exc) from exc


@router.post("/history/{snap_id}/restore")
def restore_history(scenario_id: str, snap_id: str) -> dict:
    try:
        result = history_svc.restore_snapshot(scenario_id, snap_id, active_task=False)
        return {"validation": result.validation}
    except Exception as exc:
        raise _http_from_exc(exc) from exc


@router.delete("/history/{snap_id}")
def delete_history(scenario_id: str, snap_id: str) -> dict:
    try:
        history_svc.delete_snapshot(scenario_id, snap_id)
        return {"status": "deleted"}
    except Exception as exc:
        raise _http_from_exc(exc) from exc


@router.get("/chats")
def list_chats(scenario_id: str) -> list:
    try:
        return [c.model_dump() for c in chat_svc.list_chats(scenario_id)]
    except Exception as exc:
        raise _http_from_exc(exc) from exc


@router.post("/chats")
def create_chat(scenario_id: str, body: ChatCreateRequest) -> dict:
    try:
        return chat_svc.create_chat(scenario_id, body.title).model_dump()
    except Exception as exc:
        raise _http_from_exc(exc) from exc


@router.get("/chats/{chat_id}")
def get_chat(scenario_id: str, chat_id: str) -> list:
    try:
        return chat_svc.get_chat_records(scenario_id, chat_id)
    except Exception as exc:
        raise _http_from_exc(exc) from exc


@router.patch("/chats/{chat_id}")
def patch_chat(scenario_id: str, chat_id: str, body: ChatRenameRequest) -> dict:
    try:
        return chat_svc.rename_chat(scenario_id, chat_id, body.title).model_dump()
    except Exception as exc:
        raise _http_from_exc(exc) from exc


@router.delete("/chats/{chat_id}")
def delete_chat(scenario_id: str, chat_id: str) -> dict:
    try:
        chat_svc.delete_chat(scenario_id, chat_id)
        return {"status": "deleted"}
    except Exception as exc:
        raise _http_from_exc(exc) from exc
