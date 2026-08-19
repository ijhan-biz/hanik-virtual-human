"""보고서, 인덱스, 다음 세션 브리프.

점수를 내지 않는다. 세는 것만 센다. 점수는 이 저장소의 전신을 망친 장치이고,
비판의 질은 숫자로 환원되지 않는다.

모든 경로는 저장소 상대 경로로만 쓴다. 보고서가 이 기계의 파일 구조를 흘리지
않도록 하기 위해서다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import text as textutil
from .conclusion import CONTINUE, Conclusion
from .document import Document, condition_size, document_size, full_size
from .integrity import Review, largest_sections
from .objections import Backlog, Objection

REPORT_PREFIX = "iteration-"
INDEX_NAME = "index.md"
BRIEF_NAME = "next-session.md"

_ITERATION_NUMBER = re.compile(r"(\d+)")


@dataclass(frozen=True)
class Metrics:
    """관측 지표. 판정이 아니라 계수다."""

    conditions: int
    document_length: int
    substance_length: int
    open_objections: int
    resolved_objections: int
    changed_conditions: int
    resolved_now: int
    raised_now: int


def measure(document: Document, backlog: Backlog, review: Review) -> Metrics:
    # 예산과 같은 잣대다. '개정'까지 세는 것은 읽는 사람이 그것도 읽기 때문이다.
    length = full_size(document)
    return Metrics(
        conditions=len(document.conditions),
        document_length=length,
        substance_length=document_size(document),
        open_objections=len(backlog.open_items),
        resolved_objections=len(backlog.resolved_items),
        changed_conditions=len(review.changed_conditions),
        resolved_now=len(review.resolved_now),
        raised_now=len(review.raised_now),
    )


# 한 반복에서 실질 분량이 이 비율 이상 줄면 보고서와 브리프가 따로 알린다. 정리는
# 갈아내는 일이지 지우는 일이므로, 절반이 한 번에 사라졌다면 사람이 읽어야 한다.
# 막지는 않는다 — 무엇이 남고 무엇이 사라졌는지는 기계가 판정할 수 없고, 판정할 수
# 없는 것을 막으면 정당한 압축까지 함께 막힌다. 대신 놓칠 수 없게 만든다.
LARGE_CUT = 0.5


def _delta(review: Review, metrics: Metrics) -> str:
    """직전 반복과의 분량 차이. 예산과 같은 잣대(개정 포함)로 잰다."""
    before = review.previous_size
    if before is None or before == metrics.document_length:
        return ""
    return f" (직전 {before}자에서 {metrics.document_length - before:+d}자)"


def large_cut(review: Review, metrics: Metrics) -> float | None:
    """이번 반복이 분량을 크게 덜어냈으면 그 비율. 아니면 None."""
    before = review.previous_size
    if not before or metrics.document_length >= before:
        return None
    removed = (before - metrics.document_length) / before
    return removed if removed >= LARGE_CUT else None


def raised_at(objection: Objection) -> int:
    match = _ITERATION_NUMBER.search(objection.raised)
    return int(match.group(1)) if match else 0

def priority_order(backlog: Backlog) -> tuple[Objection, ...]:
    """오래 열려 있던 반론이 먼저다. 쉬운 것만 골라 잡는 일을 막는다."""
    return tuple(sorted(backlog.open_items, key=lambda o: (raised_at(o), o.identifier)))


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _excerpt(body: str, limit: int = 400) -> str:
    """본문을 한 흐름으로 이어 붙여 발췌한다.

    첫 문단만 뽑으면 '다음을 갖출 때 해소된다' 같은 도입부에서 잘려 쓸모가 없다.
    """
    collapsed = " ".join(body.split())
    if not collapsed:
        return "(내용 없음)"
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def report_path(reports: Path, iteration: int) -> Path:
    return reports / f"{REPORT_PREFIX}{iteration:04d}.md"


def render_report(
    iteration: int,
    document: Document,
    backlog: Backlog,
    review: Review,
    metrics: Metrics,
    state_notes: list[str],
    verdict: Conclusion | None = None,
) -> str:
    lines: list[str] = []
    result_word = "통과" if review.ok else "위반"
    lines.append(f"# 반복 {iteration:04d}")
    lines.append("")
    lines.append(f"- 시각: {_timestamp()}")
    lines.append(f"- 결과: **{result_word}**")
    lines.append(f"- 증거 서명: `{review.signature[:16]}`")
    if verdict is not None and verdict.state != CONTINUE:
        lines.append(f"- 마침: **{verdict.state}** — {verdict.reason}")
    lines.append("")

    if verdict is not None and verdict.state != CONTINUE:
        lines.append(f"## 루프가 물러난다 — {verdict.state}")
        lines.append("")
        lines.append(verdict.reason)
        lines.append("")
        if verdict.guidance:
            lines.append(verdict.guidance)
            lines.append("")

    if state_notes:
        lines.append("## 상태 복구")
        lines.append("")
        for note in state_notes:
            lines.append(f"- {note}")
        lines.append("")

    lines.append("## 관측 지표")
    lines.append("")
    lines.append("점수가 아니다. 세는 것만 센다.")
    lines.append("")
    lines.append("| 항목 | 값 |")
    lines.append("| --- | --- |")
    lines.append(f"| 조건 수 | {metrics.conditions} |")
    lines.append(
        f"| 문서 분량(공백 제외) | {metrics.document_length}자{_delta(review, metrics)} |"
    )
    lines.append(f"| 예산 | {review.budget}자 |")
    lines.append(f"| 실질 분량(개정 제외) | {metrics.substance_length}자 |")
    lines.append(f"| 미해결 반론 | {metrics.open_objections} |")
    lines.append(f"| 누적 해소 반론 | {metrics.resolved_objections} |")
    lines.append(f"| 이번에 바뀐 조건 | {metrics.changed_conditions} |")
    lines.append(f"| 이번에 해소한 반론 | {metrics.resolved_now} |")
    lines.append(f"| 이번에 제기한 반론 | {metrics.raised_now} |")
    lines.append("")

    lines.append("## 이번 반복의 변화")
    lines.append("")
    cut = large_cut(review, metrics)
    if cut is not None:
        lines.append(f"> **이번 반복이 문서의 {cut:.0%}를 덜어냈다.**")
        lines.append(">")
        lines.append(
            "> 규칙은 이것을 막지 않는다. R13은 분량이 줄었다는 것까지만 알고, 무엇이"
            " 남고 무엇이 사라졌는지는 판정하지 못한다. 핵심 논증이 함께 사라졌는지는"
            " 사람이 `git diff`로 읽어야 한다. 정리는 갈아내는 일이지 지우는 일이 아니다."
        )
        lines.append("")
    lines.append(f"- 바뀐 조건: {', '.join(review.changed_conditions) or '없음'}")
    lines.append(f"- 해소한 반론: {', '.join(review.resolved_now) or '없음'}")
    lines.append(f"- 제기한 반론: {', '.join(review.raised_now) or '없음'}")
    if review.superseded_now:
        lines.append(f"- 은퇴시킨 반론: {', '.join(review.superseded_now)} (해소로 세지 않는다)")
    if review.resolve_first:
        lines.append("- 미해결 반론이 상한에 이르러 **해소 우선** 모드다. 새 반론 제기 의무가 면제된다.")
    if review.consolidating:
        lines.append(
            f"- 문서가 예산을 {review.overage}자 넘어 **정리 모드**다"
            f"({review.size}자 / {review.budget}자). 문서가 줄어야 R13을 통과한다."
        )
    lines.append("")

    lines.append("## 정직성 규칙")
    lines.append("")
    lines.append("| 규칙 | 내용 | 결과 | 근거 |")
    lines.append("| --- | --- | --- | --- |")
    for result in review.results:
        evidence = result.evidence.replace("|", "\\|")
        lines.append(f"| {result.identifier} | {result.title} | {result.symbol} | {evidence} |")
    lines.append("")

    lines.append("## 조건")
    lines.append("")
    lines.append("| 조건 | 제목 | 실질 분량 | 문서에서의 몫 | 개정 |")
    lines.append("| --- | --- | --- | --- | --- |")
    total = metrics.document_length or 1
    for condition in document.conditions:
        size = condition_size(condition)
        revision_size = textutil.visible_length(condition.field("개정"))
        revision = " ".join(condition.field("개정").split()).replace("|", "\\|")
        lines.append(
            f"| {condition.identifier} | {condition.title} | {size}자 | "
            f"{(size + revision_size) / total:.0%} | {revision} |"
        )
    lines.append("")
    lines.append(
        "예산은 문서 전체에 걸린다. 어디에 분량을 쓸지는 탐구의 몫이므로 조건마다 "
        "상한을 두지 않는다. 몫은 어느 조건이 문서를 차지하고 있는지 보여줄 뿐 "
        "그 자체로 위반이 아니다."
    )
    lines.append("")

    lines.append("## 미해결 반론")
    lines.append("")
    ordered = priority_order(backlog)
    if not ordered:
        lines.append("없음. R8 위반이다 — 비판이 멈췄다는 뜻이다.")
    else:
        lines.append("| 반론 | 대상 | 제기 | 제목 |")
        lines.append("| --- | --- | --- | --- |")
        for objection in ordered:
            title = objection.title.replace("|", "\\|")
            lines.append(
                f"| {objection.identifier} | {objection.target} | {objection.raised} | {title} |"
            )
    lines.append("")

    if review.violations:
        lines.append("## 고쳐야 할 것")
        lines.append("")
        for result in review.violations:
            lines.append(f"- **{result.identifier}** {result.title} — {result.evidence}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_index(history: list[dict]) -> str:
    lines = ["# 반복 기록", "", "최신순.", "", "| 반복 | 시각 | 결과 | 조건 | 미해결 반론 | 해소 | 제기 |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for entry in sorted(history, key=lambda e: e.get("iteration", 0), reverse=True):
        number = entry.get("iteration", 0)
        link = f"[{number:04d}]({REPORT_PREFIX}{number:04d}.md)"
        lines.append(
            "| {link} | {at} | {verdict} | {conditions} | {open} | {resolved} | {raised} |".format(
                link=link,
                at=entry.get("at", ""),
                verdict="통과" if entry.get("ok") else "위반",
                conditions=entry.get("conditions", 0),
                open=entry.get("open", 0),
                resolved=entry.get("resolved_now", 0),
                raised=entry.get("raised_now", 0),
            )
        )
    lines.append("")
    return "\n".join(lines)


def render_brief(
    iteration: int,
    document: Document,
    backlog: Backlog,
    review: Review,
    metrics: Metrics,
    verdict: Conclusion | None = None,
) -> str:
    ordered = priority_order(backlog)
    lines: list[str] = []
    lines.append("# 다음 세션 브리프")
    lines.append("")
    lines.append(f"반복 {iteration:04d}이 {_timestamp()}에 생성했다.")
    lines.append("")

    if verdict is not None and verdict.state != CONTINUE:
        lines.append(f"## 루프가 물러났다 — {verdict.state}")
        lines.append("")
        lines.append(verdict.reason)
        lines.append("")
        if verdict.guidance:
            lines.append(verdict.guidance)
            lines.append("")
        lines.append(
            "**세션을 새로 시작하지 마라.** 사람이 `SUMMARY.md`와 마지막 보고서를 "
            "읽고 판단할 차례다."
        )
        lines.append("")

    lines.append(f"- 직전 반복 결과: **{'통과' if review.ok else '위반'}**")
    lines.append(f"- 조건 {metrics.conditions}개, 미해결 반론 {metrics.open_objections}개")
    lines.append(
        f"- 문서 분량 {metrics.document_length}자 / 예산 {review.budget}자"
        f"{_delta(review, metrics)}"
    )
    lines.append(f"- 모드: {'해소 우선 — 새 반론을 제기하지 않아도 된다' if review.resolve_first else '보통 — 해소 하나, 제기 하나'}")
    if review.consolidating:
        lines.append(
            f"- **정리 모드** — 문서가 예산을 {review.overage}자 넘었다"
            f"({review.size}자 / {review.budget}자)"
        )
    cut = large_cut(review, metrics)
    if cut is not None:
        lines.append(
            f"- **직전 반복이 문서의 {cut:.0%}를 덜어냈다.** 이어서 더 줄이기 전에,"
            " 사라진 것 가운데 되살려야 할 논증이 있는지 `git diff`로 먼저 확인하라."
        )
    lines.append("")

    if review.consolidating:
        lines.append("## 먼저: 정리한다")
        lines.append("")
        lines.append(
            f"문서가 예산을 **{review.overage}자** 넘었다({review.size}자 / "
            f"{review.budget}자). 이번 반복은 문서가 **줄어들어야** R13을 통과한다. "
            "덧붙이는 방식으로는 통과할 수 없다."
        )
        lines.append("")
        largest = largest_sections(document)
        if largest:
            lines.append(f"큰 구획부터: {', '.join(largest)}.")
            lines.append("")
        lines.append(
            "어느 구획을 줄일지는 정해져 있지 않다. 예산은 문서 전체에 걸리므로 "
            "한 조건이 어려워 길어지는 것은 정당할 수 있고, 그 대가로 다른 조건을 "
            "줄이는 것도 정당하다."
        )
        lines.append("")
        lines.append("정리는 삭제가 아니다. 다음 순서로 한다.")
        lines.append("")
        lines.append("1. 같은 말을 다르게 반복한 문단을 하나로 합친다.")
        lines.append("2. 예시가 여러 개면 가장 강한 것 하나만 남긴다.")
        lines.append("3. 이미 해소된 반론에 답하느라 늘어난 방어 문장을, 그 답이")
        lines.append("   주장에 흡수되었으면 지운다. 답은 남고 변명은 지운다.")
        lines.append("4. 조건을 통째로 지워 분량을 맞추지 마라. R14가 잡는다.")
        lines.append("5. R2의 최소 분량 아래로 깎지 마라. R2가 잡는다.")
        lines.append("")
        lines.append(
            "정리로 대상 조건의 실질이 바뀌면 그것으로 R5도 만족된다. 줄이면서 "
            "반론을 해소할 수 있다."
        )
        lines.append("")

    if review.violations:
        lines.append("## 먼저 고칠 것")
        lines.append("")
        lines.append("직전 반복이 정직성 규칙을 어겼다. 새 작업을 시작하기 전에 이것부터 해결한다.")
        lines.append("")
        for result in review.violations:
            lines.append(f"- **{result.identifier}** {result.title} — {result.evidence}")
        lines.append("")

    lines.append("## 이번에 할 일")
    lines.append("")
    if not ordered:
        lines.append("미해결 반론이 없다. 이것은 완성이 아니라 비판이 멈춘 상태이며 R8 위반이다.")
        lines.append("`Hanik.md`를 다시 읽고, 가장 약한 논증을 겨냥한 반론을 새로 제기하라.")
        lines.append("")
    else:
        head = ordered[0]
        lines.append(f"1. **{head.identifier}을 해소한다.** (대상 {head.target})")
        lines.append("")
        lines.append(f"   > {head.title}")
        lines.append("")
        lines.append(f"   해소 조건: {_excerpt(head.criteria)}")
        lines.append("")
        lines.append(f"   전문은 `objections/{head.identifier}.md`에 있다. 대상 조건의 **주장·근거·한계**를")
        lines.append("   실제로 고쳐 쓴 뒤에야 상태를 `resolved`로 바꿀 수 있다. '개정' 줄만 고치면 R5가 잡는다.")
        lines.append("")
        if not review.resolve_first:
            lines.append("2. **새 반론을 하나 이상 제기한다.** 방금 고쳐 쓴 논증을 다시 읽고, 그것이 새로")
            lines.append("   끌어들인 전제나 아직 답하지 못한 물음을 겨냥하라. 반론이 없으면 루프가 멈춘다.")
            lines.append("")
        else:
            lines.append("2. 새 반론 제기는 면제된다. 쌓인 반론을 줄이는 데 집중하라.")
            lines.append("")
        lines.append("3. `python3 -m pytest tests/ -v` 후 `python3 -m src.hanik_loop`을 마지막에 실행한다.")
        lines.append("")

    if len(ordered) > 1:
        lines.append("## 남은 미해결 반론")
        lines.append("")
        for objection in ordered[1:]:
            lines.append(f"- `{objection.identifier}` ({objection.target}, {objection.raised}) — {objection.title}")
        lines.append("")

    lines.append("## 규칙")
    lines.append("")
    lines.append("- **반론은 제기된 뒤 고칠 수 없다.** 제목·대상·본문을 무르게 고치는 것을 R6이 해시로 잡는다.")
    lines.append("  생각이 달라졌다면 기존 반론을 그대로 두고 새 반론을 제기하라.")
    lines.append("- **반론 파일을 지우거나 번호를 바꿀 수 없다.** R12가 잡는다. 겨냥할 구조가 사라졌다면")
    lines.append("  `superseded`로 은퇴시키고 비판을 넘겨받을 반론을 `해소`에 적어라. 은퇴는 해소로 세지 않는다.")
    lines.append("- **규칙을 고쳐 통과시키지 마라.** `src/integrity.py`를 무르게 만드는 것은 루프가 잡지 못한다.")
    lines.append("  사람 리뷰만이 막을 수 있고, 그래서 이것이 여기 적혀 있다.")
    lines.append("- **예산을 늘려 정리를 피하지 마라.** `HANIK_DOCUMENT_BUDGET`을 올리는 것은")
    lines.append("  R13을 무르게 만드는 것과 같다. 읽을 수 없는 문서는 쓰이지 않은 문서다.")
    lines.append("- `SUMMARY.md`와 `state/sessions.md`는 생성물이다. 손으로 고치지 마라.")
    lines.append("- 전체 계약은 `AGENTS.md`에 있다.")
    lines.append("")
    return "\n".join(lines)
