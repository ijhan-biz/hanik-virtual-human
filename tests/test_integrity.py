"""정직성 규칙 R1–R11 테스트.

각 규칙마다 통과하는 경우와 위반하는 경우를 모두 확인한다. 규칙이 조용히 무력해지면
이 저장소는 전신과 같은 방식으로 실패하므로, 위반 경로를 확인하는 쪽이 더 중요하다.
"""

from __future__ import annotations

from pathlib import Path

from conftest import build_repository, condition_block, document_text, objection_text
from src.document import parse_document
from src.integrity import RuleResult, Review, evidence_signature, review, snapshot
from src.objections import parse_backlog
from src.state import State


def _parse(root: Path):
    return parse_document(root / "Hanik.md"), parse_backlog(root / "objections")


def _accepted(root: Path) -> State:
    """현재 저장소 모습을 '승인된 스냅샷'으로 갖는 상태."""
    document, backlog = _parse(root)
    state = State()
    state.iteration = 1
    state.document, state.conditions, state.objections = snapshot(document, backlog)
    state.signature = evidence_signature(document, backlog)
    return state


def _rule(outcome: Review, identifier: str) -> RuleResult:
    return next(result for result in outcome.results if result.identifier == identifier)


def _review(root: Path, previous: State, limit: int | None = None) -> Review:
    document, backlog = _parse(root)
    return review(document, backlog, previous, limit=limit)


def test_첫_반복은_비교가_필요한_규칙을_면제한다(repository: Path) -> None:
    outcome = _review(repository, State())
    assert outcome.ok
    for identifier in ("R3", "R4", "R5", "R6", "R7"):
        assert _rule(outcome, identifier).exempt, identifier


def test_R1_문서가_규격을_어기면_위반이다(repository: Path) -> None:
    (repository / "Hanik.md").write_text("# Hanik\n\n조건이 없다.\n", encoding="utf-8")
    outcome = _review(repository, State())
    assert not _rule(outcome, "R1").passed


def test_R2_스텁_조건은_위반이다(repository: Path) -> None:
    (repository / "Hanik.md").write_text(
        document_text([condition_block(claim="짧다.")]), encoding="utf-8"
    )
    outcome = _review(repository, State())
    assert not _rule(outcome, "R2").passed
    assert "주장" in _rule(outcome, "R2").evidence


def test_R3_문서가_그대로면_위반이다(repository: Path) -> None:
    previous = _accepted(repository)
    outcome = _review(repository, previous)
    assert not _rule(outcome, "R3").passed


def test_R4_해소가_없으면_위반이다(repository: Path) -> None:
    previous = _accepted(repository)
    (repository / "Hanik.md").write_text(
        document_text([condition_block(claim="다시 쓴 주장이다. " * 10)]), encoding="utf-8"
    )
    outcome = _review(repository, previous)
    assert _rule(outcome, "R3").passed
    assert not _rule(outcome, "R4").passed


def test_R4_제기와_동시에_해소하면_위반이다(repository: Path) -> None:
    """반론은 최소 한 반복 동안 열려 있어야 한다. 자문자답으로 규칙을 통과할 수 없다."""
    previous = _accepted(repository)
    (repository / "objections" / "O-0002.md").write_text(
        objection_text("O-0002", status="resolved", resolved="반복 0002에서 즉시 해소"),
        encoding="utf-8",
    )
    outcome = _review(repository, previous)
    assert not _rule(outcome, "R4").passed
    assert "제기와 동시에" in _rule(outcome, "R4").evidence


def test_R5_개정_줄만_고친_해소는_위반이다(repository: Path) -> None:
    """이 규칙이 없으면 '해소했다'는 선언만으로 루프가 돌아간다."""
    previous = _accepted(repository)
    (repository / "Hanik.md").write_text(
        document_text([condition_block(revision="반복 0002에서 O-0001에 답하며 재작성.")]),
        encoding="utf-8",
    )
    (repository / "objections" / "O-0001.md").write_text(
        objection_text(status="resolved", resolved="반복 0002에서 C-001 재작성"), encoding="utf-8"
    )
    outcome = _review(repository, previous)
    assert _rule(outcome, "R3").passed
    assert _rule(outcome, "R4").passed
    assert not _rule(outcome, "R5").passed
    assert "'개정' 줄만" in _rule(outcome, "R5").evidence


