"""Representative 对 FileSystem 的封装接口。"""

from __future__ import annotations

from pathlib import Path

import pytest

from scenario.scenario import Scenario

TEMPLATE = Path(__file__).resolve().parent.parent / "scenario-template"

CHURCHILL = "winston_churchill"
STALIN = "joseph_stalin"


@pytest.fixture
def scenario(tmp_path: Path) -> Scenario:
    loaded = Scenario()
    loaded.load(str(TEMPLATE))
    loaded.root_path = tmp_path
    (tmp_path / "simulation").mkdir()
    loaded.initialize()
    return loaded


def _rep(scenario: Scenario, rep_id: str):
    for rep in scenario.representatives:
        if rep.id == rep_id:
            return rep
    raise AssertionError(f"missing rep {rep_id}")


def test_representative_file_api(scenario: Scenario) -> None:
    churchill = _rep(scenario, CHURCHILL)
    stalin = _rep(scenario, STALIN)

    draft = churchill.create_file("draft.md", "百分比初稿", "百分比草案")
    assert draft.description == "百分比草案"
    assert churchill.read_file(draft) == "百分比初稿"

    churchill.write_file(draft, "百分比修订稿")
    assert churchill.read_file(draft) == "百分比修订稿"

    visible = churchill.list_visible()
    writable = churchill.list_writable()
    assert [f.path.name for f in visible] == ["draft.md"]
    assert [f.path.name for f in writable] == ["draft.md"]
    assert visible[0].description == "百分比草案"

    assert stalin.list_visible() == []
    with pytest.raises(PermissionError):
        stalin.read_file(draft)
    with pytest.raises(PermissionError):
        stalin.write_file(draft, "篡改")
