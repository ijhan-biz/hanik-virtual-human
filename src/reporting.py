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
from .document import REQUIRED_FIELDS, Document
from .integrity import Review
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
    open_objections: int
    resolved_objections: int
    changed_conditions: int
    resolved_now: int
    raised_now: int


def measure(document: Document, backlog: Backlog, review: Review) -> Metrics:
    length = textutil.visible_length(document.preamble) + sum(
        textutil.visible_length(condition.field(name))
        for condition in document.conditions
        for name in REQUIRED_FIELDS
    )
    return Metrics(
        conditions=len(document.conditions),
        document_length=length,
        open_objections=len(backlog.open_items),
        resolved_objections=len(backlog.resolved_items),
        changed_conditions=len(review.changed_conditions),
        resolved_now=len(review.resolved_now),
        raised_now=len(review.raised_now),
    )


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
) -> str:
    lines: list[str] = []
    verdict = "통과" if review.ok else "위반"
    lines.append(f"# 반복 {iteration:04d}")
    lines.append("")
    lines.append(f"- 시각: {_timestamp()}")
    lines.append(f"- 결과: **{verdict}**")
    lines.append(f"- 증거 서명: `{review.signature[:16]}`")
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
    lines.append(f"| 문서 분량(공백 제외) | {metrics.document_length}자 |")
    lines.append(f"| 미해결 반론 | {metrics.open_objections} |")
    lines.append(f"| 누적 해소 반론 | {metrics.resolved_objections} |")
    lines.append(f"| 이번에 바뀐 조건 | {metrics.changed_conditions} |")
    lines.append(f"| 이번에 해소한 반론 | {metrics.resolved_now} |")
    lines.append(f"| 이번에 제기한 반론 | {metrics.raised_now} |")
    lines.append("")

    lines.append("## 이번 반복의 변화")
    lines.append("")
    lines.append(f"- 바뀐 조건: {', '.join(review.changed_conditions) or '없음'}")
    lines.append(f"- 해소한 반론: {', '.join(review.resolved_now) or '없음'}")
    lines.append(f"- 제기한 반론: {', '.join(review.raised_now) or '없음'}")
    if review.superseded_now:
        lines.append(f"- 은퇴시킨 반론: {', '.join(review.superseded_now)} (해소로 세지 않는다)")
    if review.resolve_first:
        lines.append("- 미해결 반론이 상한에 이르러 **해소 우선** 모드다. 새 반론 제기 의무가 면제된다.")
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
    lines.append("| 조건 | 제목 | 분량 | 개정 |")
    lines.append("| --- | --- | --- | --- |")
    for condition in document.conditions:
        size = sum(textutil.visible_length(condition.field(name)) for name in REQUIRED_FIELDS)
        revision = " ".join(condition.field("개정").split()).replace("|", "\\|")
        lines.append(f"| {condition.identifier} | {condition.title} | {size}자 | {revision} |")
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
) -> str:
    ordered = priority_order(backlog)
    lines: list[str] = []
    lines.append("# 다음 세션 브리프")
    lines.append("")
    lines.append(f"반복 {iteration:04d}이 {_timestamp()}에 생성했다.")
    lines.append("")
    lines.append(f"- 직전 반복 결과: **{'통과' if review.ok else '위반'}**")
    lines.append(f"- 조건 {metrics.conditions}개, 미해결 반론 {metrics.open_objections}개")
    lines.append(f"- 모드: {'해소 우선 — 새 반론을 제기하지 않아도 된다' if review.resolve_first else '보통 — 해소 하나, 제기 하나'}")
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
    lines.append("- 전체 계약은 `AGENTS.md`에 있다.")
    lines.append("")
    return "\n".join(lines)
