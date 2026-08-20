"""반론 파서 테스트."""

from __future__ import annotations

from pathlib import Path

from conftest import objection_text
from src.objections import parse_backlog


def _write(root: Path, *bodies: str) -> Path:
    directory = root / "objections"
    directory.mkdir(exist_ok=True)
    for body in bodies:
        identifier = body.split("·")[0].replace("#", "").strip()
        (directory / f"{identifier}.md").write_text(body, encoding="utf-8")
    return directory


def test_디렉터리가_없으면_문제로_보고한다(tmp_path: Path) -> None:
    backlog = parse_backlog(tmp_path / "objections")
    assert backlog.items == ()
    assert backlog.problems


def test_정상_반론을_읽는다(tmp_path: Path) -> None:
    backlog = parse_backlog(_write(tmp_path, objection_text()))
    assert backlog.problems == ()
    objection = backlog.items[0]
    assert objection.identifier == "O-0001"
    assert objection.is_open
    assert objection.target == "C-001"
    assert not objection.targets_document


def test_문서_전체를_겨냥한_반론을_읽는다(tmp_path: Path) -> None:
    backlog = parse_backlog(_write(tmp_path, objection_text(target="문서")))
    assert backlog.problems == ()
    assert backlog.items[0].targets_document


def test_알_수_없는_상태는_문제다(tmp_path: Path) -> None:
    backlog = parse_backlog(_write(tmp_path, objection_text(status="보류")))
    assert any("상태 '보류'" in problem for problem in backlog.problems)


def test_실재하지_않는_형식의_대상은_문제다(tmp_path: Path) -> None:
    backlog = parse_backlog(_write(tmp_path, objection_text(target="페르소나")))
    assert any("대상 '페르소나'" in problem for problem in backlog.problems)


def test_open인데_해소가_채워져_있으면_문제다(tmp_path: Path) -> None:
    backlog = parse_backlog(_write(tmp_path, objection_text(status="open", resolved="반복 0003")))
    assert any("open인데" in problem for problem in backlog.problems)


def test_resolved인데_해소가_비어_있으면_문제다(tmp_path: Path) -> None:
    backlog = parse_backlog(_write(tmp_path, objection_text(status="resolved", resolved="—")))
    assert any("resolved인데" in problem for problem in backlog.problems)


def test_필수_절이_없으면_문제다(tmp_path: Path) -> None:
    body = objection_text().replace("## 해소 조건", "## 덧붙임")
    backlog = parse_backlog(_write(tmp_path, body))
    assert any("'## 해소 조건' 절이 없다" in problem for problem in backlog.problems)
    assert any("알 수 없는 절" in problem for problem in backlog.problems)


def test_파일_이름과_식별자가_다르면_문제다(tmp_path: Path) -> None:
    directory = tmp_path / "objections"
    directory.mkdir()
    (directory / "O-0009.md").write_text(objection_text("O-0001"), encoding="utf-8")
    backlog = parse_backlog(directory)
    assert any("파일 이름과 다르다" in problem for problem in backlog.problems)


def test_해시는_상태_변화에_영향받지_않는다(tmp_path: Path) -> None:
    """해소 처리는 상태와 해소 항목만 바꾼다. 본문 해시는 그대로여야 한다."""
    opened = parse_backlog(_write(tmp_path, objection_text(status="open"))).items[0]
    closed = parse_backlog(
        _write(tmp_path, objection_text(status="resolved", resolved="반복 0004에서 C-001 재작성"))
    ).items[0]
    assert opened.digest == closed.digest


def test_본문을_고치면_해시가_바뀐다(tmp_path: Path) -> None:
    before = parse_backlog(_write(tmp_path, objection_text())).items[0]
    after = parse_backlog(_write(tmp_path, objection_text(argument="약하게 고쳐 쓴 반론이다. " * 12))).items[0]
    assert before.digest != after.digest