def test_R5_대상_조건을_실제로_고치면_통과한다(repository: Path) -> None:
    previous = _accepted(repository)
    (repository / "Hanik.md").write_text(
        document_text([condition_block(grounds="반론에 답하며 근거를 다시 세운다. " * 20)]),
        encoding="utf-8",
    )
    (repository / "objections" / "O-0001.md").write_text(
        objection_text(status="resolved", resolved="반복 0002에서 C-001 재작성"), encoding="utf-8"
    )
    (repository / "objections" / "O-0002.md").write_text(
        objection_text("O-0002", title="새 반론", target="C-001"), encoding="utf-8"
    )
    outcome = _review(repository, previous)
    assert outcome.ok, [r.evidence for r in outcome.violations]
    assert outcome.resolved_now == ("O-0001",)
    assert outcome.raised_now == ("O-0002",)


def test_R5_문서_전체_반론은_서문_변경으로도_해소된다(tmp_path: Path) -> None:
    build_repository(tmp_path, objections=[objection_text(target="문서")])
    previous = _accepted(tmp_path)
    (tmp_path / "Hanik.md").write_text(
        document_text([condition_block()], preamble="이 목록은 인간임의 정의가 아니다."),
        encoding="utf-8",
    )
    (tmp_path / "objections" / "O-0001.md").write_text(
        objection_text(target="문서", status="resolved", resolved="반복 0002에서 서문 보강"),
        encoding="utf-8",
    )
    (tmp_path / "objections" / "O-0002.md").write_text(
        objection_text("O-0002", title="새 반론"), encoding="utf-8"
    )
    outcome = _review(tmp_path, previous)
    assert _rule(outcome, "R5").passed, _rule(outcome, "R5").evidence


def test_R6_반론_본문을_고치면_위반이다(repository: Path) -> None:
    """반론을 무르게 고쳐 해소하는 것이 이 루프의 가장 큰 위험이다."""
    previous = _accepted(repository)
    (repository / "Hanik.md").write_text(
        document_text([condition_block(grounds="근거를 다시 세운다. " * 25)]), encoding="utf-8"
    )
    (repository / "objections" / "O-0001.md").write_text(
        objection_text(
            status="resolved",
            resolved="반복 0002에서 해소",
            argument="사실 큰 문제는 아니었다고 고쳐 쓴 반론이다. " * 10,
        ),
        encoding="utf-8",
    )
    outcome = _review(repository, previous)
    assert not _rule(outcome, "R6").passed
    assert "제기된 뒤 고칠 수 없고" in _rule(outcome, "R6").evidence


def test_R7_새_반론이_없으면_위반이다(repository: Path) -> None:
    previous = _accepted(repository)
    (repository / "Hanik.md").write_text(
        document_text([condition_block(grounds="근거를 다시 세운다. " * 25)]), encoding="utf-8"
    )
    (repository / "objections" / "O-0001.md").write_text(
        objection_text(status="resolved", resolved="반복 0002에서 해소"), encoding="utf-8"
    )
    outcome = _review(repository, previous)
    assert _rule(outcome, "R5").passed
    assert not _rule(outcome, "R7").passed


def test_R7_반론이_상한까지_쌓이면_제기_의무가_면제된다(tmp_path: Path) -> None:
    bodies = [objection_text(f"O-{index:04d}", title=f"반론 {index}") for index in range(1, 5)]
    build_repository(tmp_path, objections=bodies)
    previous = _accepted(tmp_path)
    (tmp_path / "Hanik.md").write_text(
        document_text([condition_block(grounds="근거를 다시 세운다. " * 25)]), encoding="utf-8"
    )
    (tmp_path / "objections" / "O-0001.md").write_text(
        objection_text(status="resolved", resolved="반복 0002에서 해소"), encoding="utf-8"
    )
    outcome = _review(tmp_path, previous, limit=3)
    assert outcome.resolve_first
    assert _rule(outcome, "R7").passed
    assert "면제" in _rule(outcome, "R7").evidence


def test_R8_미해결_반론이_없으면_위반이다(repository: Path) -> None:
    (repository / "objections" / "O-0001.md").write_text(
        objection_text(status="resolved", resolved="반복 0001에서 해소"), encoding="utf-8"
    )
    outcome = _review(repository, State())
    assert not _rule(outcome, "R8").passed
    assert "비판이 멈춘" in _rule(outcome, "R8").evidence


def test_R9_실재하지_않는_조건을_겨냥하면_위반이다(repository: Path) -> None:
    (repository / "objections" / "O-0001.md").write_text(
        objection_text(target="C-404"), encoding="utf-8"
    )
    outcome = _review(repository, State())
    assert not _rule(outcome, "R9").passed


