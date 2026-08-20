"""보고가 대량 삭감을 드러내는지 확인한다.

R13이 처음으로 실제 문서에 걸린 반복에서 실질 분량이 302,010자에서 2,547자로
줄었다. 모든 규칙이 통과했고 보고서는 '통과'라고만 적었다. 규칙이 이것을 막지
않는 것은 옳다 — 무엇이 남고 무엇이 사라졌는지는 기계가 판정할 수 없고, 판정할 수
없는 것을 막으면 정당한 압축까지 함께 막힌다. 그러나 사람이 읽어야 한다는 사실이
보고서에 없으면 아무도 읽지 않는다.
"""

from __future__ import annotations

from src.document import parse_document
from src.integrity import Review
from src.objections import parse_backlog
from src.reporting import (
    LARGE_CUT,
    Metrics,
    large_cut,
    render_brief,
    render_report,
)

from conftest import build_repository


def _review(previous_size: int | None) -> Review:
    return Review(
        results=(),
        signature="0123456789abcdef",
        resolved_now=("O-0001",),
        raised_now=("O-0002",),
        superseded_now=(),
        changed_conditions=("C-001",),
        resolve_first=False,
        size=2547,
        budget=100_000,
        previous_size=previous_size,
    )


def _metrics(substance: int) -> Metrics:
    return Metrics(
        conditions=1,
        document_length=substance,
        substance_length=substance,
        open_objections=1,
        resolved_objections=1,
        changed_conditions=1,
        resolved_now=1,
        raised_now=1,
    )


def test_실질_분량의_절반_이상이_사라지면_대량_삭감이다() -> None:
    assert large_cut(_review(1000), _metrics(400)) == 0.6
    assert large_cut(_review(302010), _metrics(2547)) is not None


def test_조금_줄어든_것은_대량_삭감이_아니다() -> None:
    assert large_cut(_review(1000), _metrics(900)) is None


def test_늘어난_것은_대량_삭감이_아니다() -> None:
    assert large_cut(_review(1000), _metrics(1200)) is None


def test_비교할_직전_분량이_없으면_판정하지_않는다() -> None:
    assert large_cut(_review(None), _metrics(400)) is None


def test_경계에서는_대량_삭감으로_친다() -> None:
    assert large_cut(_review(1000), _metrics(int(1000 * (1 - LARGE_CUT)))) is not None


def test_보고서가_대량_삭감을_알리고_읽으라고_말한다(tmp_path) -> None:
    root = build_repository(tmp_path)
    document = parse_document(root / "Hanik.md")
    backlog = parse_backlog(root / "objections")

    report = render_report(3, document, backlog, _review(302010), _metrics(2547), [])
    assert "덜어냈다" in report
    assert "git diff" in report
    assert "직전 302010자에서 -299463자" in report

    quiet = render_report(3, document, backlog, _review(2600), _metrics(2547), [])
    assert "덜어냈다" not in quiet


def test_브리프가_다음_세션에게_사라진_것을_확인하라고_말한다(tmp_path) -> None:
    root = build_repository(tmp_path)
    document = parse_document(root / "Hanik.md")
    backlog = parse_backlog(root / "objections")

    brief = render_brief(3, document, backlog, _review(302010), _metrics(2547))
    assert "덜어냈다" in brief
    assert "되살려야 할 논증" in brief


def _crowded_review(size: int, budget: int = 100_000) -> Review:
    return Review(
        results=(),
        signature="0123456789abcdef",
        resolved_now=("O-0001",),
        raised_now=("O-0002",),
        superseded_now=(),
        changed_conditions=("C-001",),
        resolve_first=False,
        size=size,
        budget=budget,
        previous_size=size,
    )


def test_예산에_바짝_붙으면_넘기_전에_알린다(tmp_path) -> None:
    """R13은 넘어야만 문다. 그래서 예산선에 붙으면 세션이 안내 없이 위반한다.

    반복 2830-2834가 실제로 같은 100,001자 문서를 다섯 번 내놓고 정체로 끝났다.
    """
    root = build_repository(tmp_path)
    document = parse_document(root / "Hanik.md")
    backlog = parse_backlog(root / "objections")

    review = _crowded_review(100_000)
    assert review.crowded and not review.consolidating
    brief = render_brief(3, document, backlog, review, _metrics(2547))
    assert "먼저: 정리한다" in brief
    assert "바짝 붙었다" in brief
    assert "0자 남음" in brief


def test_여유가_있으면_정리를_말하지_않는다(tmp_path) -> None:
    root = build_repository(tmp_path)
    document = parse_document(root / "Hanik.md")
    backlog = parse_backlog(root / "objections")

    review = _crowded_review(50_000)
    assert not review.crowded and not review.consolidating
    assert "먼저: 정리한다" not in render_brief(3, document, backlog, review, _metrics(2547))
