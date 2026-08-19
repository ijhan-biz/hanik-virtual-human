"""결산 — 결과물에서 중요한 부분만 뽑아낸다.

`Hanik.md`는 반복이 쌓일수록 커진다. 루프의 규칙은 전부 한 방향으로만 민다:
R3은 문서가 바뀌기를 요구하고, R5는 대상 조건이 바뀌기를 요구하며, R2는 최소
분량만 정하고 상한을 두지 않는다. 가장 싼 만족 방법은 덧붙이기다. 그래서 문서는
읽을 수 없을 때까지 자란다.

결산은 그 반대편이다. 문서를 줄이지는 않되, **읽을 사람이 실제로 필요한 것**만
추려 `SUMMARY.md`에 남긴다.

무엇이 중요한 부분인가:

- **주장** — 각 조건에 대한 Hanik의 현재 입장. 문서가 내놓는 답 그 자체다.
- **한계** — 그 입장이 아직 해결하지 못한 것. 다음 작업이 있는 자리다.
- **비판의 계보** — 어떤 반론이 어떤 조건을 고치게 만들었는가. 루프가 실제로
  생산한 것은 문장이 아니라 이 계보다.
- **남은 물음** — 미해결 반론.

**근거**는 뽑지 않고 발췌만 한다. 분량이 불어나는 자리가 대부분 거기이고,
결산까지 그것을 그대로 옮기면 결산도 같은 운명을 맞는다.

이 파일은 **생성물이다.** 손으로 고치지 마라. 매 반복 덮어쓰인다. 손으로 쓸 수
있게 두면 분량을 밀어 넣을 자리가 하나 더 생길 뿐이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from . import text as textutil
from .document import Document, condition_size
from .integrity import condition_budget, preamble_budget
from .objections import Backlog, Objection

SETTLEMENT_NAME = "SUMMARY.md"

#: 결산에 실리는 발췌의 상한. 결산이 결산인 이유는 짧기 때문이다. 이 상한이
#: 없으면 `Hanik.md`가 자란 만큼 결산도 자라고, 읽을 수 있는 요약은 사라진다.
CLAIM_LIMIT = 1500
LIMITS_LIMIT = 1000
EVIDENCE_LIMIT = 700
PREAMBLE_LIMIT = 900

_OBJECTION_REFERENCE = re.compile(r"O-\d{4}")


def _excerpt(body: str, limit: int) -> tuple[str, bool]:
    """(발췌, 잘렸는가).

    잘렸는지를 함께 돌려주는 이유는, 잘림 자체가 읽을 사람에게 필요한 정보이기
    때문이다. 주장이 상한을 넘었다는 것은 그것이 더는 주장이 아니라는 뜻이다.
    """
    collapsed = " ".join(body.split())
    if not collapsed:
        return "(내용 없음)", False
    if len(collapsed) <= limit:
        return collapsed, False
    return collapsed[: limit - 1] + "…", True


@dataclass(frozen=True)
class ConditionSummary:
    """조건 하나에서 추린 중요한 부분."""

    identifier: str
    title: str
    claim: str
    claim_truncated: bool
    claim_size: int
    limits: str
    limits_truncated: bool
    evidence_excerpt: str
    size: int
    budget: int
    shaped_by: tuple[str, ...]
    open_questions: tuple[str, ...]

    @property
    def over_budget(self) -> bool:
        return self.size > self.budget


@dataclass(frozen=True)
class Settlement:
    """결산 한 장."""

    iteration: int
    generated_at: str
    conditions: tuple[ConditionSummary, ...]
    preamble_excerpt: str
    preamble_size: int
    preamble_budget: int
    open_objections: tuple[Objection, ...]
    resolved_count: int
    superseded_count: int
    iterations_run: int
    passed_run: int

    @property
    def total_size(self) -> int:
        return self.preamble_size + sum(c.size for c in self.conditions)

    @property
    def over_budget(self) -> tuple[str, ...]:
        names = []
        if self.preamble_size > self.preamble_budget:
            names.append("서문")
        names += [c.identifier for c in self.conditions if c.over_budget]
        return tuple(names)


def _shaping_objections(
    identifier: str, revision: str, backlog: Backlog
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """이 조건을 고치게 만든 반론과, 아직 이 조건에 답을 요구하는 반론.

    계보는 두 곳에서 모은다. 반론이 스스로 밝힌 `대상`과, 조건의 `개정` 줄이
    지목한 반론 번호다. 둘 중 하나만 보면 대상을 옮긴 반론이나 개정 줄에만 적힌
    반론을 놓친다.
    """
    shaped: list[str] = []
    pending: list[str] = []
    for objection in backlog.items:
        if objection.target != identifier:
            continue
        if objection.is_open:
            pending.append(objection.identifier)
        else:
            shaped.append(objection.identifier)

    for reference in _OBJECTION_REFERENCE.findall(revision):
        if reference not in shaped and reference not in pending:
            shaped.append(reference)

    return tuple(sorted(set(shaped))), tuple(sorted(set(pending)))


def settle(
    document: Document,
    backlog: Backlog,
    iteration: int,
    ledger: list[dict[str, Any]] | None = None,
    condition_budget_override: int = 0,
    preamble_budget_override: int = 0,
) -> Settlement:
    """현재 저장소에서 결산을 만든다. 판단하지 않고 추리기만 한다."""
    c_budget = condition_budget_override or condition_budget()
    p_budget = preamble_budget_override or preamble_budget()
    entries = ledger or []

    summaries = []
    for condition in document.conditions:
        shaped, pending = _shaping_objections(
            condition.identifier, condition.field("개정"), backlog
        )
        claim, claim_cut = _excerpt(condition.field("주장"), CLAIM_LIMIT)
        limits, limits_cut = _excerpt(condition.field("한계"), LIMITS_LIMIT)
        evidence, _ = _excerpt(condition.field("근거"), EVIDENCE_LIMIT)
        summaries.append(
            ConditionSummary(
                identifier=condition.identifier,
                title=condition.title,
                claim=claim,
                claim_truncated=claim_cut,
                claim_size=textutil.visible_length(condition.field("주장")),
                limits=limits,
                limits_truncated=limits_cut,
                evidence_excerpt=evidence,
                size=condition_size(condition),
                budget=c_budget,
                shaped_by=shaped,
                open_questions=pending,
            )
        )

    preamble_excerpt, _ = _excerpt(document.preamble, PREAMBLE_LIMIT)
    return Settlement(
        iteration=iteration,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        conditions=tuple(summaries),
        preamble_excerpt=preamble_excerpt,
        preamble_size=textutil.visible_length(document.preamble),
        preamble_budget=p_budget,
        open_objections=tuple(
            sorted(backlog.open_items, key=lambda o: o.identifier)
        ),
        resolved_count=len(backlog.resolved_items),
        superseded_count=len([o for o in backlog.items if o.is_superseded]),
        iterations_run=len(entries),
        passed_run=len([entry for entry in entries if entry.get("ok")]),
    )


def render_settlement(settlement: Settlement) -> str:
    """`SUMMARY.md` 본문."""
    lines: list[str] = []
    lines.append("# Hanik — 결산")
    lines.append("")
    lines.append(
        "이 파일은 **생성물이다.** `python3 -m src.hanik_loop`이 매 반복 덮어쓴다. "
        "손으로 고치지 마라."
    )
    lines.append("")
    lines.append(
        f"반복 {settlement.iteration:04d} 기준 · {settlement.generated_at}"
    )
    lines.append("")
    lines.append(
        "`Hanik.md`는 탐구의 전문이고 이 문서는 그 결론만이다. 여기 없는 것이 "
        "중요하지 않다는 뜻은 아니지만, 여기 있는 것만으로 Hanik이 지금 무엇을 "
        "주장하는지는 읽을 수 있어야 한다."
    )
    lines.append("")

    lines.append("## 지금 Hanik의 입장")
    lines.append("")
    if not settlement.conditions:
        lines.append("조건이 없다. 문서가 비었거나 파싱되지 않는다.")
        lines.append("")
    for summary in settlement.conditions:
        lines.append(f"### {summary.identifier} · {summary.title}")
        lines.append("")
        lines.append(f"**주장.** {summary.claim}")
        if summary.claim_truncated:
            lines.append("")
            lines.append(
                f"> 이 주장은 {summary.claim_size}자다. 결산은 {CLAIM_LIMIT}자까지만 싣는다. "
                "한 조건에 대한 입장이 요약될 수 없다면 그것은 아직 입장이 아니라 "
                "메모다. 전문은 `Hanik.md`에 있다."
            )
        lines.append("")
        lines.append(f"**아직 못 한 것.** {summary.limits}")
        lines.append("")
        if summary.shaped_by:
            lines.append(
                f"이 입장은 반론 {', '.join(summary.shaped_by)}에 답하며 지금 모습이 되었다."
            )
        else:
            lines.append("아직 이 조건을 고치게 만든 반론이 없다.")
        if summary.open_questions:
            lines.append("")
            lines.append(
                f"열린 물음: {', '.join(summary.open_questions)} — 아직 답하지 못했다."
            )
        lines.append("")

    lines.append("## 아직 답하지 못한 물음")
    lines.append("")
    if not settlement.open_objections:
        lines.append(
            "미해결 반론이 없다. 문서가 완성된 것이 아니라 비판이 멈춘 것이다(R8 위반)."
        )
    else:
        lines.append("| 반론 | 대상 | 제기 | 물음 |")
        lines.append("| --- | --- | --- | --- |")
        for objection in settlement.open_objections:
            title = objection.title.replace("|", "\\|")
            lines.append(
                f"| `{objection.identifier}` | {objection.target} | {objection.raised} | {title} |"
            )
    lines.append("")

    lines.append("## 분량 회계")
    lines.append("")
    lines.append(
        "읽히지 않는 문서는 쓰이지 않은 문서와 같다. 예산은 품질 기준이 아니라 "
        "읽을 수 있는 크기의 상한이다."
    )
    lines.append("")
    lines.append("| 구획 | 실질 분량 | 예산 | 상태 |")
    lines.append("| --- | --- | --- | --- |")
    preamble_state = (
        "초과" if settlement.preamble_size > settlement.preamble_budget else "이내"
    )
    lines.append(
        f"| 서문 | {settlement.preamble_size}자 | {settlement.preamble_budget}자 | {preamble_state} |"
    )
    for summary in settlement.conditions:
        state = "초과" if summary.over_budget else "이내"
        lines.append(
            f"| {summary.identifier} | {summary.size}자 | {summary.budget}자 | {state} |"
        )
    lines.append(f"| **합계** | **{settlement.total_size}자** | — | — |")
    lines.append("")
    if settlement.over_budget:
        lines.append(
            f"**예산을 넘긴 구획: {', '.join(settlement.over_budget)}.** 다음 반복은 "
            "정리 모드다. 새 문장을 더하기 전에 이 구획을 줄여야 R13을 통과한다."
        )
        lines.append("")

    lines.append("## 루프의 기록")
    lines.append("")
    lines.append("| 항목 | 값 |")
    lines.append("| --- | --- |")
    lines.append(f"| 기록된 반복 | {settlement.iterations_run} |")
    lines.append(f"| 그중 통과 | {settlement.passed_run} |")
    lines.append(f"| 조건 | {len(settlement.conditions)} |")
    lines.append(f"| 미해결 반론 | {len(settlement.open_objections)} |")
    lines.append(f"| 해소된 반론 | {settlement.resolved_count} |")
    lines.append(f"| 은퇴한 반론 | {settlement.superseded_count} |")
    lines.append("")

    lines.append("## 서문 발췌")
    lines.append("")
    lines.append(f"> {settlement.preamble_excerpt}")
    lines.append("")

    lines.append("## 근거 발췌")
    lines.append("")
    lines.append(
        "각 조건의 **근거**는 전문이 `Hanik.md`에 있다. 여기서는 첫머리만 보인다."
    )
    lines.append("")
    for summary in settlement.conditions:
        lines.append(f"- **{summary.identifier}** — {summary.evidence_excerpt}")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_sessions(ledger: list[dict[str, Any]], limit: int = 40) -> str:
    """세션들이 남긴 것을 최근 것부터 훑는 기록.

    러너의 원시 로그는 반복마다 수천 줄씩 쌓인다. 그중 남을 가치가 있는 것은
    무엇이 해소되고 무엇이 새로 제기되었는가뿐이다.

    이 파일도 무한히 자라게 두지 않는다. 분량 예산을 두면서 루프 자신의 기록만
    끝없이 늘리는 것은 앞뒤가 맞지 않는다. 전체는 `state/ledger.json`에 남는다.
    """
    lines: list[str] = []
    lines.append("# 세션 기록")
    lines.append("")
    lines.append(
        "이 파일은 **생성물이다.** 매 반복 덮어쓰인다. 최근 "
        f"{limit}개만 보이며, 잘린 것은 `state/ledger.json`에 그대로 있다."
    )
    lines.append("")

    recent = sorted(ledger, key=lambda e: e.get("iteration", 0), reverse=True)[:limit]
    if not recent:
        lines.append("아직 기록된 반복이 없다.")
        lines.append("")
        return "\n".join(lines)

    for entry in recent:
        iteration = entry.get("iteration", 0)
        violations = entry.get("violations") or []
        verdict = "통과" if entry.get("ok") else f"위반({', '.join(violations) or '이유 미상'})"
        lines.append(f"## 반복 {iteration:04d} — {verdict}")
        lines.append("")
        lines.append(f"- 시각: {entry.get('at', '기록 없음')}")
        lines.append(f"- 해소: {_ids(entry, 'resolved_ids', 'resolved_now')}")
        lines.append(f"- 제기: {_ids(entry, 'raised_ids', 'raised_now')}")
        superseded = entry.get("superseded_ids")
        if superseded:
            lines.append(f"- 은퇴: {', '.join(superseded)}")
        lines.append(f"- 바뀐 조건: {_ids(entry, 'changed_ids', 'changed_now')}")
        size = entry.get("size")
        if isinstance(size, int):
            over = entry.get("over_budget") or []
            suffix = f" (예산 초과: {', '.join(over)})" if over else ""
            lines.append(f"- 실질 분량: {size}자{suffix}")
        lines.append(f"- 미해결 반론: {entry.get('open', 0)}개")
        lines.append("")

    return "\n".join(lines)


def _ids(entry: dict[str, Any], id_key: str, count_key: str) -> str:
    """원장에 번호가 있으면 번호를, 옛 항목이면 개수를 보인다."""
    values = entry.get(id_key)
    if isinstance(values, list) and values:
        return ", ".join(str(value) for value in values)
    if isinstance(values, list):
        return "없음"
    count = entry.get(count_key)
    if isinstance(count, int):
        return f"{count}개 (번호 기록 이전)"
    return "기록 없음"
