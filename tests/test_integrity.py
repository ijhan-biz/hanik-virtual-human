"""정직성 규칙 R1–R14 테스트.

각 규칙마다 통과하는 경우와 위반하는 경우를 모두 확인한다. 규칙이 조용히 무력해지면
이 저장소는 전신과 같은 방식으로 실패하므로, 위반 경로를 확인하는 쪽이 더 중요하다.
"""

from __future__ import annotations

from pathlib import Path

from conftest import build_repository, condition_block, document_text, filler, objection_text
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
        document_text([
            condition_block(
                "C-001",
                "체현",
                grounds="C-002를 흡수해 다시 쓴다. " * 25,
                revision="반복 0002에서 O-0001을 은퇴시키며 C-002를 흡수했다.",
            )
        ]),
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


def _budgeted(monkeypatch, document: int = 500) -> None:
    monkeypatch.setenv("HANIK_DOCUMENT_BUDGET", str(document))


def test_R13_예산_안이면_통과한다(repository: Path, monkeypatch) -> None:
    _budgeted(monkeypatch, document=100_000)
    outcome = _review(repository, _accepted(repository))
    assert _rule(outcome, "R13").passed
    assert not outcome.consolidating
    assert outcome.overage == 0


def test_R13_예산을_넘겼는데_늘어나면_위반이다(repository: Path, monkeypatch) -> None:
    _budgeted(monkeypatch)
    previous = _accepted(repository)
    (repository / "Hanik.md").write_text(
        document_text([condition_block(grounds=filler("C-001 근거", 900))]), encoding="utf-8"
    )
    outcome = _review(repository, previous)
    assert not _rule(outcome, "R13").passed
    assert outcome.consolidating
    assert "큰 구획부터" in _rule(outcome, "R13").evidence


def test_R13_예산을_넘겨도_줄어들면_통과한다(repository: Path, monkeypatch) -> None:
    _budgeted(monkeypatch)
    (repository / "Hanik.md").write_text(
        document_text([condition_block(grounds=filler("C-001 근거", 900))]), encoding="utf-8"
    )
    previous = _accepted(repository)
    (repository / "Hanik.md").write_text(
        document_text([condition_block(grounds=filler("C-001 근거", 320))]), encoding="utf-8"
    )
    outcome = _review(repository, previous)
    assert _rule(outcome, "R13").passed
    assert outcome.consolidating, "여전히 예산은 넘지만 줄었으므로 통과한다"
    assert "줄었다" in _rule(outcome, "R13").evidence


def test_R13_한_구획이_커도_문서가_예산_안이면_묻지_않는다(
    repository: Path, monkeypatch
) -> None:
    """예산은 문서 전체에 걸린다. 한 조건이 유난히 긴 것은 그 자체로 위반이 아니다.

    어디에 분량을 쓸지는 탐구의 몫이다. 한 조건이 어려워 길어지고 그 대가로
    다른 조건이 짧아지는 배분을 규칙이 대신 정해서는 안 된다.
    """
    _budgeted(monkeypatch, document=100_000)
    previous = _accepted(repository)
    (repository / "Hanik.md").write_text(
        document_text([condition_block(grounds=filler("C-001 근거", 5000))]), encoding="utf-8"
    )
    outcome = _review(repository, previous)
    assert _rule(outcome, "R13").passed
    assert not outcome.consolidating


def test_R13_첫_반복은_면제된다(repository: Path, monkeypatch) -> None:
    _budgeted(monkeypatch, document=10)
    outcome = _review(repository, State())
    assert _rule(outcome, "R13").exempt


def test_R14_조건이_자취_없이_사라지면_위반이다(tmp_path: Path) -> None:
    build_repository(
        tmp_path,
        conditions=[condition_block("C-001", "체현"), condition_block("C-002", "유한성")],
        objections=[objection_text("O-0001", target="C-001")],
    )
    previous = _accepted(tmp_path)
    (tmp_path / "Hanik.md").write_text(
        document_text([condition_block("C-001", "체현", claim="다시 쓴 주장이다. " * 12)]),
        encoding="utf-8",
    )
    outcome = _review(tmp_path, previous)
    assert not _rule(outcome, "R14").passed
    assert "C-002" in _rule(outcome, "R14").evidence


def test_R14_개정에_자취를_남기면_조건을_합칠_수_있다(tmp_path: Path) -> None:
    build_repository(
        tmp_path,
        conditions=[condition_block("C-001", "체현"), condition_block("C-002", "유한성")],
        objections=[objection_text("O-0001", target="C-001")],
    )
    previous = _accepted(tmp_path)
    (tmp_path / "Hanik.md").write_text(
        document_text([
            condition_block(
                "C-001",
                "체현",
                claim="다시 쓴 주장이다. " * 12,
                revision="반복 0002에서 C-002를 흡수했다.",
            )
        ]),
        encoding="utf-8",
    )
    outcome = _review(tmp_path, previous)
    assert _rule(outcome, "R14").passed
    assert "C-002 → C-001" in _rule(outcome, "R14").evidence


