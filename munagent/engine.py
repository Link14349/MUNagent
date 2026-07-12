"""推演引擎(P2): 完整会议机制.

支持: Mod/Unmod/Voting 三阶段、主持席路由、动议处理、四类指令、DM 判定完整五步.
"""

from __future__ import annotations

import difflib
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from munagent.agents.base import TaskSpec
from munagent.agents.chair import AppealRulingAction, ChairAgent, build_chair_g
from munagent.agents.delegate import (
    DelegateAgent,
    DelegateTurnAction,
    DelegateVoteAction,
    PresidingCaucusSwitch,
    PresidingMotionRuling,
    PresidingNextSpeaker,
    build_delegate_g_global,
)
from munagent.agents.dm import DMAgent, build_dm_g, outcome_tier
from munagent.config.models import MunagentConfig
from munagent.core.bus import EventBus
from munagent.core.events import Event
from munagent.core.render import render
from munagent.core.scenario import Scenario, SeatSpec, VenueSpec
from munagent.core.state_machine import GroupState, VenueStateMachine
from munagent.llm.client import LLMClient


ANSI_COLORS = {
    "white": "\033[97m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "red": "\033[91m",
    "cyan": "\033[96m",
    "magenta": "\033[95m",
    "dim": "\033[90m",
    "reset": "\033[0m",
}


def colorize(text: str, color: str) -> str:
    return f"{ANSI_COLORS.get(color, '')}{text}{ANSI_COLORS['reset']}"


@dataclass
class RunResult:
    session_id: str
    total_steps: int
    events: list[Event] = field(default_factory=list)


class Engine:
    """P2 推演引擎: 单会场完整会议机制 + 主持席路由."""

    def __init__(
        self,
        scenario: Scenario,
        config: MunagentConfig,
        *,
        master_seed: int | None = None,
        max_steps: int = 30,
        db_path: str = "munagent.db",
        usage_sink: Any = None,
        llm_transport: Any = None,
        on_event: Any = None,
    ) -> None:
        self.scenario = scenario
        self.config = config
        self.master_seed = master_seed if master_seed is not None else secrets.randbits(63)
        self.max_steps = max_steps
        self.db_path = db_path
        self.session_id = f"{scenario.id}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        self._llm: LLMClient | None = None
        self._llm_transport = llm_transport
        self._usage_sink = usage_sink
        self._on_event = on_event
        self._l3_start_seq: dict[str, int] = {}  # viewer -> 纪元起点 seq(11§3)
        self._directive_index: dict[str, dict] = {}  # directive id/title -> payload(投票取正文)
        self._directive_count = 0  # 本会话已提交指令数(进 L4 进度提示)
        # 草案线(D16): 联合指令/公报的git式版本树. "D1.2" -> {status, versions:[info...]}
        self._doc_lines: dict[str, dict] = {}
        self._line_seq = 0  # 当前议程序号下的递交序(线号分配计数)
        self._agenda_no = 1  # 正式 Mod 会议序号(编号 D<n>.<递交序> 的 n)
        # 运行时 stats(tags/values 的当前值): 从场景包初始化, DM 判定的 stat_changes 落在这里
        self._stats: dict[str, dict] = {
            e.id: {"label": e.label, "owner": e.owner,
                   "tags": dict(e.tags or {}), "values": dict(e.values or {})}
            for e in scenario.stats.entities
        }

    def _emit_committed(self, events: list[Event]) -> None:
        if self._on_event is not None:
            for e in events:
                self._on_event(e)

    def _make_llm(self, usage_sink=None) -> LLMClient:
        if self._llm is None:
            kwargs: dict = {}
            if self._llm_transport is not None:
                kwargs["transport"] = self._llm_transport
            sinks = []
            if self._usage_sink is not None:
                sinks.append(self._usage_sink)
            if usage_sink is not None:
                sinks.append(usage_sink)
            if sinks:
                def combined_sink(record):
                    for s in sinks:
                        s(record)
                kwargs["usage_sink"] = combined_sink
            self._llm = LLMClient(self.config, **kwargs)
        return self._llm

    async def run(self) -> RunResult:
        bus = EventBus(self.db_path, self.session_id)
        await bus.init_db()
        existing = await bus.query("god")
        is_resume = len(existing) > 0

        session_row = await bus.get_session()
        if session_row is None:
            await bus.create_session(
                self.scenario.id,
                master_seed=self.master_seed,
                config={"max_steps": self.max_steps},
            )
        elif session_row.get("master_seed") is not None:
            self.master_seed = int(session_row["master_seed"])

        # 预算追踪(必须在 _make_llm 之前定义)
        total_tokens = 0
        token_budget = self.config.engine.session_max_tokens
        consecutive_failures: dict[str, int] = {}  # role -> 连续失败次数

        def _on_usage(record):
            nonlocal total_tokens
            total_tokens += record.prompt_tokens + record.completion_tokens

        llm = self._make_llm(usage_sink=_on_usage)
        venue_spec = self.scenario.venues[0]
        seat_specs = self.scenario.seats_of(venue_spec.id)
        seat_ids = [s.id for s in seat_specs]
        delegate_g = build_delegate_g_global(self.scenario, venue_spec.id)

        # G 段预热(见 11§6)
        if self.config.engine.cache_warmup:
            await self._warmup_g_segment(llm, delegate_g)

        sm = VenueStateMachine(
            venue_id=venue_spec.id,
            seat_ids=seat_ids,
            initial_phase="Opening",  # 统一从 Opening 开始, 再转到 initial_phase
            start_story_time=self.scenario.manifest.start_story_time,
            per_mod_speech=venue_spec.clock_rate.per_mod_speech,
            per_unmod_round=venue_spec.clock_rate.per_unmod_round,
            max_speeches=self.config.engine.mod_max_speeches,
            unmod_rounds=self.config.engine.unmod_rounds,
            presiding_seat=venue_spec.presiding_seat,
        )

        delegates = {
            s.id: DelegateAgent(llm, s, delegate_g)
            for s in seat_specs
        }
        chair = ChairAgent(llm, venue_spec.id, seat_ids, g_chair=build_chair_g(self.scenario))
        self._chair = chair  # 判定后跳时决策用(见 _adjudicate)
        dm = DMAgent(llm, self.master_seed, g_dm=build_dm_g(self.scenario))
        from munagent.agents.recorder import RecorderAgent, estimate_tokens
        recorder = RecorderAgent(llm)

        # 纪元机制: 每视角追踪摘要(L2)和 L3 累积量
        epoch_threshold = self.config.engine.epoch_l3_max_tokens
        summaries: dict[str, str] = {}  # viewer -> L2文本(=章节拼接, 消费端只读这个)
        l2_chapters: dict[str, list[str]] = {}  # viewer -> 章节列表(追加式, 见05§3.4)
        # 续推场景: 从存档回灌章节(consolidated章替换此前全部章节)
        for e in await bus.query("god", types=["summary_written"]):
            _viewer = e.payload.get("viewer", "")
            _text = e.payload.get("text", "")
            if not _viewer or not _text:
                continue
            if e.payload.get("kind") == "consolidated":
                l2_chapters[_viewer] = [_text]
            else:
                l2_chapters.setdefault(_viewer, []).append(_text)
        for _viewer, _chs in l2_chapters.items():
            summaries[_viewer] = "\n\n".join(_chs)
        l3_accum: dict[str, list[Event]] = {}  # viewer -> 本纪元 L3 事件
        self._l3_start_seq = {}  # viewer -> 纪元起点 seq(之前的事件已被压进 L2)
        self._directive_index = {}  # directive_id/title -> 指令 payload(投票时取正文)
        # 续推场景: 从已存档事件回灌指令索引/草案线/计数(内存只是缓存, 事件日志才是事实源)
        self._doc_lines = {}
        self._line_seq = 0
        self._agenda_no = 1
        for e in await bus.query("god", types=["phase_change"]):
            _to = e.payload.get("to")
            _fr = e.payload.get("from")
            if _to == "ModeratedCaucus":
                if "agenda_no" in e.payload:
                    self._agenda_no = int(e.payload["agenda_no"])
                elif _fr == "UnmoderatedCaucus":
                    self._agenda_no += 1
                elif _fr == "Opening":
                    self._agenda_no = 1
        for e in await bus.query("god", types=["directive_submitted"]):
            _p = e.payload
            _info = {"directive_id": _p.get("directive_id", ""), "kind": _p.get("kind", ""),
                     "title": _p.get("title", ""), "body": _p.get("body", ""),
                     "author": _p.get("author", ""),
                     "co_sponsors": list(_p.get("co_sponsors") or [])}
            if _info["directive_id"]:
                self._directive_index[_info["directive_id"]] = _info
            if _info["title"]:
                self._directive_index[_info["title"]] = _info
            _line_no = _p.get("doc_line")
            if _line_no:
                self._register_doc_version({"doc_line": _line_no}, _info)
                self._directive_index[_line_no] = _info
                if _line_no.startswith(f"D{self._agenda_no}."):
                    _seq = int(_line_no.partition(".")[2] or 0)
                    self._line_seq = max(self._line_seq, _seq)
        for e in await bus.query("god", types=["note_delivered"]):
            _did = e.payload.get("directive_id", "")
            if _did in self._directive_index:
                self._directive_index[_did]["delivered"] = True
                self._directive_index[_did]["recipient"] = e.payload.get("recipient")
        for e in await bus.query("god", types=["directive_status"]):
            _p = e.payload
            _line_no = str(_p.get("directive_id", "")).partition("-v")[0]
            if _line_no in self._doc_lines and _p.get("status") in ("passed", "rejected", "superseded"):
                self._doc_lines[_line_no]["status"] = {
                    "passed": "merged", "rejected": "rejected", "superseded": "superseded",
                }[_p["status"]]
        self._directive_count = len(
            {v["directive_id"] for v in self._directive_index.values() if v["directive_id"]}
        )

        # 预算追踪
        consecutive_failures: dict[str, int] = {}  # role -> 连续失败次数

        all_events: list[Event] = []
        step = 0

        if is_resume:
            sm.replay_from_events(existing)
        else:
            # Opening → 初始阶段
            initial = venue_spec.initial_phase
            phase_payload: dict = {"from": "Opening", "to": initial, "reason": "会议开始"}
            if initial == "ModeratedCaucus":
                self._on_enter_moderated_caucus("Opening")
                phase_payload["agenda_no"] = self._agenda_no
            bus.stage(
                Event(
                    session_id=self.session_id,
                    story_time=sm.story_time,
                    type="phase_change",
                    actor="chair",
                    venue_id=sm.venue_id,
                    scope="venue",
                    payload=phase_payload,
                ),
                venue_seats=sm.active_seat_ids,
            )
            committed = await bus.commit_step()
            all_events.extend(committed)
            self._emit_committed(committed)
            sm.transition(initial)

        while step < self.max_steps and sm.phase != "Adjourned":
            step += 1
            if sm.phase == "ModeratedCaucus":
                committed = await self._run_mod_step(bus, sm, delegates, chair, dm, venue_spec, seat_ids, summaries)
            elif sm.phase == "UnmoderatedCaucus":
                committed = await self._run_unmod_phase(bus, sm, delegates, chair, venue_spec, seat_ids, summaries, dm)
            elif sm.phase == "Voting":
                committed = await self._run_voting_step(bus, sm, delegates, chair, venue_spec, seat_ids, summaries, dm)
            else:
                break

            all_events.extend(committed)

            # 在席席位不足以议事时闭会
            if len(sm.active_seat_ids) < 2 and sm.phase != "Adjourned":
                if sm.can_transition("Adjourned"):
                    prev_phase = sm.phase
                    sm.transition("Adjourned")
                    bus.stage(
                        Event(
                            session_id=self.session_id,
                            story_time=sm.story_time,
                            type="phase_change",
                            actor="chair",
                            venue_id=sm.venue_id,
                            scope="venue",
                            payload={"from": prev_phase, "to": "Adjourned",
                                     "reason": "在席席位不足, 会议无法继续"},
                        ),
                        venue_seats=sm.active_seat_ids,
                    )
                    committed = await bus.commit_step()
                    all_events.extend(committed)
                    self._emit_committed(committed)
                    break

            # 纪元检查
            await self._check_epochs(
                bus, sm, recorder, summaries, l2_chapters, l3_accum, committed, seat_ids, epoch_threshold
            )

            # token 预算熔断
            if total_tokens >= token_budget:
                bus.stage(
                    Event(
                        session_id=self.session_id,
                        story_time=sm.story_time,
                        type="session_control",
                        actor="system",
                        venue_id=sm.venue_id,
                        scope="dm-only",
                        payload={"action": "pause", "detail": f"token 预算耗尽({total_tokens}/{token_budget})"},
                    ),
                )
                await bus.commit_step()
                import sys
                print(f"\n[熔断] token 预算耗尽({total_tokens}/{token_budget}), 推演暂停。", file=sys.stderr)
                break

            # 预算检查
            if sm.phase == "ModeratedCaucus" and sm.budget_exceeded:
                committed = await self._chair_phase_decision(bus, sm, chair, seat_ids)
                all_events.extend(committed)

        await bus.set_session_status("ended")
        all_committed = await bus.query("god")
        await bus.close()
        if self._llm is not None:
            await self._llm.aclose()
        return RunResult(
            session_id=self.session_id,
            total_steps=step,
            events=all_committed,
        )

    # --- 时间推进 ---

    @staticmethod
    def _pending_effect_times(
        adjudication_events: list[Event],
        story_time: str,
        *,
        extra: str = "",
    ) -> list[str]:
        """汇总故事时间尚未到达的 takes_effect_at(在途生效点)."""
        from munagent.core.timezone import parse_story_datetime, to_utc_iso

        cur = parse_story_datetime(story_time)
        if cur is None:
            return []
        pending: list[str] = []
        for e in adjudication_events:
            te = e.payload.get("takes_effect_at") or ""
            if not te:
                continue
            try:
                te_norm = to_utc_iso(te)
            except ValueError:
                continue
            te_dt = parse_story_datetime(te_norm)
            if te_dt and te_dt > cur:
                pending.append(te_norm)
        if extra:
            try:
                extra_norm = to_utc_iso(extra)
            except ValueError:
                extra_norm = ""
            if extra_norm:
                extra_dt = parse_story_datetime(extra_norm)
                if extra_dt and extra_dt > cur and extra_norm not in pending:
                    pending.append(extra_norm)
        return pending

    @staticmethod
    def _format_pending_effects(
        adjudication_events: list[Event],
        story_time: str,
        *,
        extra_directive_id: str = "",
        extra_takes_effect_at: str = "",
    ) -> str:
        """主席 clock_decision 用的在途生效点文本."""
        extra = extra_takes_effect_at if extra_takes_effect_at else ""
        times = Engine._pending_effect_times(adjudication_events, story_time, extra=extra)
        if not times:
            return ""
        # 按时间排序, 关联 directive_id
        id_by_time: dict[str, str] = {}
        from munagent.core.timezone import to_utc_iso

        for e in adjudication_events:
            te = e.payload.get("takes_effect_at") or ""
            if not te:
                continue
            try:
                te_norm = to_utc_iso(te)
            except ValueError:
                continue
            id_by_time[te_norm] = e.payload.get("directive_id", "")
        if extra_takes_effect_at and extra_directive_id:
            try:
                id_by_time[to_utc_iso(extra_takes_effect_at)] = extra_directive_id
            except ValueError:
                pass
        lines = []
        for te in sorted(times):
            did = id_by_time.get(te, "")
            label = f"{did} " if did else ""
            lines.append(f"- {label}生效于 {te}")
        return "\n".join(lines)

    @staticmethod
    def _validate_clock_advance(
        current: str,
        target: str,
        max_jump_hours: int = 24,
        pending_effect_times: list[str] | None = None,
    ) -> str | None:
        """校验主席跳时目标: 只向前、限步长、不得越过在途生效点; 非法返回 None."""
        from datetime import datetime, timedelta

        from munagent.core.timezone import parse_story_datetime, to_utc_iso

        cur = parse_story_datetime(current)
        if cur is None:
            return None
        tgt = parse_story_datetime(target)
        if tgt is None:
            return None
        if tgt <= cur or tgt - cur > timedelta(hours=max_jump_hours):
            return None
        if pending_effect_times:
            future: list[datetime] = []
            for raw in pending_effect_times:
                try:
                    norm = to_utc_iso(raw)
                except ValueError:
                    continue
                dt = parse_story_datetime(norm)
                if dt and dt > cur:
                    future.append(dt)
            if future and tgt > min(future):
                return None
        try:
            return to_utc_iso(target)
        except ValueError:
            return None

    # --- 草案线(D16, 见06§2) ---

    def _on_enter_moderated_caucus(self, from_phase: str) -> None:
        """进入正式 Mod 时更新议程序号. 每次 Unmod 归来开启新序号并从 .1 重新编号."""
        if from_phase == "Opening":
            self._agenda_no = 1
            self._line_seq = 0
        elif from_phase == "UnmoderatedCaucus":
            self._agenda_no += 1
            self._line_seq = 0

    def _phase_change_to_mod_payload(self, from_phase: str, reason: str) -> dict:
        self._on_enter_moderated_caucus(from_phase)
        return {
            "from": from_phase,
            "to": "ModeratedCaucus",
            "reason": reason,
            "agenda_no": self._agenda_no,
        }

    @staticmethod
    def _diff_summary(old_body: str, new_body: str, max_lines: int = 20) -> str:
        """程序生成的增删摘要(确定性纯函数); 提交时算好存payload, render保持纯函数."""
        diff = list(difflib.unified_diff(
            old_body.splitlines(), new_body.splitlines(), lineterm="", n=0,
        ))[2:]  # 去掉 ---/+++ 头
        diff = [ln for ln in diff if not ln.startswith("@@")]
        if not diff:
            return "(无文本变化)"
        if len(diff) > max_lines:
            diff = diff[:max_lines] + [f"…(另有{len(diff) - max_lines}行改动)"]
        return "\n".join(diff)

    def _resolve_doc_ref(self, ref: str) -> tuple[str | None, dict | None]:
        """把代表填的编号/版本号/标题解析为(线号, 该线最新版info)."""
        ref = (ref or "").strip()
        if not ref:
            return None, None
        line_no = ref.partition("-v")[0]
        line = self._doc_lines.get(line_no)
        if line is None:
            for ln, l in self._doc_lines.items():  # 标题兜底
                if any(v["title"] == ref for v in l["versions"]):
                    line_no, line = ln, l
                    break
        if line is None:
            return None, None
        # 显式版本号则取该版, 否则最新版
        explicit = next((v for v in line["versions"] if v["directive_id"] == ref), None)
        return line_no, (explicit or line["versions"][-1])

    def _assign_doc_number(self, d, author: str) -> dict:
        """联合指令/公报的线号/版本分配与修订/分叉判定(D16). 确定性纯计数."""
        agenda_no = self._agenda_no
        if d.revises:
            line_no, parent = self._resolve_doc_ref(d.revises)
            if line_no is not None and parent is not None:
                line = self._doc_lines[line_no]
                latest = line["versions"][-1]
                sponsors = {latest["author"], *latest.get("co_sponsors", [])}
                if line["status"] == "active" and author in sponsors:
                    # 联署集团内: 同线新版本
                    return {"doc_line": line_no, "version": len(line["versions"]) + 1,
                            "parent": parent["directive_id"], "forked_from": None,
                            "parent_body": parent["body"]}
                # 外人修订/线已关闭: 自动分叉
                self._line_seq += 1
                return {"doc_line": f"D{agenda_no}.{self._line_seq}", "version": 1,
                        "parent": None, "forked_from": parent["directive_id"],
                        "parent_body": parent["body"]}
        self._line_seq += 1
        return {"doc_line": f"D{agenda_no}.{self._line_seq}", "version": 1,
                "parent": None, "forked_from": None, "parent_body": None}

    def _register_doc_version(self, assignment: dict, info: dict) -> None:
        line = self._doc_lines.setdefault(
            assignment["doc_line"], {"status": "active", "versions": []}
        )
        line["versions"].append(info)

    def _supersede_other_lines(self, bus: EventBus, sm: VenueStateMachine, passed_line: str) -> None:
        """一版通过, 同议程序号下其余 active 线批量作废."""
        passed_prefix = passed_line.partition(".")[0]
        for line_no, line in self._doc_lines.items():
            if line_no.partition(".")[0] != passed_prefix:
                continue
            if line_no == passed_line or line["status"] != "active":
                continue
            line["status"] = "superseded"
            latest = line["versions"][-1]
            bus.stage(
                Event(
                    session_id=self.session_id,
                    story_time=sm.story_time,
                    type="directive_status",
                    actor="system",
                    venue_id=sm.venue_id,
                    scope="venue",
                    payload={"directive_id": latest["directive_id"], "status": "superseded",
                             "reason": f"{passed_line}已通过, 同议程其余草案作废"},
                ),
                venue_seats=sm.active_seat_ids,
            )

    def _docs_dossier(self, seat_id: str) -> str:
        """该席位可见的现行文件原文: 已通过文件 + 各草案线当前版(历史版本隐藏) + 本人私密指令.

        草案线模型天然给出"当前可用版本"语义: 每条线只展示最新版;
        分叉产生的对抗版是独立线, 自然并列显示; rejected/superseded线整体隐藏.
        """
        merged_parts: list[str] = []
        active_parts: list[str] = []
        for line in self._doc_lines.values():
            if line["status"] not in ("merged", "active"):
                continue
            v = line["versions"][-1]
            co = f", 联署: {', '.join(v['co_sponsors'])}" if v.get("co_sponsors") else ""
            block = f"{v['directive_id']}《{v['title']}》(发起: {v['author']}{co})\n{v['body']}"
            (merged_parts if line["status"] == "merged" else active_parts).append(block)
        own_parts: list[str] = []
        received_parts: list[str] = []
        for key, v in self._directive_index.items():
            if key != v.get("directive_id"):
                continue  # 跳过标题/线号别名, 每份指令只取一次
            if v.get("kind") in ("personal", "crisis_note") and v.get("author") == seat_id:
                own_parts.append(f"[{v['kind']}]《{v['title']}》\n{v['body']}")
            elif (
                v.get("kind") == "crisis_note"
                and v.get("delivered")
                and v.get("recipient") == seat_id
            ):
                received_parts.append(
                    f"来自 {v.get('author', '')}《{v['title']}》\n{v['body']}"
                )
        sections: list[str] = []
        if merged_parts:
            sections.append("## 已通过生效的文件\n" + "\n\n".join(merged_parts))
        if active_parts:
            sections.append(
                "## 待决草案(各线当前版本)\n" + "\n\n".join(active_parts)
            )
        if own_parts:
            sections.append("## 你此前递交的私密指令\n" + "\n\n".join(own_parts))
        if received_parts:
            sections.append("## 你收到的危机笔记\n" + "\n\n".join(received_parts))
        return "\n\n".join(sections)

    # --- 运行时 stats ---

    def _format_stats(self, entity_ids: list[str] | None = None) -> str:
        """渲染当前 stats 为 prompt 文本. entity_ids=None 时全量(DM用)."""
        lines = []
        for eid, ent in self._stats.items():
            if entity_ids is not None and eid not in entity_ids:
                continue
            fields = ent["tags"] or {k: str(v) for k, v in ent["values"].items()}
            if not fields:
                continue
            pairs = ", ".join(f"{k}: {v}" for k, v in fields.items())
            lines.append(f"- {ent['label']}({eid}): {pairs}")
        return "\n".join(lines)

    def _stats_for_seat_text(self, seat_id: str) -> str:
        visible_ids = [e.id for e in self.scenario.stats_for_seat(seat_id)]
        return self._format_stats(visible_ids) if visible_ids else ""

    def _apply_stat_changes(self, changes: list[dict]) -> None:
        """DM 判定结果中的 stat_changes 落到运行时 stats."""
        for ch in changes:
            ent = self._stats.get(ch.get("entity", ""))
            field = ch.get("field", "")
            if ent is None or not field:
                continue
            to = ch.get("to", "")
            if ent["tags"] or not ent["values"]:
                ent["tags"][field] = str(to)
            else:
                try:
                    ent["values"][field] = int(to)
                except (TypeError, ValueError):
                    ent["tags"][field] = str(to)

    # --- 纪元过滤 ---

    def _epoch_slice(self, visible: list[Event], viewer: str) -> list[Event]:
        """L3 = 本纪元起点以来的可见事件, 只追加不截断(11§3). 纪元切换前前缀字节级稳定."""
        start = getattr(self, "_l3_start_seq", {}).get(viewer, 0)
        return [e for e in visible if (e.seq or 0) > start]

    # --- 主持者路由 ---

    def _get_presider_id(self, sm: VenueStateMachine) -> str | None:
        """返回当前主持席 id, 无则 None(走中立主席)."""
        ps = sm.presiding_seat
        if ps and sm.seat_status.get(ps) == "active":
            return ps
        return None

    async def _presider_next_speaker(
        self,
        bus: EventBus,
        sm: VenueStateMachine,
        delegates: dict[str, DelegateAgent],
        chair: ChairAgent,
        seat_ids: list[str],
        summaries: dict[str, str] | None = None,
    ) -> str:
        """路由 next_speaker: 有主持席→DelegateAgent, 无→ChairAgent.

        主持席(代表)点名时产生 venue 可见的 speech 事件(大家听到主持者说话);
        中立主席点名不产生事件(游戏层操作).
        """
        presider_id = self._get_presider_id(sm)
        # 主持席是戏内角色, 只能看自己视角; 中立主席才用 chair 视角
        query_viewer = f"seat:{presider_id}" if presider_id else "chair"
        visible = self._epoch_slice(await bus.query(query_viewer, venue=sm.venue_id), query_viewer)
        task = TaskSpec(
            role="delegate" if presider_id else "chair",
            task="next_speaker",
            phase=sm.phase,
            venue_id=sm.venue_id,
        )

        if presider_id:
            agent = delegates[presider_id]
            # 驳回重试: 点了不存在的席位时, 最多重试 2 次
            for attempt in range(3):
                result = await agent.presiding_next_speaker(
                    task, visible, sm.phase, sm.story_time, sm.spoken_this_phase, sm.active_seat_ids,
                    l2_summary=(summaries or {}).get(f"seat:{presider_id}", ""),
                )
                target = result.seat
                if target in delegates:
                    break
                # 点了不存在的席位, 驳回
                import sys
                print(
                    f"[驳回] 主持席点了不存在的席位 '{target}', "
                    f"可用席位: {', '.join(seat_ids)}, 重试 {attempt+1}/3",
                    file=sys.stderr,
                )
            else:
                # 3 次都点了不存在的人, 保底轮询
                target = (sm.active_seat_ids or seat_ids)[0]
                result = PresidingNextSpeaker(seat=target, announcement=f"请{target}发言。")

            presider_pick = result  # announcement 延后到终局人选确定后再播
        else:
            presider_pick = None
            for attempt in range(3):
                result = await chair.next_speaker(
                    task, visible, sm.phase, sm.story_time, sm.spoken_this_phase
                )
                target = result.seat
                if target in delegates:
                    break
                import sys
                print(
                    f"[驳回] 主席点了不存在的席位 '{target}', 重试 {attempt+1}/3",
                    file=sys.stderr,
                )
            else:
                target = seat_ids[0]

        # 保底轮询覆盖
        if sm.floor_rotation_due:
            forced = sm.next_for_floor_rotation()
            if forced:
                target = forced

        active = sm.active_seat_ids
        if target not in delegates or target not in active:
            target = active[0] if active else seat_ids[0]

        # 主持席点名是戏内行为, 终局人选确定后才播 announcement, 保证"说的"与"点的"一致.
        # 点自己时不播——紧接着的行动回合就是他要说的话, 否则同一段话说两遍.
        if presider_id and target != presider_id:
            if presider_pick is not None and presider_pick.seat == target:
                announcement = presider_pick.announcement or f"请{target}发言。"
                thought = presider_pick.inner_thought
            else:
                announcement = f"请{target}发言。"  # 被保底轮询覆盖时用默认措辞
                thought = ""
            speech_ev = bus.stage(
                Event(
                    session_id=self.session_id,
                    story_time=sm.story_time,
                    type="speech",
                    actor=f"seat:{presider_id}",
                    venue_id=sm.venue_id,
                    scope="venue",
                    payload={"text": announcement},
                ),
                venue_seats=sm.active_seat_ids,
            )
            if thought:
                bus.stage(
                    Event(
                        session_id=self.session_id,
                        story_time=sm.story_time,
                        type="speech_thought",
                        actor=f"seat:{presider_id}",
                        venue_id=sm.venue_id,
                        scope="self",
                        payload={"thought": thought, "ref_seq": speech_ev.seq},
                    ),
                )
        return target

    # --- ModCaucus ---

    async def _run_mod_step(
        self,
        bus: EventBus,
        sm: VenueStateMachine,
        delegates: dict[str, DelegateAgent],
        chair: ChairAgent,
        dm: DMAgent,
        venue_spec: VenueSpec,
        seat_ids: list[str],
        summaries: dict[str, str] | None = None,
    ) -> list[Event]:
        """一个 ModCaucus 最小步: 点名→代表行动→时钟推进."""
        # 1. 主持者点名
        target_seat = await self._presider_next_speaker(bus, sm, delegates, chair, seat_ids, summaries)
        delegate = delegates[target_seat]

        # 2. 代表行动
        seat_viewer = f"seat:{target_seat}"
        delegate_visible = await bus.query(seat_viewer, venue=sm.venue_id)
        is_presiding = (target_seat == sm.presiding_seat)
        turn_task = TaskSpec(
            role="delegate",
            task="turn",
            phase=sm.phase,
            scope="venue",
            venue_id=sm.venue_id,
            seat_id=target_seat,
        )
        ctx = delegate.build_turn_context(
            turn_task, self._epoch_slice(delegate_visible, seat_viewer), sm.phase, sm.story_time,
            is_presiding,
            l2_summary=(summaries or {}).get(f"seat:{target_seat}", ""),
            directives_submitted=self._directive_count,
            own_stats=self._stats_for_seat_text(target_seat),
            docs_dossier=self._docs_dossier(target_seat),
        )
        turn_result = await delegate.act(turn_task, ctx)

        # 3. 处理行动
        if turn_result.action == "speech" and turn_result.text:
            await self._handle_speech(bus, sm, delegate, turn_result, target_seat, seat_ids)
        elif turn_result.action == "motion":
            await self._handle_motion(bus, sm, delegates, chair, turn_result, target_seat, seat_ids, venue_spec, summaries)
        elif turn_result.action == "write_directive" and turn_result.directive:
            if turn_result.text:
                # 边说边交: text 是他当众说的话, 指令同步提交
                await self._handle_speech(bus, sm, delegate, turn_result, target_seat, seat_ids)
            await self._handle_write_directive(bus, sm, dm, turn_result, target_seat, sm.mod_speech_count, seat_ids, summaries)
        elif turn_result.action == "pass":
            # pass 也产生 venue 可见事件, 让用户看到"XX 选择跳过"
            bus.stage(
                Event(
                    session_id=self.session_id,
                    story_time=sm.story_time,
                    type="speech",
                    actor=f"seat:{target_seat}",
                    venue_id=sm.venue_id,
                    scope="venue",
                    payload={"text": f"(选择跳过)"},
                ),
                venue_seats=sm.active_seat_ids,
            )
            sm.record_no_speech()

        # 4. 时钟推进
        sm.advance_clock()
        bus.stage(
            Event(
                session_id=self.session_id,
                story_time=sm.story_time,
                type="clock_advance",
                actor="system",
                venue_id=sm.venue_id,
                scope="venue",
                payload={"from": "", "to": sm.story_time},
            ),
            venue_seats=sm.active_seat_ids,
        )

        committed = await bus.commit_step()
        self._emit_committed(committed)
        return committed

    async def _handle_speech(
        self,
        bus: EventBus,
        sm: VenueStateMachine,
        delegate: DelegateAgent,
        turn_result: DelegateTurnAction,
        target_seat: str,
        seat_ids: list[str],
    ) -> None:
        speech_ev = bus.stage(
            Event(
                session_id=self.session_id,
                story_time=sm.story_time,
                type="speech",
                actor=f"seat:{target_seat}",
                venue_id=sm.venue_id,
                scope="venue",
                payload={"text": turn_result.text},
            ),
            venue_seats=sm.active_seat_ids,
        )
        if turn_result.inner_thought:
            bus.stage(
                Event(
                    session_id=self.session_id,
                    story_time=sm.story_time,
                    type="speech_thought",
                    actor=f"seat:{target_seat}",
                    venue_id=sm.venue_id,
                    scope="self",
                    payload={
                        "thought": turn_result.inner_thought,
                        "ref_seq": speech_ev.seq,
                    },
                ),
            )
        sm.record_speech(target_seat)

    async def _handle_motion(
        self,
        bus: EventBus,
        sm: VenueStateMachine,
        delegates: dict[str, DelegateAgent],
        chair: ChairAgent,
        turn_result: DelegateTurnAction,
        target_seat: str,
        seat_ids: list[str],
        venue_spec: VenueSpec,
        summaries: dict[str, str] | None = None,
    ) -> None:
        motion_type = turn_result.motion_type or "caucus_switch"
        motion_target = turn_result.motion_target or ""

        # 产生 motion 事件
        motion_ev = bus.stage(
            Event(
                session_id=self.session_id,
                story_time=sm.story_time,
                type="motion",
                actor=f"seat:{target_seat}",
                venue_id=sm.venue_id,
                scope="venue",
                payload={"motion_type": motion_type, "target": motion_target, "text": turn_result.text},
            ),
            venue_seats=sm.active_seat_ids,
        )

        # appeal 动议 → 戏外主席终裁
        if motion_type == "appeal":
            await self._handle_appeal(bus, sm, chair, turn_result, motion_ev, seat_ids)
            return

        # 其他动议 → 主持者裁决
        presider_id = self._get_presider_id(sm)
        ruling_task = TaskSpec(
            role="delegate" if presider_id else "chair",
            task="motion_ruling",
            phase=sm.phase,
            venue_id=sm.venue_id,
        )
        motion_text = f"{motion_type}: {motion_target} ({turn_result.text})"

        if presider_id:
            pv = f"seat:{presider_id}"
            visible = self._epoch_slice(await bus.query(pv, venue=sm.venue_id), pv)
            agent = delegates[presider_id]
            ruling = await agent.presiding_motion_ruling(
                ruling_task, visible, motion_text, sm.story_time,
                l2_summary=(summaries or {}).get(pv, ""),
            )
        else:
            visible = self._epoch_slice(await bus.query("chair", venue=sm.venue_id), "chair")
            ruling_result = await chair.motion_ruling(
                ruling_task, visible, motion_text, sm.story_time
            )
            class _R:
                def __init__(self, r, reason):
                    self.ruling = r
                    self.reason = reason
                    self.inner_thought = ""
            ruling = _R(ruling_result.ruling, ruling_result.reason)

        # motion_ruling 事件
        bus.stage(
            Event(
                session_id=self.session_id,
                story_time=sm.story_time,
                type="motion_ruling",
                actor=f"seat:{presider_id}" if presider_id else "chair",
                venue_id=sm.venue_id,
                scope="venue",
                payload={
                    "motion_seq": motion_ev.seq,
                    "ruling": ruling.ruling,
                    "reason": ruling.reason,
                },
            ),
            venue_seats=sm.active_seat_ids,
        )

        # 受理 → 执行动议后果
        if ruling.ruling == "accept":
            if motion_type == "caucus_switch":
                # 切磋商形式
                target_phase = "UnmoderatedCaucus" if sm.phase == "ModeratedCaucus" else "ModeratedCaucus"
                from_phase = sm.phase
                sm.transition(target_phase)
                if target_phase == "ModeratedCaucus":
                    phase_payload = self._phase_change_to_mod_payload(
                        from_phase, turn_result.text or "动议通过"
                    )
                else:
                    phase_payload = {
                        "from": from_phase,
                        "to": target_phase,
                        "reason": turn_result.text or "动议通过",
                    }
                bus.stage(
                    Event(
                        session_id=self.session_id,
                        story_time=sm.story_time,
                        type="phase_change",
                        actor=f"seat:{presider_id}" if presider_id else "chair",
                        venue_id=sm.venue_id,
                        scope="venue",
                        payload=phase_payload,
                    ),
                    venue_seats=sm.active_seat_ids,
                )
            elif motion_type == "vote_directive":
                # 进入 Voting 子流程, 锁定被表决指令(编号解析为具体版本, 见D16)
                _, target_info = self._resolve_doc_ref(motion_target)
                resolved_id = target_info["directive_id"] if target_info else motion_target
                sm.transition("Voting", interrupted_from="ModeratedCaucus")
                sm.start_vote(resolved_id, sm.active_seat_ids)
                # vote_call 事件
                bus.stage(
                    Event(
                        session_id=self.session_id,
                        story_time=sm.story_time,
                        type="vote_call",
                        actor=f"seat:{presider_id}" if presider_id else "chair",
                        venue_id=sm.venue_id,
                        scope="venue",
                        payload={"directive_id": motion_target},
                    ),
                    venue_seats=sm.active_seat_ids,
                )

    async def _handle_appeal(
        self,
        bus: EventBus,
        sm: VenueStateMachine,
        chair: ChairAgent,
        turn_result: DelegateTurnAction,
        motion_ev: Event,
        seat_ids: list[str],
    ) -> None:
        """appeal 动议 → 戏外主席终裁."""
        visible = self._epoch_slice(await bus.query("chair", venue=sm.venue_id), "chair")
        task = TaskSpec(
            role="chair",
            task="appeal_ruling",
            phase=sm.phase,
            venue_id=sm.venue_id,
        )
        result = await chair.appeal_ruling(
            task, visible, turn_result.text, turn_result.motion_target, sm.story_time
        )
        bus.stage(
            Event(
                session_id=self.session_id,
                story_time=sm.story_time,
                type="motion_ruling",
                actor="chair",
                venue_id=sm.venue_id,
                scope="venue",
                payload={
                    "motion_seq": motion_ev.seq,
                    "ruling": "accept" if result.ruling == "overrule" else "reject",
                    "reason": f"申诉终裁: {result.reason}",
                },
            ),
            venue_seats=sm.active_seat_ids,
        )

    async def _handle_write_directive(
        self,
        bus: EventBus,
        sm: VenueStateMachine,
        dm: DMAgent | None,
        delegate_result: DelegateTurnAction,
        target_seat: str,
        step: int,
        seat_ids: list[str],
        summaries: dict[str, str] | None = None,
    ) -> None:
        d = delegate_result.directive
        if d is None:
            return
        is_joint = d.kind in ("directive", "communique")
        assignment: dict = {}
        if is_joint:
            assignment = self._assign_doc_number(d, target_seat)
            directive_id = f"{assignment['doc_line']}-v{assignment['version']}"
        else:
            # 计数器保证会话内唯一且确定; 不含session_id/时钟——掷骰seed依赖id, 墙钟会毁掉同seed可复现
            directive_id = f"d-{self._directive_count + 1}"
        diff_summary = None
        if assignment.get("parent_body") is not None:
            diff_summary = self._diff_summary(assignment["parent_body"], d.body)
        info = {"directive_id": directive_id, "kind": d.kind, "title": d.title,
                "body": d.body, "author": target_seat, "co_sponsors": list(d.co_sponsors),
                "recipient": d.recipient, "delivered": False}
        self._directive_count += 1
        self._directive_index[directive_id] = info
        if is_joint:
            self._register_doc_version(assignment, info)
            self._directive_index[assignment["doc_line"]] = info  # 线号 → 最新版
        if d.title:
            self._directive_index[d.title] = info
        scope = "private" if d.kind in ("personal", "crisis_note") else "venue"
        recipients = [target_seat] if d.kind in ("personal", "crisis_note") else seat_ids

        bus.stage(
            Event(
                session_id=self.session_id,
                story_time=sm.story_time,
                type="directive_submitted",
                actor=f"seat:{target_seat}",
                venue_id=sm.venue_id,
                scope=scope,
                payload={
                    "directive_id": directive_id,
                    "kind": d.kind,
                    "title": d.title,
                    "body": d.body,
                    "uses_powers": d.uses_powers,
                    "author": target_seat,
                    "co_sponsors": d.co_sponsors,
                    "recipient": d.recipient,
                    "revises": d.revises,
                    "doc_line": assignment.get("doc_line"),
                    "version": assignment.get("version"),
                    "parent": assignment.get("parent"),
                    "forked_from": assignment.get("forked_from"),
                    "diff_summary": diff_summary,
                },
            ),
            venue_seats=recipients if scope == "venue" else None,
            private_recipients=recipients if scope == "private" else None,
        )

        # 个人指令直接判定; 危机笔记先判定截获再判定送达; 联合指令/公报需投票(P2 简化: 暂也直接判定)
        if dm is not None and d.kind == "personal":
            await self._adjudicate(bus, dm, directive_id, d.title, d.body, sm, seat_ids,
                                   author_seat=target_seat, summaries=summaries)
        elif dm is not None and d.kind == "crisis_note":
            await self._adjudicate_crisis_note(bus, dm, directive_id, d, target_seat, sm, seat_ids,
                                               summaries=summaries)

    # --- Voting 子流程 ---

    async def _run_voting_step(
        self,
        bus: EventBus,
        sm: VenueStateMachine,
        delegates: dict[str, DelegateAgent],
        chair: ChairAgent,
        venue_spec: VenueSpec,
        seat_ids: list[str],
        summaries: dict[str, str] | None = None,
        dm: DMAgent | None = None,
    ) -> list[Event]:
        """Voting 子流程: 逐席位投票 → 计票 → 返回."""
        if not sm.vote_order:
            # 动议路径外进入投票(容错): 初始化投票顺序
            sm.start_vote(sm.active_vote_directive_id or "", sm.active_seat_ids)

        # 逐席位投票
        while not sm.voting_finished:
            voter = sm.next_voter()
            if voter is None:
                break
            if voter not in delegates:
                sm.record_vote(voter, "abstain")
                continue

            delegate = delegates[voter]
            voter_viewer = f"seat:{voter}"
            visible = await bus.query(voter_viewer, venue=sm.venue_id)
            vote_task = TaskSpec(
                role="delegate",
                task="vote",
                phase="Voting",
                venue_id=sm.venue_id,
                seat_id=voter,
            )
            directive_id = sm.active_vote_directive_id or ""
            info = self._directive_index.get(directive_id, {})
            if info.get("kind") not in ("directive", "communique"):
                info = {}  # 私密指令正文不得进入投票上下文
            ctx = delegate.build_vote_context(
                vote_task,
                self._epoch_slice(visible, voter_viewer),
                info.get("title") or directive_id,
                sm.story_time,
                directive_body=info.get("body", ""),
                l2_summary=(summaries or {}).get(voter_viewer, ""),
                docs_dossier=self._docs_dossier(voter),
            )
            result = await delegate.act(vote_task, ctx, schema_model=DelegateVoteAction)

            choice = result.choice if isinstance(result, DelegateVoteAction) else "abstain"
            sm.record_vote(voter, choice)
            bus.stage(
                Event(
                    session_id=self.session_id,
                    story_time=sm.story_time,
                    type="vote_cast",
                    actor=f"seat:{voter}",
                    venue_id=sm.venue_id,
                    scope="venue",
                    payload={"directive_id": directive_id, "choice": choice},
                ),
                venue_seats=sm.active_seat_ids,
            )

        # 计票
        result_str, tally = sm.tally_votes(
            venue_spec.decision_rule.pass_threshold,
            venue_spec.decision_rule.veto_seats,
        )
        directive_id = sm.active_vote_directive_id or ""
        bus.stage(
            Event(
                session_id=self.session_id,
                story_time=sm.story_time,
                type="vote_result",
                actor="system",
                venue_id=sm.venue_id,
                scope="venue",
                payload={
                    "directive_id": directive_id,
                    "result": result_str,
                    "tally": str(tally),
                },
            ),
            venue_seats=sm.active_seat_ids,
        )

        # 指令状态更新
        bus.stage(
            Event(
                session_id=self.session_id,
                story_time=sm.story_time,
                type="directive_status",
                actor="system",
                venue_id=sm.venue_id,
                scope="venue",
                payload={"directive_id": directive_id, "status": result_str},
            ),
            venue_seats=sm.active_seat_ids,
        )

        # 草案线状态推进(D16): 通过→merged且其余线superseded; 被否→rejected(可fork重开)
        voted_line = directive_id.partition("-v")[0]
        if voted_line in self._doc_lines:
            if result_str == "passed":
                self._doc_lines[voted_line]["status"] = "merged"
                self._supersede_other_lines(bus, sm, voted_line)
            else:
                self._doc_lines[voted_line]["status"] = "rejected"

        # 通过的联合指令/公报交 DM 判定——通过不等于执行成功, 世界要给出反馈
        if result_str == "passed" and dm is not None:
            passed_info = self._directive_index.get(directive_id, {})
            if passed_info.get("kind") in ("directive", "communique"):
                await self._adjudicate(
                    bus, dm,
                    passed_info.get("directive_id", directive_id),
                    passed_info.get("title", directive_id),
                    passed_info.get("body", ""),
                    sm, seat_ids,
                    author_seat=passed_info.get("author", ""),
                    summaries=summaries,
                )

        # 返回被打断的阶段
        return_phase = sm.end_vote()
        sm.transition(return_phase)
        bus.stage(
            Event(
                session_id=self.session_id,
                story_time=sm.story_time,
                type="phase_change",
                actor="chair",
                venue_id=sm.venue_id,
                scope="venue",
                payload={"from": "Voting", "to": return_phase, "reason": "表决完毕"},
            ),
            venue_seats=sm.active_seat_ids,
        )

        committed = await bus.commit_step()
        self._emit_committed(committed)
        return committed

    # --- UnmodCaucus ---

    async def _run_unmod_phase(
        self,
        bus: EventBus,
        sm: VenueStateMachine,
        delegates: dict[str, DelegateAgent],
        chair: ChairAgent,
        venue_spec: VenueSpec,
        seat_ids: list[str],
        summaries: dict[str, str] | None = None,
        dm: DMAgent | None = None,
    ) -> list[Event]:
        """Unmod: 分组→小轮并行→屏障结算. P2 简化版(单轮, 无闭门)."""
        if not sm.groups:
            # 初始分组: 每人表达意愿, 简化为全体一组
            sm.init_groups([GroupState("g1", list(seat_ids))])

        # 跑一轮: 每个在席席位发言一次
        for seat_id in sm.active_seat_ids:
            delegate = delegates[seat_id]
            visible = await bus.query(f"seat:{seat_id}", venue=sm.venue_id, group="g1")
            turn_task = TaskSpec(
                role="delegate",
                task="turn",
                phase="UnmoderatedCaucus",
                scope="group",
                venue_id=sm.venue_id,
                seat_id=seat_id,
            )
            ctx = delegate.build_turn_context(
                turn_task,
                self._epoch_slice(visible, f"seat:{seat_id}"),
                "UnmoderatedCaucus", sm.story_time,
                l2_summary=(summaries or {}).get(f"seat:{seat_id}", ""),
                directives_submitted=self._directive_count,
                own_stats=self._stats_for_seat_text(seat_id),
                docs_dossier=self._docs_dossier(seat_id),
            )
            turn_result = await delegate.act(turn_task, ctx)

            if turn_result.text and turn_result.action in ("speech", "write_directive"):
                speech_ev = bus.stage(
                    Event(
                        session_id=self.session_id,
                        story_time=sm.story_time,
                        type="speech",
                        actor=f"seat:{seat_id}",
                        venue_id=sm.venue_id,
                        group_id="g1",
                        scope="group",
                        payload={"text": turn_result.text},
                    ),
                    group_members=sm.active_seat_ids,
                )
                if turn_result.inner_thought:
                    bus.stage(
                        Event(
                            session_id=self.session_id,
                            story_time=sm.story_time,
                            type="speech_thought",
                            actor=f"seat:{seat_id}",
                            venue_id=sm.venue_id,
                            scope="self",
                            payload={"thought": turn_result.inner_thought, "ref_seq": speech_ev.seq},
                        ),
                    )
            if turn_result.action == "write_directive" and turn_result.directive:
                # Unmod 中同样可以提交指令(此前被静默丢弃)
                await self._handle_write_directive(
                    bus, sm, dm, turn_result, seat_id, 0, seat_ids, summaries,
                )

        sm.next_unmod_round()
        sm.advance_clock(unmod=True)
        bus.stage(
            Event(
                session_id=self.session_id,
                story_time=sm.story_time,
                type="clock_advance",
                actor="system",
                venue_id=sm.venue_id,
                scope="venue",
                payload={"from": "", "to": sm.story_time},
            ),
            venue_seats=sm.active_seat_ids,
        )

        # 小轮跑完 → 主席决定返回 Mod
        if sm.unmod_finished:
            sm.transition("ModeratedCaucus")
            bus.stage(
                Event(
                    session_id=self.session_id,
                    story_time=sm.story_time,
                    type="phase_change",
                    actor="chair",
                    venue_id=sm.venue_id,
                    scope="venue",
                    payload=self._phase_change_to_mod_payload(
                        "UnmoderatedCaucus", "非正式磋商结束"
                    ),
                ),
                venue_seats=sm.active_seat_ids,
            )

        committed = await bus.commit_step()
        self._emit_committed(committed)
        return committed

    # --- 阶段决策 ---

    async def _chair_phase_decision(
        self,
        bus: EventBus,
        sm: VenueStateMachine,
        chair: ChairAgent,
        seat_ids: list[str],
    ) -> list[Event]:
        visible = self._epoch_slice(await bus.query("chair", venue=sm.venue_id), "chair")
        task = TaskSpec(
            role="chair",
            task="phase_decision",
            phase=sm.phase,
            venue_id=sm.venue_id,
        )
        decision = await chair.phase_decision(
            task, visible, sm.phase, sm.story_time, sm.mod_speech_count, sm.max_speeches,
            directives_submitted=self._directive_count,
        )

        events_to_commit: list[Event] = []
        if decision.action == "keep" and decision.announcement:
            # keep 时也播报 announcement——零指令时的公开催办靠这条落地
            bus.stage(
                Event(
                    session_id=self.session_id,
                    story_time=sm.story_time,
                    type="speech",
                    actor="chair",
                    venue_id=sm.venue_id,
                    scope="venue",
                    payload={"text": decision.announcement},
                ),
                venue_seats=sm.active_seat_ids,
            )
        if decision.action == "adjourn":
            sm.transition("Adjourned")
            bus.stage(
                Event(
                    session_id=self.session_id,
                    story_time=sm.story_time,
                    type="phase_change",
                    actor="chair",
                    venue_id=sm.venue_id,
                    scope="venue",
                    payload={"from": sm.phase, "to": "Adjourned", "reason": decision.announcement or "闭会"},
                ),
                venue_seats=sm.active_seat_ids,
            )
        elif decision.action == "switch" and decision.to_phase:
            if sm.can_transition(decision.to_phase):
                old_phase = sm.phase
                sm.transition(decision.to_phase)
                if decision.to_phase == "ModeratedCaucus":
                    phase_payload = self._phase_change_to_mod_payload(
                        old_phase, decision.announcement or ""
                    )
                else:
                    phase_payload = {
                        "from": old_phase,
                        "to": decision.to_phase,
                        "reason": decision.announcement,
                    }
                bus.stage(
                    Event(
                        session_id=self.session_id,
                        story_time=sm.story_time,
                        type="phase_change",
                        actor="chair",
                        venue_id=sm.venue_id,
                        scope="venue",
                        payload=phase_payload,
                    ),
                    venue_seats=sm.active_seat_ids,
                )

        committed = await bus.commit_step()
        self._emit_committed(committed)
        return committed

    # --- DM 判定 ---

    async def _adjudicate(
        self,
        bus: EventBus,
        dm: DMAgent,
        directive_id: str,
        title: str,
        body: str,
        sm: VenueStateMachine,
        seat_ids: list[str],
        author_seat: str = "",
        summaries: dict[str, str] | None = None,
    ) -> None:
        directive_text = f"标题: {title}\n内容: {body}"
        dm_summary = (summaries or {}).get("dm", "")
        # 背景文书全文与权力清单在 DM 的 G 段(缓存友好); 这里只放动态内容
        parts = []
        stats_text = self._format_stats()
        if stats_text:
            author_label = f"(提交者: {author_seat})" if author_seat else ""
            parts.append(f"当前局势数值{author_label}——评估概率档位的核心依据:\n{stats_text}")
        if dm_summary:
            parts.append(f"近期局势摘要:\n{dm_summary}")
        context_summary = "\n\n".join(parts) or "(局势尚无特别记录)"

        assess_task = TaskSpec(role="dm", task="adjudicate", phase=sm.phase, venue_id=sm.venue_id)
        assessment = await dm.assess_feasibility(
            assess_task, directive_text, context_summary, story_time=sm.story_time
        )

        seed, roll = dm.roll(directive_id)
        margin = assessment.probability_tier - roll
        outcome = outcome_tier(margin)

        result_task = TaskSpec(role="dm", task="adjudicate", phase=sm.phase, venue_id=sm.venue_id)
        result = await dm.write_result(
            result_task, directive_text, assessment.probability_tier, roll, outcome,
            context_summary, story_time=sm.story_time,
        )

        takes_effect_at = ""
        if assessment.takes_effect_at:
            from munagent.core.timezone import to_utc_iso
            try:
                takes_effect_at = to_utc_iso(assessment.takes_effect_at)
            except ValueError:
                takes_effect_at = assessment.takes_effect_at

        bus.stage(
            Event(
                session_id=self.session_id,
                story_time=sm.story_time,
                type="adjudication",
                actor="dm",
                venue_id=sm.venue_id,
                scope="dm-only",
                payload={
                    "directive_id": directive_id,
                    "probability_tier": assessment.probability_tier,
                    "roll": roll,
                    "outcome": outcome,
                    "narrative_full": result.narrative_full,
                    "takes_effect_at": takes_effect_at,
                },
                rng={"seed": seed, "rolls": [roll]},
            ),
        )

        bus.stage(
            Event(
                session_id=self.session_id,
                story_time=sm.story_time,
                type="directive_status",
                actor="system",
                venue_id=sm.venue_id,
                scope="private",
                payload={"directive_id": directive_id, "status": "resolved"},
            ),
            private_recipients=[author_seat] if author_seat else [],
        )

        self._apply_stat_changes(result.stat_changes)

        # 席位资格变化: DM叙事宣告 → 机制执行(解职/被捕/死亡/复席), 见 04§3
        for change in result.seat_status_changes:
            seat = change.get("seat", "")
            to = change.get("to", "")
            if seat not in sm.seat_status or to not in ("active", "suspended", "removed"):
                continue
            old_presider = sm.presiding_seat
            sm.set_seat_status(seat, to)
            bus.stage(
                Event(
                    session_id=self.session_id,
                    story_time=sm.story_time,
                    type="seat_status_change",
                    actor="system",
                    venue_id=sm.venue_id,
                    scope="venue",
                    payload={"seat": seat, "to": to, "reason": change.get("reason", ""),
                             "cause_directive": directive_id},
                ),
                venue_seats=sm.active_seat_ids,
            )
            if old_presider == seat and sm.presiding_seat is None:
                bus.stage(
                    Event(
                        session_id=self.session_id,
                        story_time=sm.story_time,
                        type="presiding_change",
                        actor="system",
                        venue_id=sm.venue_id,
                        scope="venue",
                        payload={"from_seat": seat, "to_seat": "", "cause": "主持席失去参会资格, 回落中立主席"},
                    ),
                    venue_seats=sm.active_seat_ids,
                )

        broadcast_text = (
            result.per_venue_visible[0]["text"]
            if result.per_venue_visible
            else result.narrative_full
        )
        bus.stage(
            Event(
                session_id=self.session_id,
                story_time=sm.story_time,
                type="crisis_update",
                actor="chair",
                venue_id=sm.venue_id,
                scope="global",
                payload={"text": broadcast_text, "source_directive_ids": [directive_id]},
            ),
        )

        # 危机更新后由主席决定跳时(见 04§5): 依据G段时间线节点与局势
        chair = getattr(self, "_chair", None)
        if chair is not None:
            prior_adj = await bus.query("god", types=["adjudication"])
            pending_times = self._pending_effect_times(
                prior_adj, sm.story_time, extra=takes_effect_at,
            )
            pending = self._format_pending_effects(
                prior_adj, sm.story_time,
                extra_directive_id=directive_id,
                extra_takes_effect_at=takes_effect_at,
            )
            clock_task = TaskSpec(role="chair", task="clock_decision",
                                  phase=sm.phase, venue_id=sm.venue_id)
            decision = await chair.clock_decision(
                clock_task, sm.story_time, broadcast_text, pending
            )
            if decision.advance_to:
                validated = self._validate_clock_advance(
                    sm.story_time, decision.advance_to,
                    pending_effect_times=pending_times,
                )
                if validated is not None:
                    old_time = sm.story_time
                    sm.advance_clock_to(validated)
                    bus.stage(
                        Event(
                            session_id=self.session_id,
                            story_time=sm.story_time,
                            type="clock_advance",
                            actor="chair",
                            venue_id=sm.venue_id,
                            scope="venue",
                            payload={"from": old_time, "to": sm.story_time,
                                     "reason": decision.reason},
                        ),
                        venue_seats=sm.active_seat_ids,
                    )

    async def _adjudicate_crisis_note(
        self,
        bus: EventBus,
        dm: DMAgent,
        directive_id: str,
        d: Any,
        author_seat: str,
        sm: VenueStateMachine,
        seat_ids: list[str],
        summaries: dict[str, str] | None = None,
    ) -> None:
        """危机笔记: 先判定截获, 再判定送达. 见 06§5.

        截获时**不通知作者**(猜疑链设计: 作者只会发现石沉大海);
        送达时 note_delivered 携带正文, 收件人由此读到笔记内容.
        """
        # 截获判定: 程序掷骰, 概率档位默认 30(低频截获)
        seed, roll = dm.roll(directive_id + ":intercept")
        intercept_tier = 30  # 截获概率较低
        margin = intercept_tier - roll
        intercepted = margin >= 10  # 成功档以上才截获

        if intercepted:
            # 截获: 产生 private 事件给主席团
            bus.stage(
                Event(
                    session_id=self.session_id,
                    story_time=sm.story_time,
                    type="adjudication",
                    actor="dm",
                    venue_id=sm.venue_id,
                    scope="dm-only",
                    payload={
                        "directive_id": directive_id,
                        "kind": "crisis_note_intercept",
                        "outcome": "截获",
                        "narrative_full": f"危机笔记'{d.title}'被截获。内容: {d.body[:100]}",
                    },
                    rng={"seed": seed, "rolls": [roll]},
                ),
            )
            bus.stage(
                Event(
                    session_id=self.session_id,
                    story_time=sm.story_time,
                    type="directive_status",
                    actor="system",
                    venue_id=sm.venue_id,
                    scope="dm-only",
                    payload={"directive_id": directive_id, "status": "intercepted"},
                ),
            )
        else:
            # 未截获: 正常送达 + 判定内容效果
            bus.stage(
                Event(
                    session_id=self.session_id,
                    story_time=sm.story_time,
                    type="note_delivered",
                    actor="system",
                    venue_id=sm.venue_id,
                    scope="private",
                    payload={
                        "directive_id": directive_id,
                        "recipient": d.recipient,
                        "from": author_seat,
                        "title": d.title,
                        "body": d.body,
                    },
                ),
                private_recipients=[author_seat, d.recipient] if d.recipient else [author_seat],
            )
            if directive_id in self._directive_index:
                self._directive_index[directive_id]["delivered"] = True
            await self._adjudicate(bus, dm, directive_id, d.title, d.body, sm, seat_ids,
                                   author_seat=author_seat, summaries=summaries)

    # --- 纪元机制 ---

    async def _check_epochs(
        self,
        bus: EventBus,
        sm: VenueStateMachine,
        recorder: Any,
        summaries: dict[str, str],
        l2_chapters: dict[str, list[str]],
        l3_accum: dict[str, list[Event]],
        new_committed: list[Event],
        seat_ids: list[str],
        threshold: int,
    ) -> None:
        """检查各视角 L3 是否超阈值, 超了则触发摘要. 见 11§3."""
        from munagent.agents.recorder import estimate_tokens

        viewers = [f"seat:{sid}" for sid in seat_ids] + ["chair", "dm"]
        for viewer in viewers:
            # 累积本视角可见的新事件
            for e in new_committed:
                if e.is_visible_to(viewer):
                    l3_accum.setdefault(viewer, []).append(e)

            accum = l3_accum.get(viewer, [])
            if not accum:
                continue

            l3_text = "\n".join(render(e) for e in accum)
            if estimate_tokens(l3_text) < threshold:
                continue

            # 触发纪元切换: 摘本期新事件为一章, 追加(章节追加模型, 见05§3.4)
            level = "private" if viewer.startswith("seat:") else "dm-only"
            if viewer == "chair":
                level = "venue"
            task = TaskSpec(
                role="recorder",
                task="summarize",
                phase=sm.phase,
                venue_id=sm.venue_id,
            )
            chapter = await recorder.summarize_chapter(task, accum, level)
            chapters = l2_chapters.setdefault(viewer, [])
            if chapter:
                chapters.append(chapter)
                bus.stage(
                    Event(
                        session_id=self.session_id,
                        story_time=sm.story_time,
                        type="summary_written",
                        actor="recorder",
                        venue_id=sm.venue_id,
                        scope="dm-only",
                        payload={
                            "level": level,
                            "kind": "chapter",
                            "text": chapter,
                            "viewer": viewer,
                        },
                    ),
                )

            # 低频合并(squash): 章节总量超 2×纪元阈值时全部压成一章
            from munagent.agents.recorder import estimate_tokens as _est
            if len(chapters) > 1 and _est("\n\n".join(chapters)) > threshold * 2:
                merged = await recorder.consolidate(task, list(chapters), level)
                l2_chapters[viewer] = [merged]
                chapters = l2_chapters[viewer]
                bus.stage(
                    Event(
                        session_id=self.session_id,
                        story_time=sm.story_time,
                        type="summary_written",
                        actor="recorder",
                        venue_id=sm.venue_id,
                        scope="dm-only",
                        payload={
                            "level": level,
                            "kind": "consolidated",
                            "text": merged,
                            "viewer": viewer,
                        },
                    ),
                )
            summaries[viewer] = "\n\n".join(chapters)
            committed = await bus.commit_step()
            self._emit_committed(committed)

            # L3 清空, 开始新纪元; 记录起点 seq 供 _epoch_slice 过滤
            if accum:
                self._l3_start_seq[viewer] = max((e.seq or 0) for e in accum)
            l3_accum[viewer] = []

    async def _warmup_g_segment(self, llm: LLMClient, g_global: str) -> None:
        """G 段预热: 会话启动时发一次廉价请求建立缓存. 见 11§6."""
        from munagent.llm.client import ChatMessage, ChatRequest

        request = ChatRequest(
            role="delegate",
            task="warmup",
            messages=[
                ChatMessage(role="system", content=g_global),
                ChatMessage(role="user", content="理解了. 回复ok."),
            ],
            max_tokens=5,
        )
        try:
            await llm.chat(request)
        except Exception:
            pass  # 预热失败不影响推演
