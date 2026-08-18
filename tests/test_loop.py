"""루프 전체 흐름 테스트.

반복 하나가 실제로 무엇을 남기는지, 그리고 규칙을 어겼을 때 기준이 어떻게 보존되는지
확인한다.
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import build_repository, condition_block, document_text, objection_text
from src.hanik_loop import run
from src.state import load_state


def _state(root: Path):
    state, _ = load_state(root / "state" / "state.json")
    return state


def _honest_resolution(root: Path, iteration: int, new_objection: str = "O-0002") -> None:
    """반론이 요구한 대로 조건을 실제로 고쳐 쓰고, 새 반론을 제기한다."""
    (root / "Hanik.md").write_text(
        document_text(
            [
                condition_block(
                    grounds=f"반복 {iteration}에서 반론에 답하며 근거를 다시 세운다. " * 20,
                    revision=f"반복 {iteration:04d}에서 재작성.",
                )
            ]
        ),
        encoding="utf-8",
    )
    (root / "objections" / "O-0001.md").write_text(
        objection_text(status="resolved", resolved=f"반복 {iteration:04d}에서 C-001 재작성"),
        encoding="utf-8",
    )
    (root / "objections" / f"{new_objection}.md").write_text(
        objection_text(new_objection, title="다시 쓴 근거가 끌어들인 새 전제"), encoding="utf-8"
    )


def test_첫_반복은_통과하고_산출물을_남긴다(repository: Path) -> None:
    assert run(repository) == 0

    assert (repository / "reports" / "iteration-0001.md").is_file()
    assert (repository / "reports" / "index.md").is_file()
    assert (repository / "state" / "state.json").is_file()
    assert (repository / "state" / "ledger.json").is_file()

    brief = (repository / "state" / "next-session.md").read_text(encoding="utf-8")
    assert "O-0001" in brief
    assert "반론은 제기된 뒤 고칠 수 없다" in brief

    state = _state(repository)
    assert state.iteration == 1
    assert state.conditions and state.objections
    assert not state.is_first_run


def test_보고서는_점수를_내지_않는다(repository: Path) -> None:
    run(repository)
    report = (repository / "reports" / "iteration-0001.md").read_text(encoding="utf-8")
    assert "관측 지표" in report
    assert "점수가 아니다" in report
    assert "점수:" not in report


def test_바꾸지_않고_다시_돌리면_실패한다(repository: Path) -> None:
    assert run(repository) == 0
    assert run(repository) == 1

    report = (repository / "reports" / "iteration-0002.md").read_text(encoding="utf-8")
    assert "위반" in report
    assert "R3" in report


def test_위반한_반복은_기준을_갱신하지_않는다(repository: Path) -> None:
    """어긴 상태가 다음 반복의 기준이 되면 위반이 세탁된다."""
    run(repository)
    accepted = _state(repository)

    run(repository)
    after = _state(repository)

    assert after.iteration == 2
    assert after.signature == accepted.signature
    assert after.conditions == accepted.conditions
    assert after.objections == accepted.objections


def test_정직한_해소는_통과한다(repository: Path) -> None:
    assert run(repository) == 0
    _honest_resolution(repository, 2)
    assert run(repository) == 0

    state = _state(repository)
    assert state.iteration == 2
    assert state.objections["O-0001"]["status"] == "resolved"
    assert "O-0002" in state.objections

    report = (repository / "reports" / "iteration-0002.md").read_text(encoding="utf-8")
    assert "O-0001" in report
    assert "O-0002" in report


def test_개정_줄만_고친_해소는_실패한다(repository: Path) -> None:
    assert run(repository) == 0
    (repository / "Hanik.md").write_text(
        document_text([condition_block(revision="반복 0002에서 O-0001에 답함.")]), encoding="utf-8"
    )
    (repository / "objections" / "O-0001.md").write_text(
        objection_text(status="resolved", resolved="반복 0002에서 해소"), encoding="utf-8"
    )
    (repository / "objections" / "O-0002.md").write_text(
        objection_text("O-0002", title="새 반론"), encoding="utf-8"
    )
    assert run(repository) == 1

    report = (repository / "reports" / "iteration-0002.md").read_text(encoding="utf-8")
    assert "R5" in report


def test_실패한_첫_반복_뒤에도_비교_대상이_없으면_면제가_유지된다(tmp_path: Path) -> None:
    build_repository(tmp_path)
    (tmp_path / "Hanik.md").write_text("# Hanik\n\n조건이 없다.\n", encoding="utf-8")
    assert run(tmp_path) == 1
    assert _state(tmp_path).is_first_run

    build_repository(tmp_path)
    assert run(tmp_path) == 0


def test_원장과_인덱스가_모든_반복을_담는다(repository: Path) -> None:
    run(repository)
    _honest_resolution(repository, 2)
    run(repository)

    ledger = json.loads((repository / "state" / "ledger.json").read_text(encoding="utf-8"))
    assert [entry["iteration"] for entry in ledger] == [1, 2]

    index = (repository / "reports" / "index.md").read_text(encoding="utf-8")
    assert "iteration-0001.md" in index
    assert "iteration-0002.md" in index
    assert index.index("0002") < index.index("0001"), "최신순이어야 한다"


def test_브리프는_위반을_먼저_알린다(repository: Path) -> None:
    run(repository)
    run(repository)
    brief = (repository / "state" / "next-session.md").read_text(encoding="utf-8")
    assert "먼저 고칠 것" in brief
    assert "R3" in brief


def test_미해결_반론이_비면_새_반론을_요구한다(repository: Path) -> None:
    (repository / "objections" / "O-0001.md").write_text(
        objection_text(status="resolved", resolved="반복 0000에서 해소"), encoding="utf-8"
    )
    assert run(repository) == 1
    brief = (repository / "state" / "next-session.md").read_text(encoding="utf-8")
    assert "비판이 멈춘 상태" in brief
