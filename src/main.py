"""MUNagent 入口：加载并打印场景包摘要。"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from scenario.representative import PrivateTarget, Representative
from scenario.scenario import Scenario
from scenario.venue import Agenda, Venue


def _indent(text: str, level: int = 1) -> str:
    prefix = "  " * level
    return "\n".join(f"{prefix}{line}" for line in text.splitlines())


def _print_list(title: str, items: list[str], *, level: int = 1) -> None:
    prefix = "  " * level
    print(f"{prefix}{title}:")
    if not items:
        print(f"{prefix}  (空)")
        return
    for item in items:
        print(f"{prefix}  - {item}")


def _print_agenda(agenda: Agenda, *, level: int = 2) -> None:
    prefix = "  " * level
    print(f"{prefix}[{agenda.id}] {agenda.title}")
    for question in agenda.questions:
        print(f"{prefix}  ? {question}")


def _print_venue(venue: Venue) -> None:
    print(f"\n{'=' * 60}")
    print(f"会场: {venue.name} ({venue.id})")
    print(f"{'=' * 60}")
    print(_indent(f"时区: {venue.timezone}"))
    print(_indent(f"主席: {venue.chair}"))
    print(_indent(f"初始议题: {venue.initial_agenda}"))
    print(_indent(f"描述:\n{_indent(venue.description, 2)}"))
    _print_list("席位", venue.seats)
    print(_indent("议程阶段:"))
    for agenda in venue.agenda:
        _print_agenda(agenda)


def _print_private_target(target: PrivateTarget, *, level: int = 2) -> None:
    prefix = "  " * level
    print(f"{prefix}[{target.id}] ({target.importance}) {target.objective}")


def _print_representative(rep: Representative) -> None:
    print(f"\n{'=' * 60}")
    print(f"代表: {rep.name} ({rep.id})")
    print(f"{'=' * 60}")
    venue_id = rep.venue.id if rep.venue else "?"
    print(_indent(f"会场: {venue_id}"))
    print(_indent(f"代表团: {rep.delegation}"))
    print(_indent(f"角色: {rep.role}"))
    print(_indent(f"头衔: {rep.title}"))
    print(_indent(f"立场: {rep.position}"))

    _print_list("公开目标", rep.public_target)
    _print_list("正式权力", rep.public_formal_powers)
    _print_list("公开限制", rep.public_limits)

    print(_indent("私密目标:"))
    for target in rep.private_target:
        _print_private_target(target)

    _print_list("红线", rep.private_red_lines)
    _print_list("谈判空间", rep.private_bargaining_space)
    _print_list("私密信息", rep.private_information)

    print(_indent("人物关系:"))
    if not rep.relationships:
        print(_indent("(空)", 2))
    else:
        for related_id, note in rep.relationships.items():
            print(_indent(f"{related_id}: {note}", 2))

    print(_indent("人格:"))
    for key, value in rep._persona.items():
        print(_indent(f"{key}: {value}", 2))

    print(_indent(f"Agent 指令:\n{_indent(rep._agent_directive, 2)}"))


def main() -> None:
    root = Path(__file__).resolve().parent.parent / "scenario-template"
    scenario = Scenario()
    scenario.load(str(root))

    print(f"场景: {scenario.title}")
    print(f"时区: {scenario.timezone}")
    print(f"开场时间: {scenario.start_time}")
    if scenario.event_list is not None:
        print(f"当前时间: {scenario.event_list.time}")
    print(f"背景字数: {len(scenario.background)}")
    print(f"场景目标数: {len(scenario.targets)}")
    print(f"会场数: {len(scenario.venues)}")
    print(f"代表数: {len(scenario.representatives)}")
    print(f"外部事件数: {len(scenario.event_pool)}")
    print(f"结束条件数: {len(scenario.end_conditions)}")

    print("\n场景目标:")
    for index, target in enumerate(scenario.targets, start=1):
        print(f"  {index}. {target}")

    for venue in scenario.venues:
        _print_venue(venue)

    for rep in scenario.representatives:
        _print_representative(rep)

    print("\n外部事件:")
    for event in scenario.event_pool:
        print(f"  - [{event.condition.type}] {event.content[:80]}...")


if __name__ == "__main__":
    main()
