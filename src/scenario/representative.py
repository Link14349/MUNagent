from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
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
