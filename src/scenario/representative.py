from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from filesystem.filesystem import File, FileSystem
    from scenario.venue import Venue


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


    # 与Filesystem的交互通道
    def _require_filesystem(self) -> FileSystem:
        if not self.id:
            raise RuntimeError("代表尚未设置 id")
        if self.venue is None:
            raise RuntimeError(f"代表 {self.id} 未绑定会场,无法访问 FileSystem")
        filesystem = self.venue.scenario.filesystem
        if filesystem is None:
            raise RuntimeError(
                f"代表 {self.id} 所在 Scenario 尚未 initialize,FileSystem 不可用"
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
        """列出本代表在 ``reps/`` 下可见的文件."""
        return self._require_filesystem().list_visible(self.id)

    def list_writable(self) -> list[File]:
        """列出本代表在 ``reps/`` 下可写的文件."""
        return self._require_filesystem().list_writable(self.id)

    def read_file(self, file: File) -> str:
        """以本代表身份读取 ``file`` 内容(须在其 scope 内)."""
        self._require_managed_file(file)
        return file.get_content(self.id)

    def write_file(self, file: File, content: str) -> None:
        """以本代表身份写入 ``file`` 内容(须为其 owner)并落盘."""
        filesystem = self._require_managed_file(file)
        relative = filesystem._relkey(file.path)
        filesystem.write(relative, self.id, content)

    def create_file(self, name: str, content: str, description: str) -> File:
        """在本代表目录下创建新文件;``description`` 为不超过 20 字的简述."""
        return self._require_filesystem().create_rep_file(
            self.id,
            name,
            content,
            description=description,
        )

    def add_scope(self, file: File, others: str | set[str]) -> None:
        """以本代表身份扩大 ``file`` 的可见范围(须为其 owner)."""
        filesystem = self._require_managed_file(file)
        relative = filesystem._relkey(file.path)
        newcomers = {others} if isinstance(others, str) else others
        filesystem.add_scope(relative, self.id, newcomers)

    def add_owner(self, file: File, others: str | set[str]) -> None:
        """以本代表身份将已在 scope 中的对象提升为 owner(须为其 owner)."""
        filesystem = self._require_managed_file(file)
        relative = filesystem._relkey(file.path)
        newcomers = {others} if isinstance(others, str) else others
        filesystem.add_owner(relative, self.id, newcomers)

    def submit_file(self, file: File) -> File:
        """以本代表身份将 ``file`` 提交到 ``submissions/``(须为其 owner)."""
        self._require_managed_file(file)
        return file.submit(self.id)

    def can_submit(self, file: File) -> bool:
        """判断本代表是否可将 ``file`` 提交到 ``submissions/``."""
        self._require_managed_file(file)
        return file.can_submit(self.id)

    def set_description(self, file: File, description: str) -> None:
        """以本代表身份修改 ``file`` 简述(须为其 owner)并写入 manifest."""
        filesystem = self._require_managed_file(file)
        relative = filesystem._relkey(file.path)
        filesystem.set_description(relative, self.id, description)
