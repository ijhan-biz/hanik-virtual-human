"""상태 저장 테스트."""

from __future__ import annotations

import json
from pathlib import Path

from src.state import (
    SCHEMA_VERSION,
    State,
    history_limit,
    load_ledger,
    load_state,
    save_ledger,
    save_state,
)


def test_없는_파일은_새_상태로_시작한다(tmp_path: Path) -> None:
    state, notes = load_state(tmp_path / "state.json")
    assert state.iteration == 0
    assert state.is_first_run
    assert notes == []


def test_깨진_JSON은_예외_대신_복구된다(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text('{"iteration": 3, "condi', encoding="utf-8")
    state, notes = load_state(path)
    assert state.iteration == 0
    assert any("읽을 수 없다" in note for note in notes)


def test_최상위가_객체가_아니면_복구된다(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    state, notes = load_state(path)
    assert state.iteration == 0
    assert notes


def test_알_수_없는_스키마는_복구된다(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"version": SCHEMA_VERSION + 1, "iteration": 9}), encoding="utf-8")
    state, notes = load_state(path)
    assert state.iteration == 0
    assert any("스키마" in note for note in notes)


def test_어긋난_필드만_되돌리고_나머지는_지킨다(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "version": SCHEMA_VERSION,
                "iteration": -4,
                "conditions": {"C-001": {"digest": "a", "substance_digest": "b"}},
                "objections": "형식이 어긋난 값",
                "history": [{"iteration": 1}],
            }
        ),
        encoding="utf-8",
    )
    state, notes = load_state(path)
    assert state.iteration == 0
    assert state.conditions == {"C-001": {"digest": "a", "substance_digest": "b"}}
    assert state.objections == {}
    assert any("반론 스냅샷" in note for note in notes)


def test_첫_반복_판정은_반복_번호가_아니라_스냅샷을_본다() -> None:
    """규칙을 어긴 첫 반복 뒤에도 비교 대상이 없으면 여전히 첫 반복이다."""
    state = State()
    state.iteration = 7
    assert state.is_first_run
    state.conditions = {"C-001": {"digest": "a", "substance_digest": "b"}}
    assert not state.is_first_run


def test_상태를_읽고_다시_쓸_수_있다(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    state = State()
    state.iteration = 2
    state.conditions = {"C-001": {"digest": "a", "substance_digest": "b"}}
    state.signature = "서명"
    save_state(path, state)

    restored, notes = load_state(path)
    assert notes == []
    assert restored.iteration == 2
    assert restored.signature == "서명"
    assert restored.conditions == state.conditions
    assert restored.updated_at


def test_이력은_상한까지만_남는다(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    state = State()
    state.history = [{"iteration": index} for index in range(1, 11)]
    save_state(path, state, limit=4)

    restored, _ = load_state(path)
    assert [entry["iteration"] for entry in restored.history] == [7, 8, 9, 10]


def test_원장은_잘리지_않는다(tmp_path: Path) -> None:
    """state.json의 이력이 잘려도 인덱스용 원장에는 전부 남아야 한다."""
    path = tmp_path / "ledger.json"
    entries = [{"iteration": index, "ok": True} for index in range(1, 121)]
    save_ledger(path, entries)
    assert load_ledger(path) == entries


def test_깨진_원장은_빈_목록으로_복구된다(tmp_path: Path) -> None:
    path = tmp_path / "ledger.json"
    path.write_text("{망가짐", encoding="utf-8")
    assert load_ledger(path) == []


def test_쓰기는_임시_파일을_남기지_않는다(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    save_state(path, State())
    leftovers = [item.name for item in tmp_path.iterdir() if item.name.startswith(".")]
    assert leftovers == []


def test_이력_상한_환경변수를_읽는다() -> None:
    assert history_limit({"HANIK_HISTORY_LIMIT": "7"}) == 7
    assert history_limit({"HANIK_HISTORY_LIMIT": "0"}) > 0
    assert history_limit({"HANIK_HISTORY_LIMIT": "숫자아님"}) > 0
