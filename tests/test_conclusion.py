"""마침 테스트.

멈추는 판단은 두 갈래뿐이다. 같은 증거가 되풀이되는 정체와, 사람이 끝내기로 한
마감이다. "다 했으니 끝"은 여기에 없어야 한다 — 그것이 전신 저장소를 망친 착각이다.
"""

from __future__ import annotations

from pathlib import Path

from src.conclusion import (
    CONTINUE,
    EXIT_CONCLUDED,
    FINISH_MARKER,
    SETTLED,
    STAGNANT,
    assess,
    stagnation_limit,
)


def _ledger(signatures: list[str]) -> list[dict]:
    return [
        {"iteration": index + 1, "signature": signature, "ok": False}
        for index, signature in enumerate(signatures)
    ]


def test_증거가_움직이면_계속한다(tmp_path: Path) -> None:
    verdict = assess(_ledger(["a", "b", "c", "d", "e"]), tmp_path, limit=5)
    assert verdict.state == CONTINUE
    assert not verdict.should_stop
    assert verdict.exit_code == 0


def test_같은_서명이_이어지면_정체다(tmp_path: Path) -> None:
    verdict = assess(_ledger(["z"] * 5), tmp_path, limit=5)
    assert verdict.state == STAGNANT
    assert verdict.should_stop
    assert verdict.exit_code == EXIT_CONCLUDED
    assert "5번" in verdict.reason


def test_정체는_최근_구간만_본다(tmp_path: Path) -> None:
    """옛날에 같은 서명이 있었다고 지금 정체인 것은 아니다."""
    verdict = assess(_ledger(["z", "z", "z", "z", "z", "새것"]), tmp_path, limit=5)
    assert verdict.state == CONTINUE


def test_기록이_상한보다_적으면_정체로_보지_않는다(tmp_path: Path) -> None:
    verdict = assess(_ledger(["z", "z"]), tmp_path, limit=5)
    assert verdict.state == CONTINUE


def test_표시_파일이_있으면_마감이다(tmp_path: Path) -> None:
    (tmp_path / FINISH_MARKER).write_text("", encoding="utf-8")
    verdict = assess(_ledger(["a", "b"]), tmp_path, limit=5)
    assert verdict.state == SETTLED
    assert verdict.should_stop
    assert FINISH_MARKER in verdict.guidance


def test_환경_변수로도_마감할_수_있다(tmp_path: Path) -> None:
    verdict = assess(_ledger(["a", "b"]), tmp_path, limit=5, environ={"HANIK_FINISH": "1"})
    assert verdict.state == SETTLED


def test_마감_변수의_거짓값은_마감이_아니다(tmp_path: Path) -> None:
    verdict = assess(_ledger(["a", "b"]), tmp_path, limit=5, environ={"HANIK_FINISH": "0"})
    assert verdict.state == CONTINUE


def test_마감이_정체보다_앞선다(tmp_path: Path) -> None:
    """사람의 판단이 기계의 판정을 덮는다."""
    (tmp_path / FINISH_MARKER).write_text("", encoding="utf-8")
    verdict = assess(_ledger(["z"] * 5), tmp_path, limit=5)
    assert verdict.state == SETTLED


def test_정체_상한은_환경_변수로_읽는다() -> None:
    assert stagnation_limit({"HANIK_STAGNATION_LIMIT": "9"}) == 9


def test_정체_상한의_잘못된_값은_기본값으로_돌아간다() -> None:
    for value in ("0", "1", "-3", "붙임", ""):
        assert stagnation_limit({"HANIK_STAGNATION_LIMIT": value}) == 5


def test_통과가_섞여_있으면_정체가_아니다(tmp_path: Path) -> None:
    """R11은 직전 원장 항목이 아니라 '승인된 스냅샷'과 서명을 견준다.

    위반한 반복은 스냅샷을 갱신하지 않으므로, 위반이 이어진 뒤의 통과는 앞선
    위반들과 같은 서명을 지닐 수 있다. 실제로 반복 1584-1588에서 그렇게 되어
    통과한 반복이 정체로 오판되었다. 그 통과가 스냅샷을 밀어 올렸으니 다음
    반복은 새 기준과 견주게 되고, 다시 돌리면 결과는 달라진다.
    """
    ledger = [
        {"iteration": 1584, "signature": "2cbf8af8", "ok": False},
        {"iteration": 1585, "signature": "2cbf8af8", "ok": False},
        {"iteration": 1586, "signature": "2cbf8af8", "ok": False},
        {"iteration": 1587, "signature": "2cbf8af8", "ok": False},
        {"iteration": 1588, "signature": "2cbf8af8", "ok": True},
    ]
    assert assess(ledger, tmp_path, limit=5).state == CONTINUE


def test_잇달아_위반이고_서명이_같으면_정체다(tmp_path: Path) -> None:
    ledger = [
        {"iteration": 1584 + i, "signature": "2cbf8af8", "ok": False} for i in range(5)
    ]
    verdict = assess(ledger, tmp_path, limit=5)
    assert verdict.state == STAGNANT
    assert "잇달아 위반" in verdict.reason


def test_통과_이전의_막힘은_세지_않는다(tmp_path: Path) -> None:
    """통과가 스냅샷을 밀어 올리므로 그 이전은 지금 막혀 있다는 증거가 아니다."""
    ledger = [
        {"iteration": 1, "signature": "aaaa", "ok": False},
        {"iteration": 2, "signature": "aaaa", "ok": False},
        {"iteration": 3, "signature": "aaaa", "ok": True},
        {"iteration": 4, "signature": "aaaa", "ok": False},
        {"iteration": 5, "signature": "aaaa", "ok": False},
    ]
    assert assess(ledger, tmp_path, limit=3).state == CONTINUE
    ledger.append({"iteration": 6, "signature": "aaaa", "ok": False})
    assert assess(ledger, tmp_path, limit=3).state == STAGNANT


def test_서명이_바뀌면_막힘이_끊긴다(tmp_path: Path) -> None:
    ledger = [
        {"iteration": 1, "signature": "aaaa", "ok": False},
        {"iteration": 2, "signature": "bbbb", "ok": False},
        {"iteration": 3, "signature": "bbbb", "ok": False},
    ]
    assert assess(ledger, tmp_path, limit=3).state == CONTINUE