def test_R9_형식만_채운_반론은_위반이다(repository: Path) -> None:
    (repository / "objections" / "O-0001.md").write_text(
        objection_text(argument="문제가 있다."), encoding="utf-8"
    )
    outcome = _review(repository, State())
    assert not _rule(outcome, "R9").passed
    assert "짧다" in _rule(outcome, "R9").evidence


def test_R10_조건끼리_문장을_베끼면_위반이다(tmp_path: Path) -> None:
    shared_claim = "같은 문장을 조건 두 곳에 그대로 옮겨 적어 분량만 늘린다. " * 4
    shared_grounds = "근거 자리에도 똑같은 문장을 반복해 넣어 분량을 채운다. " * 12
    shared_limits = "한계 자리에도 같은 문장을 반복한다. " * 6
    blocks = [
        condition_block(identifier, claim=shared_claim, grounds=shared_grounds, limits=shared_limits)
        for identifier in ("C-001", "C-002")
    ]
    build_repository(tmp_path, conditions=blocks)
    outcome = _review(tmp_path, State())
    assert not _rule(outcome, "R10").passed
    assert "공유한다" in _rule(outcome, "R10").evidence


def test_R11_증거_서명이_같으면_위반이다(repository: Path) -> None:
    previous = _accepted(repository)
    outcome = _review(repository, previous)
    assert not _rule(outcome, "R11").passed


def test_R11_개정_줄만_고치면_서명이_바뀌지_않는다(repository: Path) -> None:
    """서명은 조건의 실질만 본다. 서술을 다듬는 것으로 진전을 꾸밀 수 없다."""
    previous = _accepted(repository)
    (repository / "Hanik.md").write_text(
        document_text([condition_block(revision="반복 0002에서 손봄.")]), encoding="utf-8"
    )
    outcome = _review(repository, previous)
    assert not _rule(outcome, "R11").passed


