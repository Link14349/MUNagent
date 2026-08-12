from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agenda.agenda import Agenda
    from event.event import (
        InstructionEvent,
        MessageEvent,
        MotionSwitchEvent,
        NoteEvent,
        PhaseSwitchEvent,
        ResolutionEvent,
    )
    from filesystem.filesystem import File, FileSystem
    from scenario.venue import SessionPhase, Venue


class PrivateTarget:
    id: str
    objective: str
    importance: str

    def __init__(self, id: str, objective: str, importance: str):
        self.id = id
        self.objective = objective
        self.importance = importance


class Representative:
    id: str
    name: str
    venue: Venue | None
    is_chair: bool
    delegation: str
    role: str
    title: str
    position: str
    public_target: list[str]
    public_formal_powers: list[str]
    public_limits: list[str]
    private_target: list[PrivateTarget]
    private_red_lines: list[str]
    private_bargaining_space: list[str]
    private_information: list[str]
    relationships: dict[str, str]
    _persona: dict[str, str | float]
    _agent_directive: str

    def __init__(self):
        self.id = ""
        self.name = ""
        self.venue = None
        self.is_chair = False
        self.delegation = ""
        self.role = ""
        self.title = ""
        self.position = ""
        self.public_target = []
        self.public_formal_powers = []
        self.public_limits = []
        self.private_target = []
        self.private_red_lines = []
        self.private_bargaining_space = []
        self.private_information = []
        self.relationships = {}
        self._persona = {}
        self._agent_directive = ""

    def _require_venue(self) -> Venue:
        if not self.id:
            raise RuntimeError("代表尚未设置 id")
        if self.venue is None:
            raise RuntimeError(f"代表 {self.id} 未绑定会场")
        return self.venue

    def _require_event_list(self):
        return self._require_venue()._require_event_list()

    # 与 Agenda / Venue 的交互通道
    @property
    def current_agenda(self) -> Agenda | None:
        """当前会场正在审议的议题."""
        return self._require_venue().current_agenda

    @property
    def todo_agenda(self) -> list[Agenda]:
        """待审议议题列表副本."""
        return self._require_venue().todo_agenda

    @property
    def finished_agenda(self) -> list[Agenda]:
        """已结束议题列表副本."""
        return self._require_venue().finished_agenda

    def get_agenda(self, agenda_id: str) -> Agenda:
        """按 ID 获取本会场议题."""
        return self._require_venue().get_agenda(agenda_id)

    def set_current_agenda(self, agenda: Agenda, finished: bool = False) -> None:
        """以本代表身份切换当前议题(须为主席)."""
        self._require_venue().set_current_agenda(self.id, agenda, finished=finished)

    def add_agenda(self, agenda: Agenda) -> None:
        """以本代表身份向 todo 追加议题(须为主席)."""
        self._require_venue().add_agenda(self.id, agenda)

    # 与Filesystem的交互通道
    def _require_filesystem(self) -> FileSystem:
        venue = self._require_venue()
        filesystem = venue.scenario.filesystem
        if filesystem is None:
            raise RuntimeError(
                f"代表 {self.id} 所在 Scenario 尚未 initialize，FileSystem 不可用"
            )
        return filesystem

    def _require_managed_file(self, file: File) -> FileSystem:
        filesystem = self._require_filesystem()
        if file._filesystem is not filesystem:
            raise ValueError(
                f"文件 {file.path} 不属于当前 Scenario 的 FileSystem"
            )
        return filesystem

    def list_visible(self) -> list[File]:
        """列出本代表在 ``reps/`` 下可见的文件。"""
        return self._require_filesystem().list_visible(self.id)

    def list_writable(self) -> list[File]:
        """列出本代表在 ``reps/`` 下可写的文件。"""
        return self._require_filesystem().list_writable(self.id)

    def read_file(self, file: File) -> str:
        """以本代表身份读取 ``file`` 内容(须在其 scope 内)。"""
        self._require_managed_file(file)
        return file.get_content(self.id)

    def write_file(self, file: File, content: str) -> None:
        """以本代表身份写入 ``file`` 内容(须为其 owner)并落盘。"""
        filesystem = self._require_managed_file(file)
        relative = filesystem._relkey(file.path)
        filesystem.write(relative, self.id, content)

    def create_file(self, name: str, content: str, description: str) -> File:
        """在本代表目录下创建新文件；``description`` 为不超过 20 字的简述。"""
        return self._require_filesystem().create_rep_file(
            self.id,
            name,
            content,
            description=description,
        )

    def get_file_access(self, file: File) -> dict[str, object]:
        """查看 ``file`` 的 owners/scope/primary_owner(须为其 owner)。"""
        self._require_managed_file(file)
        return file.get_access(self.id)

    def add_scope(self, file: File, others: str | set[str]) -> None:
        """以本代表身份扩大 ``file`` 的可见范围(须为其 owner)。"""
        filesystem = self._require_managed_file(file)
        relative = filesystem._relkey(file.path)
        newcomers = {others} if isinstance(others, str) else others
        filesystem.add_scope(relative, self.id, newcomers)

    def add_owner(self, file: File, others: str | set[str]) -> None:
        """以本代表身份将已在 scope 中的对象提升为 owner(须为其 owner)。"""
        filesystem = self._require_managed_file(file)
        relative = filesystem._relkey(file.path)
        newcomers = {others} if isinstance(others, str) else others
        filesystem.add_owner(relative, self.id, newcomers)

    def submit_file(self, file: File) -> File:
        """以本代表身份将 ``file`` 提交到 ``submissions/``(须为其 owner)。"""
        self._require_managed_file(file)
        return file.submit(self.id)

    def can_submit(self, file: File) -> bool:
        """判断本代表是否可将 ``file`` 提交到 ``submissions/``。"""
        self._require_managed_file(file)
        return file.can_submit(self.id)

    def set_description(self, file: File, description: str) -> None:
        """以本代表身份修改 ``file`` 简述(须为其 owner)并写入 manifest。"""
        filesystem = self._require_managed_file(file)
        relative = filesystem._relkey(file.path)
        filesystem.set_description(relative, self.id, description)

    def _resolve_seat_ids(self, reps: str | set[str], *, field: str) -> set[str]:
        """将代表 ID 规范为本会场 seats 内的非空集合."""
        venue = self._require_venue()
        members = {reps} if isinstance(reps, str) else set(reps)
        if not members:
            raise ValueError(f"代表 {self.id} 的 {field} 不能为空")
        unknown = members - set(venue.seats)
        if unknown:
            raise ValueError(
                f"代表 {self.id} 的 {field} 不在会场 {venue.id} 的 seats 中: "
                f"{sorted(unknown)}"
            )
        return members

    def _ensure_submission(self, file: File) -> File:
        """将工作文件提交为 ``submissions/`` 副本;若已是提交副本则原样返回."""
        self._require_managed_file(file)
        if file.is_submission:
            return file
        return self.submit_file(file)

    # 通过 Venue 提交事件
    def send_message(self, content: str) -> MessageEvent:
        """以本代表身份公开发言,提交 ``MessageEvent``(全会场可见)."""
        from event.event import MessageEvent

        venue = self._require_venue()
        event = MessageEvent(content, self.id, venue.id, venue.scenario)
        venue.submit_event(event)
        return event

    def pass_note(self, content: str, to: str | set[str]) -> NoteEvent:
        """以本代表身份传纸条,提交 ``NoteEvent``(仅发送者与收件人可见)."""
        from event.event import NoteEvent

        venue = self._require_venue()
        recipients = self._resolve_seat_ids(to, field="传纸条收件人")
        event = NoteEvent(content, self.id, recipients, venue.id, venue.scenario)
        venue.submit_event(event)
        return event

    def submit_motion_switch(
        self, content: str, target_phase: SessionPhase | str
    ) -> MotionSwitchEvent:
        """以本代表身份提出阶段切换动议,提交 ``MotionSwitchEvent``(全会场可见,PENDING)."""
        from event.event import MotionSwitchEvent

        venue = self._require_venue()
        event = MotionSwitchEvent(
            content,
            target_phase,
            venue.id,
            set(venue.seats),
            venue.scenario,
        )
        venue.submit_event(event)
        return event

    def submit_phase_switch(
        self, content: str, target_phase: SessionPhase | str
    ) -> PhaseSwitchEvent:
        """以本代表身份直接切换会议阶段并提交 ``PhaseSwitchEvent``.

        须为本会场主席,且 ``chair_power.decide_switch_phase`` 为真;
        成功后会场 ``session_phase`` 立即变更,事件状态为 COMPLETED.
        """
        return self._require_venue().decide_switch_phase(
            self.id, content, target_phase
        )

    def submit_instruction(
        self, content: str, fr: set[str], file: File
    ) -> InstructionEvent:
        """提交 ``InstructionEvent``(PENDING).

        ``file`` 为 ``reps/`` 工作文件时会先 ``submit_file`` 再绑定副本;
        若已是 ``submissions/`` 副本则直接绑定.``fr`` 即可见 scope / from_reps.
        """
        from event.event import InstructionEvent

        venue = self._require_venue()
        submitted = self._ensure_submission(file)
        from_reps = self._resolve_seat_ids(fr, field="fr")
        event = InstructionEvent(
            content, from_reps, submitted, venue.id, venue.scenario
        )
        venue.submit_event(event)
        return event

    def submit_resolution(
        self, content: str, fr: set[str], file: File
    ) -> ResolutionEvent:
        """提交 ``ResolutionEvent``(PENDING).

        ``file`` 为 ``reps/`` 工作文件时会先 ``submit_file`` 再绑定副本;
        若已是 ``submissions/`` 副本则直接绑定.``fr`` 即可见 scope / from_reps.
        """
        from event.event import ResolutionEvent

        venue = self._require_venue()
        submitted = self._ensure_submission(file)
        from_reps = self._resolve_seat_ids(fr, field="fr")
        event = ResolutionEvent(
            content, from_reps, submitted, venue.id, venue.scenario
        )
        venue.submit_event(event)
        return event