def test_R14_분량을_맞추려_조건을_지우는_길을_막는다(tmp_path: Path, monkeypatch) -> None:
    """R13이 여는 구멍을 R14가 닫는지 확인한다.

    조건을 통째로 지우면 분량은 확실히 줄어 R13은 통과한다. 그것만으로 정리가
    되어버리면 R13은 삭제 유인이 된다.
    """
    _budgeted(monkeypatch)
    build_repository(
        tmp_path,
        conditions=[
            condition_block("C-001", "체현", grounds=filler("C-001 근거", 900)),
            condition_block("C-002", "유한성", grounds=filler("C-002 근거", 900)),
        ],
        objections=[objection_text("O-0001", target="C-001")],
    )
    previous = _accepted(tmp_path)
    (tmp_path / "Hanik.md").write_text(
        document_text([condition_block("C-001", "체현", grounds=filler("C-001 근거", 900))]),
        encoding="utf-8",
    )
    outcome = _review(tmp_path, previous)
    assert _rule(outcome, "R13").passed, "지웠으니 분량은 줄었다"
    assert not _rule(outcome, "R14").passed, "그러나 삭제는 정리가 아니다"


def test_R13_예산은_개정_이력까지_센다(repository: Path, monkeypatch) -> None:
    """개정은 반복마다 한 줄씩 쌓이므로 예산 밖에 두면 무한히 자란다.

    R5가 개정을 실질에서 빼는 것은 개정 줄만 고쳐 변경을 위장하는 것을 막기
    위해서다. 그 이유는 예산에는 해당하지 않는다 — 읽는 사람에게 개정 이력은
    다른 문장과 똑같이 읽어야 할 글이다.
    """
    _budgeted(monkeypatch, document=900)
    previous = _accepted(repository)
    (repository / "Hanik.md").write_text(
        document_text([condition_block(revision=filler("반복 0002에서 재작성", 900))]),
        encoding="utf-8",
    )
    outcome = _review(repository, previous)
    assert outcome.consolidating, "개정만 부풀어도 예산을 넘는다"
    assert not _rule(outcome, "R13").passed


def test_R13_개정을_쳐내면_정리로_인정된다(repository: Path, monkeypatch) -> None:
    """개정을 예산에 넣었으므로 그것을 줄이는 것도 정리다.

    기록이 사라지지는 않는다. 반복마다의 변경은 reports/와 state/ledger.json에
    잘리지 않고 남는다. 문서 안의 개정 줄은 그 기록의 사본이지 원본이 아니다.
    """
    _budgeted(monkeypatch, document=500)
    (repository / "Hanik.md").write_text(
        document_text([condition_block(revision=filler("반복 0002에서 재작성", 900))]),
        encoding="utf-8",
    )
    previous = _accepted(repository)
    (repository / "Hanik.md").write_text(
        document_text([condition_block(revision="반복 0003에서 오래된 개정 이력을 쳐냈다.")]),
        encoding="utf-8",
    )
    outcome = _review(repository, previous)
    assert _rule(outcome, "R13").passed
    assert outcome.consolidating, "아직 예산은 넘지만 줄었으므로 통과한다"
    assert "줄었다" in _rule(outcome, "R13").evidence


def _many_objections(target: str, count: int, start: int = 1) -> list[str]:
    return [
        objection_text(f"O-{start + i:04d}", target=target, status="resolved",
                       resolved=f"반복 {start + i:04d}에서 해소")
        for i in range(count)
    ]


def test_R15_최근_반론이_모두_한_조건이면_위반이다(tmp_path: Path) -> None:
    """세션은 방금 고친 논증에서 새 반론을 뽑으므로 비판이 한 조건에 갇힌다.

    실제로 O-0168 이후 687개의 반론이 모두 C-003만 겨냥했고, 그 조건은 문서의
    98%가 되었으며 나머지 둘은 최소 분량에 머물렀다.
    """
    build_repository(
        tmp_path,
        conditions=[condition_block("C-001", "체현"), condition_block("C-002", "유한성")],
        objections=_many_objections("C-002", 8),
    )
    outcome = _review(tmp_path, _accepted(tmp_path))
    assert not _rule(outcome, "R15").passed
    assert "C-002만 겨냥한다" in _rule(outcome, "R15").evidence
    assert "C-001" in _rule(outcome, "R15").evidence, "갈 곳을 알려준다"


def test_R15_대상이_갈리면_통과한다(tmp_path: Path) -> None:
    objections = _many_objections("C-002", 7)
    objections.append(objection_text("O-0008", target="C-001"))
    build_repository(
        tmp_path,
        conditions=[condition_block("C-001", "체현"), condition_block("C-002", "유한성")],
        objections=objections,
    )
    outcome = _review(tmp_path, _accepted(tmp_path))
    assert _rule(outcome, "R15").passed


def test_R15_반론이_적으면_쏠림을_말하지_않는다(tmp_path: Path) -> None:
    """한 조건을 여러 반복에 걸쳐 파고드는 것은 정당하다. 막는 것은 그것의 영구화다."""
    build_repository(
        tmp_path,
        conditions=[condition_block("C-001", "체현"), condition_block("C-002", "유한성")],
        objections=_many_objections("C-002", 3),
    )
    outcome = _review(tmp_path, _accepted(tmp_path))
    assert _rule(outcome, "R15").passed
    assert "쏠림을 말할 수 없다" in _rule(outcome, "R15").evidence


def test_R15_조건이_하나면_묻지_않는다(tmp_path: Path) -> None:
    """비판이 갈 곳이 하나뿐이면 쏠림은 잘못이 아니다."""
    build_repository(
        tmp_path,
        conditions=[condition_block("C-001", "체현")],
        objections=_many_objections("C-001", 8),
    )
    outcome = _review(tmp_path, _accepted(tmp_path))
    assert _rule(outcome, "R15").passed
    assert "갈 곳도 하나다" in _rule(outcome, "R15").evidence
