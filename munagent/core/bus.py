"""事件总线: stage/commit_step/rollback_step + SQLite 持久化. 见 03§5-6, 07§2."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import aiosqlite

from munagent.core.events import (
    Event,
    Subscriber,
    materialize_visible_to,
    row_to_event,
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  scenario_id TEXT NOT NULL,
  created TEXT NOT NULL,
  config TEXT,
  master_seed INTEGER,
  status TEXT NOT NULL DEFAULT 'running'
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  story_time TEXT,
  real_time TEXT NOT NULL,
  type TEXT NOT NULL,
  actor TEXT NOT NULL,
  venue_id TEXT,
  group_id TEXT,
  scope TEXT NOT NULL,
  visible_to TEXT,
  payload TEXT NOT NULL,
  rng TEXT,
  UNIQUE(session_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_events_query ON events(session_id, venue_id, type, seq);
CREATE TABLE IF NOT EXISTS llm_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT,
  role TEXT NOT NULL,
  task TEXT NOT NULL,
  model TEXT NOT NULL,
  provider TEXT NOT NULL,
  prompt_tokens INTEGER NOT NULL,
  completion_tokens INTEGER NOT NULL,
  cache_hit_tokens INTEGER NOT NULL DEFAULT 0,
  cache_miss_tokens INTEGER NOT NULL DEFAULT 0,
  thinking_enabled INTEGER NOT NULL DEFAULT 0,
  real_time TEXT NOT NULL
);
"""


