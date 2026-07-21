"""设计器 .chats/ JSONL 持久化(无 Agent 逻辑)."""

from __future__ import annotations

import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from munagent.designer.scenario.package import _find_scenario

_CHAT_ID_RE = re.compile(r"^\d{14}-[a-f0-9]{4}$")
DEFAULT_CHAT_TITLE = "新对话"


class ChatMeta(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    turns: int = 0


def _chats_dir(root: Path) -> Path:
    new = root / ".chats"
    legacy = root / "chats"
    if new.is_dir():
        return new
    if legacy.is_dir():
        legacy.rename(new)
        return new
    return new


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _format_chat_id() -> str:
    d = datetime.now()
    stamp = d.strftime("%Y%m%d%H%M%S")
    return f"{stamp}-{random.randint(0, 0xFFFF):04x}"


def _assert_writable(source: Literal["builtin", "user"]) -> None:
    if source == "builtin":
        raise PermissionError("只读场景不可对话, 请先另存为副本")


def _read_chat_lines(path: Path) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    if not path.is_file():
        return lines
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        lines.append(json.loads(raw))
    return lines


def _write_chat_lines(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    if text:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def list_chats(scenario_id: str) -> list[ChatMeta]:
    root, _ = _find_scenario(scenario_id)
    chats_path = _chats_dir(root)
    if not chats_path.is_dir():
        return []
    items: list[ChatMeta] = []
    for file in chats_path.glob("*.jsonl"):
        records = _read_chat_lines(file)
        if not records or records[0].get("type") != "meta":
            continue
        meta = records[0]
        turns = sum(1 for r in records[1:] if r.get("type") == "user_message")
        mtime = datetime.fromtimestamp(file.stat().st_mtime, tz=timezone.utc).astimezone().isoformat(
            timespec="seconds"
        )
        items.append(
            ChatMeta(
                id=meta.get("id", file.stem),
                title=meta.get("title", file.stem),
                created_at=meta.get("created_at", mtime),
                updated_at=mtime,
                turns=turns,
            )
        )
    items.sort(key=lambda c: c.updated_at, reverse=True)
    return items


def is_default_chat_title(title: str) -> bool:
    return title.strip() == DEFAULT_CHAT_TITLE


def create_chat(scenario_id: str, title: str = DEFAULT_CHAT_TITLE) -> ChatMeta:
    root, source = _find_scenario(scenario_id)
    _assert_writable(source)
    chat_id = _format_chat_id()
    created_at = _now_iso()
    meta = {
        "type": "meta",
        "v": 1,
        "id": chat_id,
        "title": title,
        "created_at": created_at,
    }
    path = _chats_dir(root) / f"{chat_id}.jsonl"
    _write_chat_lines(path, [meta])
    return ChatMeta(id=chat_id, title=title, created_at=created_at, updated_at=created_at, turns=0)


def get_chat_records(scenario_id: str, chat_id: str) -> list[dict[str, Any]]:
    root, _ = _find_scenario(scenario_id)
    path = _chats_dir(root) / f"{chat_id}.jsonl"
    if not path.is_file():
        raise FileNotFoundError(f"对话不存在: {chat_id}")
    return _read_chat_lines(path)


def rename_chat(scenario_id: str, chat_id: str, title: str) -> ChatMeta:
    root, source = _find_scenario(scenario_id)
    _assert_writable(source)
    path = _chats_dir(root) / f"{chat_id}.jsonl"
    records = _read_chat_lines(path)
    if not records or records[0].get("type") != "meta":
        raise FileNotFoundError(f"对话不存在: {chat_id}")
    records[0]["title"] = title
    _write_chat_lines(path, records)
    chats = list_chats(scenario_id)
    found = next((c for c in chats if c.id == chat_id), None)
    if not found:
        raise FileNotFoundError(f"对话不存在: {chat_id}")
    return found


def delete_chat(scenario_id: str, chat_id: str) -> None:
    root, source = _find_scenario(scenario_id)
    _assert_writable(source)
    path = _chats_dir(root) / f"{chat_id}.jsonl"
    if not path.is_file():
        raise FileNotFoundError(f"对话不存在: {chat_id}")
    path.unlink()


def derive_todo(records: list[dict[str, Any]]) -> str | None:
    """取最后一条 todo 记录的 text; 无则 None."""
    for row in reversed(records):
        if row.get("type") == "todo":
            text = row.get("text")
            return text if isinstance(text, str) else None
    return None


def get_chat_detail(scenario_id: str, chat_id: str) -> tuple[list[dict[str, Any]], str | None]:
    records = get_chat_records(scenario_id, chat_id)
    return records, derive_todo(records)


def _next_seq(records: list[dict[str, Any]]) -> int:
    seqs = [int(r["seq"]) for r in records if r.get("type") != "meta" and isinstance(r.get("seq"), int)]
    return (max(seqs) if seqs else 0) + 1


def append_chat_record(
    scenario_id: str,
    chat_id: str,
    record: dict[str, Any],
    *,
    turn: int | None = None,
) -> dict[str, Any]:
    """追加一条 chat 记录(只追加 meta 行除外)."""
    root, source = _find_scenario(scenario_id)
    _assert_writable(source)
    path = _chats_dir(root) / f"{chat_id}.jsonl"
    if not path.is_file():
        raise FileNotFoundError(f"对话不存在: {chat_id}")
    existing = _read_chat_lines(path)
    if not existing or existing[0].get("type") != "meta":
        raise FileNotFoundError(f"对话不存在: {chat_id}")
    entry = dict(record)
    entry["seq"] = _next_seq(existing)
    entry["ts"] = _now_iso()
    if turn is not None:
        entry["turn"] = turn
    line = json.dumps(entry, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return entry