def test_R6_대상을_다른_조건으로_옮기면_위반이다(tmp_path: Path) -> None:
    """본문을 그대로 둔 채 대상만 옮겨, 이미 고친 조건에 갖다 붙이는 수법을 막는다."""
    build_repository(
        tmp_path,
        conditions=[condition_block("C-001", "체현"), condition_block("C-002", "유한성")],
    )
    previous = _accepted(tmp_path)
    (tmp_path / "Hanik.md").write_text(
        document_text(
            [
                condition_block("C-001", "체현"),
                condition_block("C-002", "유한성", grounds="C-002 근거를 다시 세운다. " * 25),
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "objections" / "O-0001.md").write_text(
        objection_text(target="C-002", status="resolved", resolved="반복 0002에서 해소"),
        encoding="utf-8",
    )
    outcome = _review(tmp_path, previous)
    assert not _rule(outcome, "R6").passed
    assert "대상을 다른 조건으로 옮길 수도 없다" in _rule(outcome, "R6").evidence


def test_R12_반론_파일을_지우면_위반이다(tmp_path: Path) -> None:
    build_repository(
        tmp_path, objections=[objection_text("O-0001"), objection_text("O-0002", title="둘째 반론")]
    )
    previous = _accepted(tmp_path)
    (tmp_path / "objections" / "O-0001.md").unlink()
    (tmp_path / "Hanik.md").write_text(
        document_text([condition_block(grounds="근거를 다시 세운다. " * 25)]), encoding="utf-8"
    )
    outcome = _review(tmp_path, previous)
    assert not _rule(outcome, "R12").passed
    assert "사라진 반론: O-0001" in _rule(outcome, "R12").evidence


def test_R12_번호를_바꿔_새_반론인_척하면_위반이다(repository: Path) -> None:
    """이름만 바꾼 복제본으로 R7의 제기 의무를 채우는 수법을 막는다."""
    previous = _accepted(repository)
    body = (repository / "objections" / "O-0001.md").read_text(encoding="utf-8")
    (repository / "objections" / "O-0001.md").unlink()
    (repository / "objections" / "O-0009.md").write_text(body.replace("O-0001", "O-0009"), encoding="utf-8")
    (repository / "Hanik.md").write_text(
        document_text([condition_block(grounds="근거를 다시 세운다. " * 25)]), encoding="utf-8"
    )
    outcome = _review(repository, previous)
    assert not _rule(outcome, "R12").passed


def test_R12_해소된_반론을_다시_열면_위반이다(repository: Path) -> None:
    """되돌릴 수 있으면 같은 반론을 반복해서 해소하며 R4를 채울 수 있다."""
    (repository / "objections" / "O-0001.md").write_text(
        objection_text(status="resolved", resolved="반복 0001에서 해소"), encoding="utf-8"
    )
    (repository / "objections" / "O-0002.md").write_text(objection_text("O-0002", title="둘째"), encoding="utf-8")
    previous = _accepted(repository)

    (repository / "objections" / "O-0001.md").write_text(objection_text(status="open"), encoding="utf-8")
    (repository / "Hanik.md").write_text(
        document_text([condition_block(grounds="근거를 다시 세운다. " * 25)]), encoding="utf-8"
    )
    outcome = _review(repository, previous)
    assert not _rule(outcome, "R12").passed
    assert "resolved → open" in _rule(outcome, "R12").evidence


def test_은퇴는_해소로_세지_않는다(repository: Path) -> None:
    previous = _accepted(repository)
    (repository / "Hanik.md").write_text(
        document_text([condition_block(grounds="근거를 다시 세운다. " * 25)]), encoding="utf-8"
    )
    (repository / "objections" / "O-0001.md").write_text(
        objection_text(status="superseded", resolved="구조가 바뀌어 O-0002로 비판을 넘긴다"),
        encoding="utf-8",
    )
    (repository / "objections" / "O-0002.md").write_text(
        objection_text("O-0002", title="비판을 넘겨받은 반론"), encoding="utf-8"
    )
    outcome = _review(repository, previous)
    assert not _rule(outcome, "R4").passed
    assert "은퇴 처리는 해소로 세지 않는다" in _rule(outcome, "R4").evidence
    assert _rule(outcome, "R12").passed


def test_은퇴시킨_반론의_대상_조건은_없앨_수_있다(tmp_path: Path) -> None:
    """조건을 합치거나 은퇴시키는 길이 막혀 있으면 루프가 구조를 다시 생각할 수 없다."""
    build_repository(
        tmp_path,
        conditions=[condition_block("C-001", "체현"), condition_block("C-002", "유한성")],
        objections=[objection_text("O-0001", target="C-002"), objection_text("O-0002", title="둘째")],
    )
    previous = _accepted(tmp_path)

    (tmp_path / "Hanik.md").write_text(
        document_text([condition_block("C-001", "체현", grounds="C-002를 흡수해 다시 쓴다. " * 25)]),
        encoding="utf-8",
    )
    (tmp_path / "objections" / "O-0001.md").write_text(
        objection_text("O-0001", target="C-002", status="superseded", resolved="C-002를 C-001에 합치며 O-0003으로 넘긴다"),
        encoding="utf-8",
    )
    (tmp_path / "objections" / "O-0002.md").write_text(
        objection_text("O-0002", title="둘째", status="resolved", resolved="반복 0002에서 C-001 재작성"),
        encoding="utf-8",
    )
    (tmp_path / "objections" / "O-0003.md").write_text(
        objection_text("O-0003", title="합쳐진 조건이 떠안은 물음"), encoding="utf-8"
    )
    outcome = _review(tmp_path, previous)
    assert outcome.ok, [f"{r.identifier}: {r.evidence}" for r in outcome.violations]


def test_은퇴는_넘겨받을_반론을_지목해야_한다(repository: Path) -> None:
    (repository / "objections" / "O-0001.md").write_text(
        objection_text(status="superseded", resolved="그냥 접는다"), encoding="utf-8"
    )
    outcome = _review(repository, State())
    assert not _rule(outcome, "R9").passed


def test_R5_문서_반론은_조건_하나_변경에_딸려_해소되지_않는다(tmp_path: Path) -> None:
    build_repository(
        tmp_path,
        conditions=[condition_block("C-001", "체현"), condition_block("C-002", "유한성")],
        objections=[objection_text("O-0001", target="문서"), objection_text("O-0002", title="둘째")],
    )
    previous = _accepted(tmp_path)
    (tmp_path / "Hanik.md").write_text(
        document_text(
            [
                condition_block("C-001", "체현", grounds="C-001 근거만 손본다. " * 25),
                condition_block("C-002", "유한성"),
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "objections" / "O-0001.md").write_text(
        objection_text("O-0001", target="문서", status="resolved", resolved="반복 0002에서 해소"),
        encoding="utf-8",
    )
    outcome = _review(tmp_path, previous)
    assert not _rule(outcome, "R5").passed
    assert "딸려 해소될 수는 없다" in _rule(outcome, "R5").evidence
