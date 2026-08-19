"""`Hanik.md` 파서.

문서는 조건(C-NNN) 단위로 나뉘고, 각 조건은 네 개의 필드를 갖는다.
파서는 구조만 본다. 분량이나 중복 같은 판정은 `integrity` 모듈이 맡는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import text as textutil

DOCUMENT_NAME = "Hanik.md"

#: 조건이 반드시 가져야 하는 필드. 순서는 권장이며 강제하지 않는다.
REQUIRED_FIELDS = ("주장", "근거", "한계", "개정")

#: 조건의 '실질'에 해당하는 필드. 해시 비교에서 '개정'은 제외한다.
#: 개정 줄만 고쳐 변경을 위장하는 것을 막기 위해서다.
SUBSTANCE_FIELDS = ("주장", "근거", "한계")

_CONDITION_HEADING = re.compile(r"^##\s+(C-\d{3})\s*·\s*(.+?)\s*$")
_ANY_H2 = re.compile(r"^##\s+(.*?)\s*$")
_FIELD = re.compile(r"^\*\*(?P<name>[^*:]+):\*\*\s*(?P<value>.*)$")


@dataclass(frozen=True)
class Condition:
    """`Hanik.md`의 조건 하나."""

    identifier: str
    title: str
    fields: dict[str, str]
    digest: str
    substance_digest: str
    line: int

    def field(self, name: str) -> str:
        return self.fields.get(name, "")


@dataclass(frozen=True)
class Document:
    """파싱된 `Hanik.md`."""

    path: Path
    exists: bool
    preamble: str
    conditions: tuple[Condition, ...]
    digest: str
    preamble_digest: str
    problems: tuple[str, ...]

    def by_id(self, identifier: str) -> Condition | None:
        for condition in self.conditions:
            if condition.identifier == identifier:
                return condition
        return None

    @property
    def identifiers(self) -> tuple[str, ...]:
        return tuple(condition.identifier for condition in self.conditions)


def condition_size(condition: Condition) -> int:
    """조건의 실질 분량(공백 제외).

    '개정'은 무엇을 왜 고쳤는지에 대한 기록이지 조건의 내용이 아니므로 세지
    않는다. 개정 줄을 길게 써서 분량 예산을 채우는 일을 막는다.
    """
    return sum(textutil.visible_length(condition.field(name)) for name in SUBSTANCE_FIELDS)


def document_size(document: "Document") -> int:
    """서문과 모든 조건의 실질 분량 합계."""
    return textutil.visible_length(document.preamble) + sum(
        condition_size(condition) for condition in document.conditions
    )


def _parse_fields(body_lines: list[str], identifier: str) -> tuple[dict[str, str], list[str]]:
    """조건 본문에서 `**이름:**` 필드를 뽑아낸다."""
    fields: dict[str, str] = {}
    problems: list[str] = []
    current: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if current is None:
            return
        fields[current] = "\n".join(buffer).strip()

    for line in body_lines:
        match = _FIELD.match(line)
        if match:
            flush()
            name = match.group("name").strip()
            if name in fields:
                problems.append(f"{identifier}: 필드 '{name}'이 두 번 나온다.")
            current = name
            buffer = [match.group("value")]
        elif current is not None:
            buffer.append(line)
        elif line.strip():
            problems.append(f"{identifier}: 첫 필드 앞에 본문이 있다 — {line.strip()[:30]}")
    flush()

    for name in REQUIRED_FIELDS:
        if not fields.get(name, "").strip():
            problems.append(f"{identifier}: 필수 필드 '{name}'이 없거나 비어 있다.")
    for name in fields:
        if name not in REQUIRED_FIELDS:
            problems.append(f"{identifier}: 알 수 없는 필드 '{name}'.")
    return fields, problems


def parse_document(path: Path) -> Document:
    """`Hanik.md`를 읽어 구조를 반환한다. 파일이 없어도 예외를 내지 않는다."""
    if not path.is_file():
        return Document(
            path=path,
            exists=False,
            preamble="",
            conditions=(),
            digest=textutil.digest(""),
            preamble_digest=textutil.digest(""),
            problems=(f"{path.name}이 없다.",),
        )

    raw = textutil.normalize(path.read_text(encoding="utf-8"))
    lines = raw.split("\n")

    problems: list[str] = []
    preamble_lines: list[str] = []
    conditions: list[Condition] = []

    started = False
    heading: re.Match[str] | None = None
    heading_line = 0
    body: list[str] = []

    def close(match: re.Match[str] | None, body_lines: list[str], at: int) -> None:
        if match is None:
            return
        identifier, title = match.group(1), match.group(2)
        fields, field_problems = _parse_fields(body_lines, identifier)
        problems.extend(field_problems)
        conditions.append(
            Condition(
                identifier=identifier,
                title=title,
                fields=fields,
                digest=textutil.digest(identifier, title, *(fields.get(name, "") for name in REQUIRED_FIELDS)),
                substance_digest=textutil.digest(
                    identifier, *(fields.get(name, "") for name in SUBSTANCE_FIELDS)
                ),
                line=at,
            )
        )

    for number, line in enumerate(lines, start=1):
        condition_match = _CONDITION_HEADING.match(line)
        if condition_match:
            close(heading, body, heading_line)
            started = True
            heading, heading_line, body = condition_match, number, []
            continue
        other_heading = _ANY_H2.match(line)
        if other_heading and started:
            problems.append(
                f"{number}행: 조건이 시작된 뒤에 조건이 아닌 절 '{other_heading.group(1)}'이 있다."
            )
            continue
        if started:
            body.append(line)
        else:
            preamble_lines.append(line)
    close(heading, body, heading_line)

    seen: set[str] = set()
    for condition in conditions:
        if condition.identifier in seen:
            problems.append(f"{condition.identifier}: 같은 조건 번호가 두 번 나온다.")
        seen.add(condition.identifier)

    if not conditions:
        problems.append("조건이 하나도 없다.")

    preamble = "\n".join(preamble_lines).strip()
    return Document(
        path=path,
        exists=True,
        preamble=preamble,
        conditions=tuple(conditions),
        digest=textutil.digest(raw),
        preamble_digest=textutil.digest(preamble),
        problems=tuple(problems),
    )
