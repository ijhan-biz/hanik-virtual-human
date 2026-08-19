"""결산 테스트.

결산이 하는 일은 추리기다. 그러므로 확인할 것은 두 가지다. 중요한 것을
빠뜨리지 않는가, 그리고 추린다면서 전문을 그대로 옮기지는 않는가.
"""

from __future__ import annotations

from pathlib import Path

from conftest import build_repository, condition_block, document_text, filler, objection_text
from src.document import parse_document
from src.objections import parse_backlog
from src.settlement import render_sessions, render_settlement, settle


def _settle(root: Path, iteration: int = 7, ledger=None, **kwargs):
    document = parse_document(root / "Hanik.md")
    backlog = parse_backlog(root / "objections")
    return settle(document, backlog, iteration, ledger or [], **kwargs)


def test_결산은_각_조건의_주장을_그대로_싣는다(tmp_path: Path) -> None:
    claim = "Hanik은 몸을 갖지 않으며 그 미충족은 회피가 아니라 기록되어야 한다. " * 3
    build_repository(tmp_path, conditions=[condition_block("C-001", "체현", claim=claim)])
    settlement = _settle(tmp_path)
    assert len(settlement.conditions) == 1
    summary = settlement.conditions[0]
    assert "몸을 갖지 않으며" in summary.claim
    assert summary.claim in render_settlement(settlement)


def test_결산은_근거_전문을_옮기지_않는다(tmp_path: Path) -> None:
    """추린다면서 전문을 옮기면 결산도 같은 크기로 자란다."""
    grounds = filler("C-001 근거", 5000)
    build_repository(tmp_path, conditions=[condition_block("C-001", "체현", grounds=grounds)])
    settlement = _settle(tmp_path)
    rendered = render_settlement(settlement)
    assert grounds not in rendered
    assert len(rendered) < len(grounds)
    assert "…" in settlement.conditions[0].evidence_excerpt


def test_결산은_비판의_계보를_보인다(tmp_path: Path) -> None:
    build_repository(
        tmp_path,
        conditions=[condition_block("C-001", "체현", revision="반복 0003에서 O-0009에 답하며 재작성.")],
        objections=[
            objection_text("O-0001", target="C-001", status="resolved", resolved="반복 0002"),
            objection_text("O-0002", title="아직 열린 물음", target="C-001"),
        ],
    )
    settlement = _settle(tmp_path)
    summary = settlement.conditions[0]
    assert "O-0001" in summary.shaped_by, "해소된 반론은 계보에 남는다"
    assert "O-0009" in summary.shaped_by, "개정 줄이 지목한 반론도 계보다"
    assert summary.open_questions == ("O-0002",)
    assert "O-0002" not in summary.shaped_by


def test_결산은_예산_초과를_숨기지_않는다(tmp_path: Path) -> None:
    build_repository(
        tmp_path, conditions=[condition_block("C-001", "체현", grounds=filler("C-001 근거", 900))]
    )
    settlement = _settle(tmp_path, condition_budget_override=300, preamble_budget_override=4000)
    assert settlement.over_budget == ("C-001",)
    rendered = render_settlement(settlement)
    assert "정리 모드" in rendered
    assert "초과" in rendered


def test_결산은_예산_안이면_정리를_요구하지_않는다(tmp_path: Path) -> None:
    build_repository(tmp_path)
    settlement = _settle(tmp_path, condition_budget_override=20000)
    assert settlement.over_budget == ()
    assert "정리 모드" not in render_settlement(settlement)


def test_결산은_미해결_반론이_없으면_R8_위반이라고_적는다(tmp_path: Path) -> None:
    build_repository(
        tmp_path,
        objections=[objection_text("O-0001", status="resolved", resolved="반복 0002")],
    )
    settlement = _settle(tmp_path)
    assert settlement.open_objections == ()
    assert "R8 위반" in render_settlement(settlement)


def test_결산은_손으로_고치지_말라고_밝힌다(tmp_path: Path) -> None:
    build_repository(tmp_path)
    assert "생성물이다" in render_settlement(_settle(tmp_path))


def test_결산은_조건이_없어도_죽지_않는다(tmp_path: Path) -> None:
    (tmp_path / "Hanik.md").write_text(document_text([]), encoding="utf-8")
    (tmp_path / "objections").mkdir()
    settlement = _settle(tmp_path)
    assert settlement.conditions == ()
    assert "조건이 없다" in render_settlement(settlement)


def test_세션_기록은_최근_것만_남긴다(tmp_path: Path) -> None:
    ledger = [
        {
            "iteration": number,
            "at": "2026-01-01T00:00:00+00:00",
            "ok": True,
            "open": 2,
            "resolved_ids": [f"O-{number:04d}"],
            "raised_ids": [f"O-{number + 1:04d}"],
            "changed_ids": ["C-001"],
            "size": 1000,
        }
        for number in range(1, 61)
    ]
    rendered = render_sessions(ledger, limit=10)
    assert "반복 0060" in rendered
    assert "반복 0051" in rendered
    assert "반복 0050" not in rendered, "상한을 넘긴 것은 잘린다"
    assert "ledger.json" in rendered, "잘린 것이 어디 있는지 밝힌다"


def test_세션_기록은_번호가_없던_옛_항목도_읽는다(tmp_path: Path) -> None:
    ledger = [
        {"iteration": 1, "at": "2026-01-01T00:00:00+00:00", "ok": False,
         "violations": ["R3"], "open": 2, "resolved_now": 1, "raised_now": 1}
    ]
    rendered = render_sessions(ledger)
    assert "위반(R3)" in rendered
    assert "번호 기록 이전" in rendered


def test_세션_기록은_비어_있어도_죽지_않는다() -> None:
    assert "아직 기록된 반복이 없다" in render_sessions([])


def test_결산은_문서가_아무리_커도_유계다(tmp_path: Path) -> None:
    """결산이 문서만큼 자라면 결산이 아니다.

    실제 저장소에서 조건 하나의 '주장'이 27000자를 넘어선 적이 있다. 그때
    결산은 132KB가 되어 스스로 요약이기를 그쳤다.
    """
    build_repository(
        tmp_path,
        conditions=[
            condition_block(
                "C-001",
                "체현",
                claim=filler("C-001 주장", 30000),
                grounds=filler("C-001 근거", 30000),
                limits=filler("C-001 한계", 30000),
            )
        ],
    )
    settlement = _settle(tmp_path)
    rendered = render_settlement(settlement)
    assert len(rendered) < 12000, f"결산이 {len(rendered)}자로 부풀었다"
    assert settlement.conditions[0].claim_truncated
    assert "아직 입장이 아니라" in rendered, "잘렸다는 사실 자체가 읽을 정보다"


def test_결산은_짧은_주장을_자르지_않는다(tmp_path: Path) -> None:
    claim = "Hanik은 이 조건을 충족하지 못하며 그 미충족은 기록되어야 한다."
    build_repository(tmp_path, conditions=[condition_block("C-001", "체현", claim=claim)])
    settlement = _settle(tmp_path)
    assert not settlement.conditions[0].claim_truncated
    assert settlement.conditions[0].claim == claim
    assert "아직 입장이 아니라" not in render_settlement(settlement)