class EventBus:
    """事件总线: 单写者串行化, stage 缓冲, commit_step 批量落库. 见 03§5, 决策 D12."""

    def __init__(self, db_path: str, session_id: str) -> None:
        self._db_path = db_path
        self._session_id = session_id
        self._seq_counter = 0
        self._buffer: list[Event] = []
        self._subscribers: list[tuple[str, Subscriber]] = []
        self._db: aiosqlite.Connection | None = None

    async def init_db(self) -> None:
        """打开数据库连接并建表(若不存在)."""
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.executescript(SCHEMA_SQL)
        await self._db.commit()
        # 恢复 seq_counter
        async with self._db.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM events WHERE session_id = ?",
            (self._session_id,),
        ) as cur:
            row = await cur.fetchone()
            self._seq_counter = row[0] if row else 0

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def next_seq(self) -> int:
        """下一个可用 seq(含已 commit + 当前缓冲)."""
        return self._seq_counter + len(self._buffer) + 1

    def stage(
        self,
        event: Event,
        *,
        venue_seats: list[str] | None = None,
        group_members: list[str] | None = None,
        private_recipients: list[str] | None = None,
    ) -> Event:
        """暂存事件到步缓冲, 补全 seq 与 visible_to. 不落库. 见 D12."""
        if event.seq is None:
            event.seq = self.next_seq
        if event.session_id != self._session_id:
            raise ValueError(
                f"事件 session_id({event.session_id}) 与总线({self._session_id})不一致"
            )
        if event.visible_to is None and event.scope not in ("global", "dm-only"):
            event.visible_to = materialize_visible_to(
                event.scope,
                actor=event.actor,
                venue_seats=venue_seats,
                group_members=group_members,
                private_recipients=private_recipients,
            )
        self._buffer.append(event)
        return event

    # emit 作为 stage 的别名, 引擎内部习惯用
    emit = stage

    async def commit_step(self) -> list[Event]:
        """最小步结束: SQLite 事务批量落库, 推给订阅者, 清空缓冲. 见 D12."""
        if not self._buffer:
            return []
        if self._db is None:
            raise RuntimeError("EventBus 未 init_db")
        committed = list(self._buffer)
        try:
            for e in committed:
                await self._db.execute(
                    """INSERT INTO events
                    (session_id, seq, story_time, real_time, type, actor,
                     venue_id, group_id, scope, visible_to, payload, rng)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        e.session_id,
                        e.seq,
                        e.story_time,
                        e.real_time,
                        e.type,
                        e.actor,
                        e.venue_id,
                        e.group_id,
                        e.scope,
                        json.dumps(e.visible_to, ensure_ascii=False)
                        if e.visible_to is not None
                        else None,
                        json.dumps(e.payload, ensure_ascii=False),
                        json.dumps(e.rng, ensure_ascii=False)
                        if e.rng is not None
                        else None,
                    ),
                )
            await self._db.commit()
        except Exception:
            await self._db.rollback()
            raise
        self._seq_counter = committed[-1].seq or self._seq_counter
        self._buffer.clear()
        # 推给订阅者
        for viewer, cb in self._subscribers:
            for e in committed:
                if e.is_visible_to(viewer):
                    result = cb(e)
                    if hasattr(result, "__await__"):
                        await result
        return committed

    def rollback_step(self) -> None:
        """步失败: 丢弃步缓冲, 不产生孤儿事件. 见 D12."""
        self._buffer.clear()

    async def query(
        self,
        viewer: str,
        *,
        venue: str | None = None,
        group: str | None = None,
        types: list[str] | None = None,
        since_seq: int | None = None,
        limit: int | None = None,
    ) -> list[Event]:
        """查询 viewer 可见的事件(含已 commit + 当前缓冲). 见 03§5."""
        results: list[Event] = []
        # 已落库
        if self._db is not None:
            sql = "SELECT * FROM events WHERE session_id = ?"
            params: list[Any] = [self._session_id]
            if venue is not None:
                sql += " AND venue_id = ?"
                params.append(venue)
            if types:
                placeholders = ",".join("?" * len(types))
                sql += f" AND type IN ({placeholders})"
                params.extend(types)
            if since_seq is not None:
                sql += " AND seq >= ?"
                params.append(since_seq)
            sql += " ORDER BY seq ASC"
            if limit is not None:
                sql += " LIMIT ?"
                params.append(limit)
            async with self._db.execute(sql, params) as cur:
                rows = await cur.fetchall()
                for row in rows:
                    e = row_to_event(row)
                    if _visible(e, viewer, venue, group):
                        results.append(e)
        # 当前缓冲
        for e in self._buffer:
            if since_seq is not None and (e.seq or 0) < since_seq:
                continue
            if venue is not None and e.venue_id != venue:
                continue
            if types and e.type not in types:
                continue
            if _visible(e, viewer, venue, group):
                results.append(e)
        results.sort(key=lambda x: x.seq or 0)
        if limit is not None:
            results = results[:limit]
        return results

    def subscribe(self, viewer: str, callback: Subscriber) -> None:
        """注册订阅者: commit 后按 viewer 过滤推送."""
        self._subscribers.append((viewer, callback))

    async def create_session(
        self,
        scenario_id: str,
        master_seed: int,
        config: dict | None = None,
    ) -> None:
        if self._db is None:
            raise RuntimeError("EventBus 未 init_db")
        import json

        await self._db.execute(
            """INSERT OR REPLACE INTO sessions
            (id, scenario_id, created, config, master_seed, status)
            VALUES (?, ?, ?, ?, ?, 'running')""",
            (
                self._session_id,
                scenario_id,
                datetime.now(UTC).isoformat(),
                json.dumps(config, ensure_ascii=False) if config else None,
                master_seed,
            ),
        )
        await self._db.commit()

    async def set_session_status(self, status: str) -> None:
        if self._db is None:
            raise RuntimeError("EventBus 未 init_db")
        await self._db.execute(
            "UPDATE sessions SET status = ? WHERE id = ?",
            (status, self._session_id),
        )
        await self._db.commit()

    async def get_session(self) -> dict[str, Any] | None:
        if self._db is None:
            return None
        async with self._db.execute(
            "SELECT id, scenario_id, created, config, master_seed, status "
            "FROM sessions WHERE id = ?",
            (self._session_id,),
        ) as cur:
            row = await cur.fetchone()
            if row is None:
                return None
            return {
                "id": row[0],
                "scenario_id": row[1],
                "created": row[2],
                "config": json.loads(row[3]) if row[3] else None,
                "master_seed": row[4],
                "status": row[5],
            }

    async def record_usage(self, record: Any) -> None:
        """记录 LLM 用量到 llm_usage 表(不进事件日志)."""
        if self._db is None:
            return
        await self._db.execute(
            """INSERT INTO llm_usage
            (session_id, role, task, model, provider,
             prompt_tokens, completion_tokens,
             cache_hit_tokens, cache_miss_tokens, thinking_enabled, real_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                self._session_id,
                record.role,
                record.task,
                record.model,
                record.provider,
                record.prompt_tokens,
                record.completion_tokens,
                record.cache_hit_tokens,
                record.cache_miss_tokens,
                1 if record.thinking_enabled else 0,
                record.real_time,
            ),
        )
        await self._db.commit()


def _visible(e: Event, viewer: str, venue: str | None, group: str | None) -> bool:
    """query 内部用: scope 过滤 + venue/group 过滤."""
    if not e.is_visible_to(viewer):
        return False
    if venue is not None and e.venue_id != venue:
        return False
    if group is not None and e.group_id != group:
        return False
    return True
