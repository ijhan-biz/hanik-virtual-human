"""마침 — 루프가 언제 멈춰야 하는가.

이 저장소는 문서가 완성된다고 보지 않는다. R8은 미해결 반론이 0이 되는 것을
위반으로 취급한다. 비판이 멈춘 것을 완성으로 착각하는 것이 전신을 망친 장치이기
때문이다. 그러므로 "다 했으니 끝"이라는 종료는 여기에 없다.

그래도 멈춰야 할 때는 있다.

- **정체.** 같은 증거 서명이 여러 반복 동안 반복된다. 다시 돌려도 달라지지 않는
  상태이고, 이때 계속 도는 것은 진전이 아니라 전기를 쓰는 일이다. 전신 저장소가
  250번의 반복 동안 한 일이 정확히 이것이었다.
- **마감.** 사람이 캠페인을 끝내기로 했다. 판단은 사람이 하고, 루프는 그 표시를
  읽어 마지막 결산을 남기고 물러난다.

두 경우 모두 루프는 조용히 죽지 않는다. 결산을 갱신하고, 이유를 보고서에 적고,
러너가 알아볼 수 있는 종료 코드로 끝난다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: 계속 돌아도 되는 상태.
CONTINUE = "계속"

#: 같은 증거가 되풀이된다. 사람이 개입해야 한다.
STAGNANT = "정체"

#: 사람이 캠페인을 끝냈다.
SETTLED = "마감"

#: 같은 서명이 이만큼 이어지면 정체로 본다.
DEFAULT_STAGNATION_LIMIT = 5

#: 사람이 마감을 요청했음을 알리는 표시 파일 이름. `state/` 아래에 놓인다.
FINISH_MARKER = "finish"

#: 정체나 마감으로 루프가 물러났음을 알리는 종료 코드.
EXIT_CONCLUDED = 3


def stagnation_limit(environ: dict[str, str] | None = None) -> int:
    """`HANIK_STAGNATION_LIMIT`을 읽는다. 잘못된 값은 기본값으로 되돌린다."""
    source = os.environ if environ is None else environ
    try:
        value = int(source.get("HANIK_STAGNATION_LIMIT", DEFAULT_STAGNATION_LIMIT))
    except (TypeError, ValueError):
        return DEFAULT_STAGNATION_LIMIT
    return value if value > 1 else DEFAULT_STAGNATION_LIMIT


@dataclass(frozen=True)
class Conclusion:
    """루프가 계속 돌아야 하는지에 대한 판정."""

    state: str
    reason: str
    guidance: str = ""

    @property
    def should_stop(self) -> bool:
        return self.state != CONTINUE

    @property
    def exit_code(self) -> int:
        return EXIT_CONCLUDED if self.should_stop else 0


def finish_requested(state_dir: Path, environ: dict[str, str] | None = None) -> bool:
    """사람이 마감을 요청했는가.

    표시 파일과 환경 변수 둘 다 본다. 파일은 러너를 거치지 않고도 남길 수 있고,
    환경 변수는 한 번만 끝내고 싶을 때 쓴다.
    """
    source = os.environ if environ is None else environ
    if str(source.get("HANIK_FINISH", "")).strip().lower() in {"1", "true", "yes"}:
        return True
    return (state_dir / FINISH_MARKER).exists()


def _stuck_run(ledger: list[dict[str, Any]]) -> tuple[int, str]:
    """꼬리에 이어진 '위반이면서 같은 서명'의 길이와 그 서명.

    통과한 반복에서 멈춘다. 통과는 승인된 스냅샷을 밀어 올리므로 다음 반복은
    새 기준과 견주게 되고, 다시 돌리면 결과가 달라진다. 곧 통과 이전은 지금
    막혀 있다는 증거가 되지 못한다.
    """
    signature = ""
    length = 0
    for entry in reversed(ledger):
        if entry.get("ok"):
            break
        current = str(entry.get("signature", ""))
        if length == 0:
            signature = current
        elif current != signature:
            break
        length += 1
    return length, signature


def assess(
    ledger: list[dict[str, Any]],
    state_dir: Path,
    limit: int | None = None,
    environ: dict[str, str] | None = None,
) -> Conclusion:
    """이번 반복을 마지막으로 삼아야 하는지 판정한다.

    원장은 이미 이번 반복까지 반영된 상태로 들어온다.
    """
    if finish_requested(state_dir, environ):
        return Conclusion(
            state=SETTLED,
            reason="사람이 마감을 요청했다.",
            guidance=(
                "`SUMMARY.md`가 마지막 결산이다. 마감을 물리려면 "
                f"`state/{FINISH_MARKER}`를 지워라."
            ),
        )

    bound = stagnation_limit(environ) if limit is None else limit
    stuck, signature = _stuck_run(ledger)
    if stuck >= bound and signature:
        return Conclusion(
            state=STAGNANT,
            reason=(
                f"마지막 {stuck}번의 반복이 잇달아 위반이면서 같은 증거 서명 "
                f"`{signature[:16]}`를 냈다. 조건의 실질도 반론의 상태도 그대로다."
            ),
            guidance=(
                "다시 돌려도 결과는 같다. 세션이 문서를 실제로 고치지 못하고 있다는 "
                "뜻이므로, 사람이 브리프와 마지막 보고서를 읽고 막힌 곳을 풀어야 한다. "
                "반복을 더 쌓는 것은 전신 저장소가 250번에 걸쳐 한 일과 같다."
            ),
        )

    return Conclusion(state=CONTINUE, reason="증거가 계속 움직이고 있다.")


def main(argv: list[str] | None = None) -> int:
    """반복을 돌리지 않고 지금 물러나야 하는지만 묻는다.

    러너는 세션이 스스로 `src.hanik_loop`을 실행하게 두므로 그 종료 코드를 보지
    못한다. 그래서 매 반복 뒤에 이것을 따로 물어본다.
    """
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Hanik 루프가 물러나야 하는지 묻는다.")
    parser.add_argument("--root", type=Path, default=None, help="저장소 뿌리 경로")
    parser.add_argument("--quiet", action="store_true", help="이유를 출력하지 않는다")
    arguments = parser.parse_args(argv)

    root = Path(__file__).resolve().parent.parent if arguments.root is None else arguments.root
    state_dir = root / "state"
    try:
        payload = json.loads((state_dir / "ledger.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = []
    ledger = [entry for entry in payload if isinstance(entry, dict)] if isinstance(payload, list) else []

    verdict = assess(ledger, state_dir)
    if not arguments.quiet:
        print(f"{verdict.state} — {verdict.reason}")
        if verdict.guidance:
            print(verdict.guidance)
    return verdict.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
