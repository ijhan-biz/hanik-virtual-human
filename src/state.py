"""Durable state handling for the Hanik improvement loop.

The loop's memory lives in ``state/state.json``. Three properties matter and
are enforced here rather than left to convention:

* **Atomicity** -- state is written to a temporary file in the same directory
  and moved into place with :func:`os.replace`, which is atomic on POSIX and
  Windows. A crash mid-write can never leave a truncated state file.
* **Recoverability** -- a missing, unparsable, or structurally invalid state
  file resets to a fresh empty state instead of raising, so the loop can
  always make forward progress. The reset is visible in the next report.
* **Boundedness without loss** -- only the most recent ``history_limit``
  iterations stay in the working state file. Older entries are moved into
  ``state/archive/`` as JSON files, so the audit trail stays complete while
  the file the loop reads every iteration stays small.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List

#: Bumped whenever the persisted structure changes in a way that older
#: readers would misinterpret. Legacy states without the key are migrated.
SCHEMA_VERSION = 2

#: Number of full history entries retained in ``state/state.json``. Older
#: entries are archived to ``state/archive/`` instead of being discarded.
DEFAULT_HISTORY_LIMIT = 50

#: Environment variable overriding :data:`DEFAULT_HISTORY_LIMIT`.
HISTORY_LIMIT_ENV_VAR = "HANIK_HISTORY_LIMIT"

DEFAULT_STATE_PATH = Path("state/state.json")


def empty_state() -> Dict[str, Any]:
    """Return a fresh, valid, empty state."""

    return {
        "schema_version": SCHEMA_VERSION,
        "iteration": 0,
        "history": [],
        "archive": {"pruned_count": 0, "files": []},
        "stagnant_iterations": 0,
    }


def _coerce_archive(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {"pruned_count": 0, "files": []}
    pruned = value.get("pruned_count")
    files = value.get("files")
    return {
        "pruned_count": pruned if isinstance(pruned, int) and pruned >= 0 else 0,
        "files": [f for f in files if isinstance(f, str)] if isinstance(files, list) else [],
    }


def load_state(state_path: Path = DEFAULT_STATE_PATH) -> Dict[str, Any]:
    """Load prior state from ``state_path``, recovering from corruption.

    A state file written by an older schema version is migrated in memory:
    missing keys are filled with safe defaults rather than treated as
    corruption, so upgrading the loop never discards history.
    """

    if not state_path.exists():
        return empty_state()

    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_state()

    if not isinstance(data, dict):
        return empty_state()

    iteration = data.get("iteration")
    history = data.get("history")
    if not isinstance(iteration, int) or isinstance(iteration, bool) or iteration < 0:
        return empty_state()
    if not isinstance(history, list):
        return empty_state()

    stagnant = data.get("stagnant_iterations")
    return {
        "schema_version": SCHEMA_VERSION,
        "iteration": iteration,
        "history": [entry for entry in history if isinstance(entry, dict)],
        "archive": _coerce_archive(data.get("archive")),
        "stagnant_iterations": stagnant if isinstance(stagnant, int) and stagnant >= 0 else 0,
    }


def _write_json_atomic(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            json.dump(payload, tmp_file, indent=2, ensure_ascii=True, sort_keys=True)
            tmp_file.write("\n")
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


def save_state_atomic(state: Dict[str, Any], state_path: Path = DEFAULT_STATE_PATH) -> None:
    """Atomically write ``state`` as JSON to ``state_path``."""

    _write_json_atomic(state, state_path)


def get_history_limit() -> int:
    """Return the configured history limit, falling back to the default."""

    raw = os.environ.get(HISTORY_LIMIT_ENV_VAR)
    if raw is None:
        return DEFAULT_HISTORY_LIMIT
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_HISTORY_LIMIT
    return value if value > 0 else DEFAULT_HISTORY_LIMIT


def archive_dir_for(state_path: Path) -> Path:
    return state_path.parent / "archive"


def prune_history(
    state: Dict[str, Any],
    state_path: Path,
    history_limit: int,
) -> List[Path]:
    """Move history entries beyond ``history_limit`` into ``state/archive/``.

    Mutates ``state`` in place and returns the archive files written. Nothing
    is deleted: pruned entries are persisted to an archive file named after
    the iteration range it covers before they leave the working state.
    """

    history = state.get("history") or []
    if len(history) <= history_limit:
        return []

    overflow = history[: len(history) - history_limit]
    retained = history[len(history) - history_limit :]

    iterations = [
        entry.get("iteration")
        for entry in overflow
        if isinstance(entry.get("iteration"), int)
    ]
    first = min(iterations) if iterations else 0
    last = max(iterations) if iterations else 0

    archive_dir = archive_dir_for(state_path)
    archive_path = archive_dir / f"history-{first:04d}-{last:04d}.json"
    _write_json_atomic(
        {"first_iteration": first, "last_iteration": last, "entries": overflow},
        archive_path,
    )

    archive = _coerce_archive(state.get("archive"))
    archive["pruned_count"] = archive["pruned_count"] + len(overflow)
    relative = archive_path.relative_to(state_path.parent.parent).as_posix() if _is_relative(
        archive_path, state_path.parent.parent
    ) else archive_path.as_posix()
    if relative not in archive["files"]:
        archive["files"].append(relative)

    state["history"] = retained
    state["archive"] = archive
    return [archive_path]


def _is_relative(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def archived_entry_count(state_path: Path) -> int:
    """Count entries actually present in ``state/archive/`` on disk."""

    archive_dir = archive_dir_for(state_path)
    if not archive_dir.is_dir():
        return 0

    total = 0
    for archive_file in sorted(archive_dir.glob("history-*.json")):
        try:
            payload = json.loads(archive_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        entries = payload.get("entries") if isinstance(payload, dict) else None
        if isinstance(entries, list):
            total += len(entries)
    return total
