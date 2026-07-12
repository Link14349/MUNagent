"""设计器 API 请求/响应 schema."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from munagent.scenario.chats import ChatMeta
from munagent.scenario.package import DuplicateScenarioRequest
from munagent.scenario.files import FileContent, FileNode, PutFileResult, RenameFileRequest, ValidationIssue
from munagent.scenario.history import CreateSnapshotRequest, HistoryDiffEntry, HistorySnapshot


class ActiveTask(BaseModel):
    task_id: str
    chat_id: str
    turn: int


class DesignerState(BaseModel):
    title: str
    readonly: bool
    active_task: ActiveTask | None = None
    chats: list[ChatMeta] = Field(default_factory=list)
    validation: list[ValidationIssue] = Field(default_factory=list)
    file_tree: list[FileNode] = Field(default_factory=list)


class PutFileBody(BaseModel):
    content: str


class ChatCreateRequest(BaseModel):
    title: str = "新对话"


class ChatRenameRequest(BaseModel):
    title: str


class ScenarioSummaryEnriched(BaseModel):
    id: str
    title: str
    author: str = ""
    version: str = ""
    source: Literal["builtin", "user"]
    readonly: bool = False
    chat_count: int = 0
    last_chat_at: str | None = None
