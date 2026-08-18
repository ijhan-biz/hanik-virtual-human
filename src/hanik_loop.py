"""반복 하나를 실행한다.

    python3 -m src.hanik_loop

이 명령은 판단하지 않는다. 저장소를 있는 그대로 읽고, 정직성 규칙을 돌리고,
보고서와 다음 세션 브리프를 쓴다. 규칙을 어겼으면 0이 아닌 코드로 끝난다.

규칙을 어긴 반복은 **스냅샷을 갱신하지 않는다.** 어긴 상태가 다음 반복의 기준이
되어버리면 위반이 세탁되기 때문이다. 위반은 고쳐질 때까지 남는다.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from .document import parse_document
from .integrity import Review, repository_paths, review, snapshot
from .objections import parse_backlog
from .reporting import (
    BRIEF_NAME,
    INDEX_NAME,
    Metrics,
    measure,
    render_brief,
    render_index,
    render_report,
    report_path,
)
from .state import LEDGER_NAME, load_ledger, load_state, save_ledger, save_state


def repository_root() -> Path:
    return Path(__file__).resolve().parent.parent


def run(root: Path | None = None) -> int:
    """반복 하나를 수행하고 종료 코드를 돌려준다."""
    root = repository_root() if root is None else root
    document_path, objections_dir, state_path, reports_dir = repository_paths(root)

    state, notes = load_state(state_path)
    ledger = load_ledger(state_path.parent / LEDGER_NAME)

    document = parse_document(document_path)
    backlog = parse_backlog(objections_dir)
    outcome = review(document, backlog, state)

    iteration = state.iteration + 1
    metrics = measure(document, backlog, outcome)

    reports_dir.mkdir(parents=True, exist_ok=True)
    report = render_report(iteration, document, backlog, outcome, metrics, notes)
    report_path(reports_dir, iteration).write_text(report, encoding="utf-8")

    entry = {
        "iteration": iteration,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "signature": outcome.signature,
        "ok": outcome.ok,
        "conditions": metrics.conditions,
        "open": metrics.open_objections,
        "resolved_now": metrics.resolved_now,
        "raised_now": metrics.raised_now,
        "violations": [result.identifier for result in outcome.violations],
    }
    state.history.append(entry)
    ledger.append(entry)

    state.iteration = iteration
    if outcome.ok:
        document_snapshot, conditions, objections = snapshot(document, backlog)
        state.document = document_snapshot
        state.conditions = conditions
        state.objections = objections
        state.signature = outcome.signature

    save_state(state_path, state)
    save_ledger(state_path.parent / LEDGER_NAME, ledger)
    (reports_dir / INDEX_NAME).write_text(render_index(ledger), encoding="utf-8")
    (state_path.parent / BRIEF_NAME).write_text(
        render_brief(iteration, document, backlog, outcome, metrics), encoding="utf-8"
    )

    _print_summary(root, iteration, outcome, metrics, reports_dir)
    return 0 if outcome.ok else 1


def _print_summary(
    root: Path, iteration: int, outcome: Review, metrics: Metrics, reports_dir: Path
) -> None:
    relative = report_path(reports_dir, iteration).relative_to(root)
    print(f"반복 {iteration:04d} — {'통과' if outcome.ok else '위반'}")
    print(
        f"  조건 {metrics.conditions}개 / 미해결 반론 {metrics.open_objections}개 / "
        f"이번 해소 {metrics.resolved_now}개 / 이번 제기 {metrics.raised_now}개"
    )
    for result in outcome.violations:
        print(f"  [{result.identifier}] {result.title} — {result.evidence}")
    print(f"  보고서: {relative}")
    print("  브리프: state/next-session.md")
    if not outcome.ok:
        print("  스냅샷을 갱신하지 않았다. 위반을 고칠 때까지 기준은 그대로다.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hanik 반복 하나를 실행한다.")
    parser.add_argument("--root", type=Path, default=None, help="저장소 뿌리 경로")
    arguments = parser.parse_args(argv)
    return run(arguments.root)


if __name__ == "__main__":
    raise SystemExit(main())
