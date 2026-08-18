"""정직성 규칙.

이 모듈은 `Hanik.md`가 좋은 문서인지 판단하지 않는다. 그것은 사람과 세션의 몫이다.
여기서 강제하는 것은 오직 정직성이다.

- 무언가 실제로 바뀌었는가 (R3, R11)
- 해소했다고 선언한 반론의 대상이 진짜로 고쳐졌는가 (R4, R5)
- 반론을 무르게 고쳐서 해소한 것은 아닌가 (R6)
- 비판이 멈추지 않았는가 (R7, R8)
- 형식과 분량이 최소한을 넘는가 (R1, R2, R9, R10)

이전 저장소는 "검사를 약화시키지 말라"를 탐지 불가능한 규범으로 남겨두었다.
R6은 그 자리에 기계적으로 탐지 가능한 장치를 놓는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import text as textutil
from .document import REQUIRED_FIELDS, Document
from .objections import Backlog, Objection
from .state import State

#: 조건 필드가 스텁이 아니기 위한 최소 글자 수(공백 제외).
MIN_FIELD_LENGTH = {"주장": 80, "근거": 300, "한계": 100, "개정": 8}

#: 반론이 형식만 채운 것이 아니기 위한 최소 글자 수.
MIN_ARGUMENT_LENGTH = 250
MIN_CRITERIA_LENGTH = 120

#: 조건 두 개가 공유해도 되는 문장 비율의 상한. 분량 물타기를 막는다.
MAX_DUPLICATION = 0.15

#: 미해결 반론이 이만큼 쌓이면 새 반론 제기 의무(R7)를 면제하고 해소를 우선한다.
DEFAULT_OPEN_LIMIT = 12


def open_limit(environ: dict[str, str] | None = None) -> int:
    source = os.environ if environ is None else environ
    try:
        value = int(source.get("HANIK_OPEN_LIMIT", DEFAULT_OPEN_LIMIT))
    except (TypeError, ValueError):
        return DEFAULT_OPEN_LIMIT
    return value if value > 0 else DEFAULT_OPEN_LIMIT


@dataclass(frozen=True)
class RuleResult:
    """규칙 하나의 결과."""

    identifier: str
    title: str
    passed: bool
    evidence: str
    exempt: bool = False

    @property
    def symbol(self) -> str:
        if self.exempt:
            return "면제"
        return "통과" if self.passed else "위반"


@dataclass(frozen=True)
class Review:
    """한 반복의 정직성 검토 결과."""

    results: tuple[RuleResult, ...]
    signature: str
    resolved_now: tuple[str, ...]
    raised_now: tuple[str, ...]
    superseded_now: tuple[str, ...]
    changed_conditions: tuple[str, ...]
    resolve_first: bool

    @property
    def ok(self) -> bool:
        return all(result.passed or result.exempt for result in self.results)

    @property
    def violations(self) -> tuple[RuleResult, ...]:
        return tuple(r for r in self.results if not r.passed and not r.exempt)


def evidence_signature(document: Document, backlog: Backlog) -> str:
    """조건의 실질과 반론의 상태만을 담은 서명.

    서술을 다듬는 것만으로는 바뀌지 않도록 조건은 실질 해시만 쓰고,
    반론은 식별자와 상태, 본문 해시를 쓴다.
    """
    parts = [f"{c.identifier}:{c.substance_digest}" for c in sorted(document.conditions, key=lambda c: c.identifier)]
    parts += [
        f"{o.identifier}:{o.status}:{o.digest}" for o in sorted(backlog.items, key=lambda o: o.identifier)
    ]
    return textutil.digest(*parts)


def _changed_conditions(document: Document, previous: State) -> tuple[str, ...]:
    changed = []
    for condition in document.conditions:
        before = previous.conditions.get(condition.identifier, {})
        if before.get("substance_digest") != condition.substance_digest:
            changed.append(condition.identifier)
    return tuple(changed)


def _transitions(backlog: Backlog, previous: State) -> dict[str, tuple[str, ...]]:
    """반론의 상태 전이를 분류한다.

    허용되는 전이는 open → resolved 와 open → superseded 뿐이다. resolved나
    superseded가 다시 open이 되는 것을 막지 않으면, 같은 반론을 반복해서 해소하며
    R4를 만족시킬 수 있다.
    """
    resolved_now: list[str] = []
    superseded_now: list[str] = []
    raised_now: list[str] = []
    illegitimate: list[str] = []
    illegal: list[str] = []

    for objection in backlog.items:
        before = previous.objections.get(objection.identifier)
        if before is None:
            raised_now.append(objection.identifier)
            if not objection.is_open:
                illegitimate.append(objection.identifier)
            continue
        was = before.get("status")
        if was == objection.status:
            continue
        if was == "open" and objection.is_resolved:
            resolved_now.append(objection.identifier)
        elif was == "open" and objection.is_superseded:
            superseded_now.append(objection.identifier)
        else:
            illegal.append(f"{objection.identifier}: {was} → {objection.status}")

    missing = tuple(
        identifier for identifier in sorted(previous.objections) if backlog.by_id(identifier) is None
    )
    return {
        "resolved": tuple(resolved_now),
        "superseded": tuple(superseded_now),
        "raised": tuple(raised_now),
        "illegitimate": tuple(illegitimate),
        "illegal": tuple(illegal),
        "missing": missing,
    }


def _target_moved(objection: Objection, document: Document, previous: State) -> tuple[bool, str]:
    """해소된 반론의 대상이 실제로 바뀌었는지 확인한다."""
    if objection.targets_document:
        changed = _changed_conditions(document, previous)
        preamble_moved = previous.document.get("preamble_digest") != document.preamble_digest
        if preamble_moved or len(changed) >= 2:
            parts = ["서문"] if preamble_moved else []
            parts += list(changed)
            return True, f"{objection.identifier}: 문서의 틀이 바뀌었다({', '.join(parts)})."
        return False, (
            f"{objection.identifier}: 대상이 문서 전체인데 서문이 그대로이고 바뀐 조건이 "
            f"{len(changed)}개뿐이다. 조건 하나를 손본 김에 딸려 해소될 수는 없다."
        )

    condition = document.by_id(objection.target)
    if condition is None:
        return False, f"{objection.identifier}: 대상 {objection.target}이 문서에 없다."
    before = previous.conditions.get(objection.target, {})
    if before.get("substance_digest") == condition.substance_digest:
        return False, (
            f"{objection.identifier}: {objection.target}의 주장·근거·한계가 그대로다. "
            "'개정' 줄만 고치는 것은 해소가 아니다."
        )
    return True, f"{objection.identifier}: {objection.target}의 내용이 바뀌었다."


def _duplication(document: Document) -> tuple[float, str]:
    """조건 쌍 사이의 문장 중복률 중 최댓값."""
    corpus = {c.identifier: set(textutil.sentences(" ".join(c.field(f) for f in REQUIRED_FIELDS))) for c in document.conditions}
    worst = 0.0
    detail = "겹치는 문장이 없다."
    identifiers = sorted(corpus)
    for index, left in enumerate(identifiers):
        for right in identifiers[index + 1 :]:
            a, b = corpus[left], corpus[right]
            if not a or not b:
                continue
            shared = a & b
            ratio = len(shared) / min(len(a), len(b))
            if ratio > worst:
                worst = ratio
                detail = f"{left}와 {right}가 문장 {len(shared)}개를 공유한다(비율 {ratio:.2f})."
    return worst, detail


def review(
    document: Document,
    backlog: Backlog,
    previous: State,
    limit: int | None = None,
) -> Review:
    """정직성 규칙 R1–R11을 실행한다."""
    bound = open_limit() if limit is None else limit
    first_run = previous.is_first_run
    results: list[RuleResult] = []

    changed = _changed_conditions(document, previous)
    moves = _transitions(backlog, previous)
    resolved_now, raised_now = moves["resolved"], moves["raised"]
    open_items = backlog.open_items
    resolve_first = len(open_items) >= bound

    def add(identifier: str, title: str, passed: bool, evidence: str, exempt: bool = False) -> None:
        results.append(RuleResult(identifier, title, passed, evidence, exempt and first_run))

    # R1
    add(
        "R1",
        "Hanik.md가 규격대로 파싱된다",
        document.exists and not document.problems,
        "구조 문제 없음." if not document.problems else " / ".join(document.problems[:5]),
    )

    # R2
    shortfalls = []
    for condition in document.conditions:
        for name in REQUIRED_FIELDS:
            length = textutil.visible_length(condition.field(name))
            minimum = MIN_FIELD_LENGTH[name]
            if length < minimum:
                shortfalls.append(f"{condition.identifier}.{name} {length}자 < {minimum}자")
    add(
        "R2",
        "모든 조건이 필드를 갖추고 스텁이 아니다",
        not shortfalls,
        f"조건 {len(document.conditions)}개가 분량 기준을 넘는다." if not shortfalls else " / ".join(shortfalls),
    )

    # R3
    document_moved = previous.document.get("digest") != document.digest
    add(
        "R3",
        "직전 반복 대비 Hanik.md가 바뀌었다",
        document_moved,
        "문서가 바뀌었다." if document_moved else "문서가 직전 반복과 완전히 같다.",
        exempt=True,
    )

    # R4
    r4_ok = bool(resolved_now) and not moves["illegitimate"]
    if moves["illegitimate"]:
        r4_evidence = (
            f"제기와 동시에 닫힌 반론이 있다: {', '.join(moves['illegitimate'])}. "
            "반론은 최소 한 반복 동안 열려 있어야 한다."
        )
    elif resolved_now:
        r4_evidence = f"이번 반복에 해소된 반론: {', '.join(resolved_now)}."
    else:
        r4_evidence = "open에서 resolved로 바뀐 반론이 없다."
    if moves["superseded"]:
        r4_evidence += f" (은퇴 처리는 해소로 세지 않는다: {', '.join(moves['superseded'])})"
    add("R4", "반론을 하나 이상 해소했다", r4_ok, r4_evidence, exempt=True)

    # R5
    r5_details: list[str] = []
    r5_ok = True
    for identifier in resolved_now:
        objection = backlog.by_id(identifier)
        if objection is None:
            continue
        moved, detail = _target_moved(objection, document, previous)
        r5_ok = r5_ok and moved
        r5_details.append(detail)
    add(
        "R5",
        "해소된 반론의 대상이 실제로 바뀌었다",
        r5_ok,
        " / ".join(r5_details) if r5_details else "해소된 반론이 없어 확인할 대상이 없다.",
        exempt=True,
    )

    # R6
    altered: list[str] = []
    for objection in backlog.items:
        before = previous.objections.get(objection.identifier)
        if before is None:
            continue
        if before.get("digest") != objection.digest:
            altered.append(objection.identifier)
    add(
        "R6",
        "이미 제기된 반론의 제목·대상·본문이 수정되지 않았다",
        not altered,
        "모든 반론이 제기된 그대로다."
        if not altered
        else (
            f"내용이 바뀐 반론: {', '.join(altered)}. 반론은 제기된 뒤 고칠 수 없고, "
            "대상을 다른 조건으로 옮길 수도 없다. 생각이 달라졌다면 새 반론을 제기하라."
        ),
        exempt=True,
    )

    # R7
    if resolve_first:
        r7_ok, r7_evidence = True, f"미해결 반론이 {len(open_items)}개로 상한({bound}) 이상이라 제기 의무를 면제한다."
    elif raised_now:
        r7_ok, r7_evidence = True, f"새로 제기된 반론: {', '.join(raised_now)}."
    else:
        r7_ok, r7_evidence = False, "새로 제기된 반론이 없다. 비판이 멈추면 루프도 멈춘다."
    add("R7", "새 반론을 하나 이상 제기했다", r7_ok, r7_evidence, exempt=True)

    # R8
    add(
        "R8",
        "미해결 반론이 하나 이상 남아 있다",
        bool(open_items),
        f"미해결 반론 {len(open_items)}개."
        if open_items
        else "미해결 반론이 없다. 문서가 완성된 것이 아니라 비판이 멈춘 것이다.",
    )

    # R9
    backlog_problems = list(backlog.problems)
    for objection in backlog.items:
        # 대상 존재는 살아 있는 반론에만 요구한다. 닫힌 반론까지 묶어두면 조건을
        # 합치거나 은퇴시키는 일이 영영 불가능해진다.
        if objection.is_open and not objection.targets_document and document.by_id(objection.target) is None:
            backlog_problems.append(f"{objection.identifier}: 대상 {objection.target}이 문서에 없다.")
        if objection.is_superseded:
            replacement = objection.replacement
            if replacement and backlog.by_id(replacement) is None:
                backlog_problems.append(
                    f"{objection.identifier}: 비판을 넘겨받았다는 {replacement}이 없다."
                )
        if textutil.visible_length(objection.argument) < MIN_ARGUMENT_LENGTH:
            backlog_problems.append(
                f"{objection.identifier}: 반론 본문이 {textutil.visible_length(objection.argument)}자로 짧다."
            )
        if textutil.visible_length(objection.criteria) < MIN_CRITERIA_LENGTH:
            backlog_problems.append(
                f"{objection.identifier}: 해소 조건이 {textutil.visible_length(objection.criteria)}자로 짧다."
            )
    add(
        "R9",
        "반론이 규격에 맞고 대상이 실재한다",
        not backlog_problems,
        f"반론 {len(backlog.items)}개가 규격에 맞는다."
        if not backlog_problems
        else " / ".join(backlog_problems[:5]),
    )

    # R10
    ratio, duplication_detail = _duplication(document)
    add(
        "R10",
        "조건 사이의 문장 중복이 상한 이하다",
        ratio <= MAX_DUPLICATION,
        f"{duplication_detail} 상한 {MAX_DUPLICATION:.2f}.",
    )

    # R11
    signature = evidence_signature(document, backlog)
    signature_moved = signature != previous.signature
    add(
        "R11",
        "증거 서명이 직전 반복과 다르다",
        signature_moved,
        "서명이 바뀌었다." if signature_moved else "조건의 실질도 반론의 상태도 그대로다. 다시 돌려도 달라지지 않는다.",
    )

    # R12
    r12_problems: list[str] = []
    if moves["missing"]:
        r12_problems.append(
            f"사라진 반론: {', '.join(moves['missing'])}. 반론 파일은 지우거나 번호를 바꿀 수 없다. "
            "구조가 바뀌어 더는 겨냥할 대상이 없다면 superseded로 은퇴시키고 비판을 넘겨받을 반론을 적어라."
        )
    if moves["illegal"]:
        r12_problems.append(f"허용되지 않는 상태 전이: {', '.join(moves['illegal'])}.")
    add(
        "R12",
        "반론이 사라지거나 상태가 되돌아가지 않았다",
        not r12_problems,
        " / ".join(r12_problems) if r12_problems else f"이전 반론 {len(previous.objections)}개가 모두 남아 있다.",
        exempt=True,
    )

    return Review(
        results=tuple(results),
        signature=signature,
        resolved_now=resolved_now,
        raised_now=raised_now,
        superseded_now=moves["superseded"],
        changed_conditions=changed,
        resolve_first=resolve_first,
    )


def snapshot(document: Document, backlog: Backlog) -> tuple[dict[str, str], dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """다음 반복이 비교에 쓸 스냅샷을 만든다."""
    document_snapshot = {"digest": document.digest, "preamble_digest": document.preamble_digest}
    conditions = {
        c.identifier: {"digest": c.digest, "substance_digest": c.substance_digest}
        for c in document.conditions
    }
    objections = {
        o.identifier: {"status": o.status, "digest": o.digest, "target": o.target}
        for o in backlog.items
    }
    return document_snapshot, conditions, objections


def repository_paths(root: Path) -> tuple[Path, Path, Path, Path]:
    """(문서, 반론 디렉터리, 상태 파일, 보고서 디렉터리)."""
    return root / "Hanik.md", root / "objections", root / "state" / "state.json", root / "reports"
