"""반론(objection) 파서.

반론 하나가 파일 하나다. 미해결 반론의 집합이 이 저장소의 백로그이며,
반론 본문의 해시는 '반론을 약화시켜 해소하는 것'을 막는 데 쓰인다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import text as textutil

DIRECTORY_NAME = "objections"

STATUS_OPEN = "open"
STATUS_RESOLVED = "resolved"
STATUS_SUPERSEDED = "superseded"
STATUSES = (STATUS_OPEN, STATUS_RESOLVED, STATUS_SUPERSEDED)

#: 문서 전체를 겨냥한 반론이 쓰는 대상 값.
DOCUMENT_TARGET = "문서"

#: 해소 표시가 아직 없음을 뜻하는 값.
UNRESOLVED_MARK = "—"

REQUIRED_META = ("상태", "대상", "제기", "해소")
ARGUMENT_HEADING = "반론"
CRITERIA_HEADING = "해소 조건"

_TITLE = re.compile(r"^#\s+(O-\d{4})\s*·\s*(.+?)\s*$")
_META = re.compile(r"^-\s+(?P<key>[^:]+):\s*(?P<value>.*)$")
_SECTION = re.compile(r"^##\s+(.+?)\s*$")
_TARGET = re.compile(r"^(?:C-\d{3}|문서)$")
_REPLACEMENT = re.compile(r"O-\d{4}")


@dataclass(frozen=True)
class Objection:
    """반론 하나."""

    identifier: str
    title: str
    status: str
    target: str
    raised: str
    resolved: str
    argument: str
    criteria: str
    digest: str
    path: Path
    problems: tuple[str, ...]

    @property
    def is_open(self) -> bool:
        return self.status == STATUS_OPEN

    @property
    def is_resolved(self) -> bool:
        return self.status == STATUS_RESOLVED

    @property
    def is_superseded(self) -> bool:
        return self.status == STATUS_SUPERSEDED

    @property
    def targets_document(self) -> bool:
        return self.target == DOCUMENT_TARGET

    @property
    def replacement(self) -> str | None:
        """은퇴한 반론이 비판을 넘긴 대상 반론의 식별자."""
        if not self.is_superseded:
            return None
        match = _REPLACEMENT.search(self.resolved)
        return match.group(0) if match else None


@dataclass(frozen=True)
class Backlog:
    """`objections/`에 있는 반론 전체."""

    directory: Path
    items: tuple[Objection, ...]
    problems: tuple[str, ...]

    def by_id(self, identifier: str) -> Objection | None:
        for item in self.items:
            if item.identifier == identifier:
                return item
        return None

    @property
    def open_items(self) -> tuple[Objection, ...]:
        return tuple(item for item in self.items if item.is_open)

    @property
    def resolved_items(self) -> tuple[Objection, ...]:
        return tuple(item for item in self.items if item.is_resolved)


def _parse_one(path: Path) -> Objection:
    raw = textutil.normalize(path.read_text(encoding="utf-8"))
    lines = raw.split("\n")

    problems: list[str] = []
    identifier = path.stem
    title = ""
    meta: dict[str, str] = {}
    sections: dict[str, list[str]] = {}
    current: str | None = None

    for number, line in enumerate(lines, start=1):
        title_match = _TITLE.match(line)
        if title_match and not title:
            identifier, title = title_match.group(1), title_match.group(2)
            continue
        section_match = _SECTION.match(line)
        if section_match:
            current = section_match.group(1)
            if current in sections:
                problems.append(f"{path.name}: 절 '{current}'이 두 번 나온다.")
            sections.setdefault(current, [])
            continue
        if current is None:
            meta_match = _META.match(line)
            if meta_match:
                key = meta_match.group("key").strip()
                if key in meta:
                    problems.append(f"{path.name}: 메타데이터 '{key}'가 두 번 나온다.")
                meta[key] = meta_match.group("value").strip()
            elif line.strip() and not title:
                problems.append(f"{path.name} {number}행: 제목보다 앞선 내용이 있다.")
            continue
        sections[current].append(line)

    if not title:
        problems.append(f"{path.name}: '# O-NNNN · 제목' 형식의 제목이 없다.")
    if identifier != path.stem:
        problems.append(f"{path.name}: 제목의 식별자 {identifier}가 파일 이름과 다르다.")

    for key in REQUIRED_META:
        if key not in meta:
            problems.append(f"{path.name}: 메타데이터 '{key}'가 없다.")

    status = meta.get("상태", "")
    if status not in STATUSES:
        problems.append(f"{path.name}: 상태 '{status}'는 {STATUSES} 중 하나여야 한다.")

    target = meta.get("대상", "")
    if not _TARGET.match(target):
        problems.append(f"{path.name}: 대상 '{target}'은 C-NNN 또는 '{DOCUMENT_TARGET}'이어야 한다.")

    resolved = meta.get("해소", UNRESOLVED_MARK)
    if status in (STATUS_RESOLVED, STATUS_SUPERSEDED) and resolved in ("", UNRESOLVED_MARK):
        problems.append(f"{path.name}: {status}인데 '해소' 항목이 비어 있다.")
    if status == STATUS_OPEN and resolved not in ("", UNRESOLVED_MARK):
        problems.append(f"{path.name}: open인데 '해소' 항목이 채워져 있다.")
    if status == STATUS_SUPERSEDED:
        match = _REPLACEMENT.search(resolved)
        if match is None:
            problems.append(
                f"{path.name}: superseded는 '해소'에 비판을 넘겨받은 반론 O-NNNN을 적어야 한다."
            )
        elif match.group(0) == identifier:
            problems.append(f"{path.name}: 자기 자신을 대체 반론으로 지목할 수 없다.")

    for heading in (ARGUMENT_HEADING, CRITERIA_HEADING):
        if heading not in sections:
            problems.append(f"{path.name}: '## {heading}' 절이 없다.")
    for heading in sections:
        if heading not in (ARGUMENT_HEADING, CRITERIA_HEADING):
            problems.append(f"{path.name}: 알 수 없는 절 '{heading}'.")

    argument = "\n".join(sections.get(ARGUMENT_HEADING, [])).strip()
    criteria = "\n".join(sections.get(CRITERIA_HEADING, [])).strip()

    return Objection(
        identifier=identifier,
        title=title,
        status=status,
        target=target,
        raised=meta.get("제기", ""),
        resolved=resolved,
        argument=argument,
        criteria=criteria,
        digest=textutil.digest(title, target, argument, criteria),
        path=path,
        problems=tuple(problems),
    )


def parse_backlog(directory: Path) -> Backlog:
    """`objections/`의 모든 반론을 읽는다. 디렉터리가 없어도 예외를 내지 않는다."""
    problems: list[str] = []
    if not directory.is_dir():
        return Backlog(directory=directory, items=(), problems=(f"{directory.name}/ 디렉터리가 없다.",))

    items: list[Objection] = []
    for path in sorted(directory.glob("*.md")):
        if not re.fullmatch(r"O-\d{4}", path.stem):
            problems.append(f"{path.name}: 파일 이름이 O-NNNN.md 형식이 아니다.")
            continue
        objection = _parse_one(path)
        problems.extend(objection.problems)
        items.append(objection)

    if not items:
        problems.append("반론이 하나도 없다.")
    return Backlog(directory=directory, items=tuple(items), problems=tuple(problems))
