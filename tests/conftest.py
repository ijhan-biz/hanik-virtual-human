"""테스트가 공유하는 저장소 조립 도구.

정직성 규칙은 '이전과 지금'을 비교하므로, 테스트는 임시 디렉터리에 최소한의
유효한 저장소를 만들고 그것을 조금씩 바꾸며 규칙을 확인한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.text import visible_length


def filler(seed: str, chars: int) -> str:
    """지정한 분량을 넘는 문장 뭉치. 문장마다 달라서 조건 간 중복이 생기지 않는다."""
    parts: list[str] = []
    index = 0
    while visible_length(" ".join(parts)) < chars:
        parts.append(f"{seed} 논거의 {index}번째 문장을 이어 적는다.")
        index += 1
    return " ".join(parts)


def condition_block(
    identifier: str = "C-001",
    title: str = "체현",
    claim: str | None = None,
    grounds: str | None = None,
    limits: str | None = None,
    revision: str = "반복 0000에서 시드로 작성.",
) -> str:
    claim = filler(f"{identifier} 주장", 100) if claim is None else claim
    grounds = filler(f"{identifier} 근거", 320) if grounds is None else grounds
    limits = filler(f"{identifier} 한계", 120) if limits is None else limits
    return "\n".join(
        [
            f"## {identifier} · {title}",
            "",
            f"**주장:** {claim}",
            "",
            f"**근거:** {grounds}",
            "",
            f"**한계:** {limits}",
            "",
            f"**개정:** {revision}",
            "",
        ]
    )


def document_text(blocks: list[str] | None = None, preamble: str = "Hanik의 조건을 검토한다.") -> str:
    blocks = [condition_block()] if blocks is None else blocks
    return "\n".join(["# Hanik", "", preamble, ""] + blocks)


def objection_text(
    identifier: str = "O-0001",
    title: str = "체현 조건은 정의에 의한 배제다",
    status: str = "open",
    target: str = "C-001",
    raised: str = "반복 0000",
    resolved: str = "—",
    argument: str | None = None,
    criteria: str | None = None,
) -> str:
    argument = filler(f"{identifier} 반론", 280) if argument is None else argument
    criteria = filler(f"{identifier} 해소 조건", 140) if criteria is None else criteria
    return "\n".join(
        [
            f"# {identifier} · {title}",
            "",
            f"- 상태: {status}",
            f"- 대상: {target}",
            f"- 제기: {raised}",
            f"- 해소: {resolved}",
            "",
            "## 반론",
            "",
            argument,
            "",
            "## 해소 조건",
            "",
            criteria,
            "",
        ]
    )


def build_repository(root: Path, conditions: list[str] | None = None, objections: list[str] | None = None) -> Path:
    """규칙을 모두 만족하는 최소 저장소를 만든다."""
    conditions = [condition_block()] if conditions is None else conditions
    objections = [objection_text()] if objections is None else objections

    (root / "Hanik.md").write_text(document_text(conditions), encoding="utf-8")
    directory = root / "objections"
    directory.mkdir(exist_ok=True)
    for body in objections:
        identifier = body.split("·")[0].replace("#", "").strip()
        (directory / f"{identifier}.md").write_text(body, encoding="utf-8")
    (root / "state").mkdir(exist_ok=True)
    (root / "reports").mkdir(exist_ok=True)
    return root


@pytest.fixture()
def repository(tmp_path: Path) -> Path:
    return build_repository(tmp_path)
