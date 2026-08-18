"""`Hanik.md` 파서 테스트."""

from __future__ import annotations

from pathlib import Path

from conftest import condition_block, document_text
from src.document import parse_document


def _write(root: Path, text: str) -> Path:
    path = root / "Hanik.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_파일이_없으면_예외_대신_문제로_보고한다(tmp_path: Path) -> None:
    document = parse_document(tmp_path / "Hanik.md")
    assert not document.exists
    assert document.problems
    assert document.conditions == ()


def test_정상_문서를_조건_단위로_읽는다(tmp_path: Path) -> None:
    text = document_text([condition_block("C-001", "체현"), condition_block("C-002", "유한성")])
    document = parse_document(_write(tmp_path, text))
    assert document.problems == ()
    assert document.identifiers == ("C-001", "C-002")
    assert document.by_id("C-002").title == "유한성"
    assert "Hanik의 조건을 검토한다." in document.preamble


def test_필수_필드가_없으면_문제로_보고한다(tmp_path: Path) -> None:
    block = condition_block().replace("**한계:**", "**여담:**")
    document = parse_document(_write(tmp_path, document_text([block])))
    assert any("'한계'이 없거나" in problem for problem in document.problems)
    assert any("알 수 없는 필드 '여담'" in problem for problem in document.problems)


def test_같은_필드가_두_번_나오면_문제로_보고한다(tmp_path: Path) -> None:
    block = condition_block() + "\n**주장:** 뒤에 덧붙인 두 번째 주장이다.\n"
    document = parse_document(_write(tmp_path, document_text([block])))
    assert any("두 번 나온다" in problem for problem in document.problems)


def test_조건이_시작된_뒤의_다른_절은_문제다(tmp_path: Path) -> None:
    text = document_text([condition_block()]) + "\n## 부록\n\n조건이 아닌 절이다.\n"
    document = parse_document(_write(tmp_path, text))
    assert any("조건이 아닌 절" in problem for problem in document.problems)


def test_조건_번호가_겹치면_문제다(tmp_path: Path) -> None:
    text = document_text([condition_block("C-001", "하나"), condition_block("C-001", "둘")])
    document = parse_document(_write(tmp_path, text))
    assert any("두 번 나온다" in problem for problem in document.problems)


def test_실질_해시는_개정_필드를_무시한다(tmp_path: Path) -> None:
    """'개정' 줄만 고쳐서 내용이 바뀐 척하는 것을 막는 핵심 성질이다."""
    before = parse_document(_write(tmp_path, document_text([condition_block(revision="반복 0001.")])))
    after = parse_document(_write(tmp_path, document_text([condition_block(revision="반복 0002에서 재작성.")])))

    assert before.conditions[0].digest != after.conditions[0].digest
    assert before.conditions[0].substance_digest == after.conditions[0].substance_digest


def test_주장을_고치면_실질_해시가_바뀐다(tmp_path: Path) -> None:
    before = parse_document(_write(tmp_path, document_text([condition_block()])))
    after = parse_document(
        _write(tmp_path, document_text([condition_block(claim="완전히 다시 쓴 주장이다. " * 8)]))
    )
    assert before.conditions[0].substance_digest != after.conditions[0].substance_digest


def test_서식_차이는_해시를_바꾸지_않는다(tmp_path: Path) -> None:
    text = document_text([condition_block()])
    before = parse_document(_write(tmp_path, text))
    after = parse_document(_write(tmp_path, text.replace("\n\n", "\n\n\n") + "   \n"))
    assert before.digest == after.digest
