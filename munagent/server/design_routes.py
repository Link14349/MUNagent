"""设计器 REST 路由 — 薄封装, 业务在 core/."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse

from munagent.designer.revert import RevertDriftError, revert_file_edit
from munagent.designer.scenario import chats as chat_svc
from munagent.designer.scenario import package as scenario_svc
from munagent.designer.scenario import files as file_svc
from munagent.designer.scenario import history as history_svc
from munagent.designer.scenario.package import DuplicateScenarioRequest
from munagent.designer.scenario.files import FileContent, RenameFileRequest
from munagent.designer.scenario.history import CreateSnapshotRequest
from munagent.server.design_schemas import (
    ChatCreateRequest,
    ChatDetailResponse,
    ChatRenameRequest,
    DesignerState,
    PutFileBody,
    RevertConflictBody,
    SendMessageRequest,
    SendMessageResponse,
)
from munagent.server.design_task import design_tasks

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
            active_task=design_tasks.get_active_task(scenario_id),
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
        result = history_svc.restore_snapshot(
            scenario_id,
            snap_id,
            active_task=design_tasks.has_active_task(scenario_id),
        )
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


@router.get("/chats/{chat_id}", response_model=ChatDetailResponse)
def get_chat(scenario_id: str, chat_id: str) -> ChatDetailResponse:
    try:
        records, todo = chat_svc.get_chat_detail(scenario_id, chat_id)
        return ChatDetailResponse(records=records, todo=todo)
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


@router.get("/design/events")
async def design_events(
    scenario_id: str,
    request: Request,
    after: int | None = Query(None, ge=0),
) -> StreamingResponse:
    try:
        _find_scenario_for_sse(scenario_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    last_event_id = request.headers.get("last-event-id")
    if after is None and last_event_id:
        try:
            after = int(last_event_id)
        except ValueError:
            after = None

    async def stream():
        async for event in design_tasks.subscribe(scenario_id, after):
            if event.get("type") == "heartbeat":
                yield ": heartbeat\n\n"
                continue
            payload = json.dumps(event, ensure_ascii=False)
            seq = event.get("seq")
            yield f"id: {seq}\nevent: message\ndata: {payload}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/design/abort")
def abort_design_task(scenario_id: str) -> dict:
    design_tasks.abort(scenario_id)
    return {"status": "aborting"}


@router.post("/chats/{chat_id}/messages", status_code=202, response_model=SendMessageResponse)
async def send_chat_message(scenario_id: str, chat_id: str, body: SendMessageRequest) -> SendMessageResponse:
    try:
        task_id = await design_tasks.launch_message_task(
            scenario_id,
            chat_id,
            body.text.strip(),
            context_file=body.context_file,
        )
        return SendMessageResponse(task_id=task_id)
    except Exception as exc:
        raise _http_from_exc(exc) from exc


@router.post("/chats/{chat_id}/revert/{seq}")
def revert_chat_edit(scenario_id: str, chat_id: str, seq: int) -> dict:
    if design_tasks.has_active_task(scenario_id):
        raise HTTPException(status_code=409, detail="有 Agent 任务在运行, 请先中止")
    try:
        record = revert_file_edit(scenario_id, chat_id, seq)
        design_tasks.emit(scenario_id, {"type": "record_appended", "chat_id": chat_id, "record": record})
        path = _file_edit_path(scenario_id, chat_id, seq)
        if path:
            design_tasks.emit(scenario_id, {"type": "files_changed", "paths": [path]})
        return {"record": record}
    except RevertDriftError as exc:
        raise HTTPException(
            status_code=409,
            detail=RevertConflictBody(
                detail=exc.message,
                path=exc.path,
                current_content=exc.current_content,
                expected_content=exc.expected_content,
                original_content=exc.original_content,
            ).model_dump(),
        ) from exc
    except Exception as exc:
        raise _http_from_exc(exc) from exc


def _find_scenario_for_sse(scenario_id: str) -> None:
    from munagent.designer.scenario.package import _find_scenario

    _find_scenario(scenario_id)


def _file_edit_path(scenario_id: str, chat_id: str, seq: int) -> str | None:
    for row in chat_svc.get_chat_records(scenario_id, chat_id):
        if row.get("seq") == seq and row.get("type") == "file_edit":
            path = row.get("path")
            return path if isinstance(path, str) else None
    return None
