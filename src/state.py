"""반복 사이에 남는 상태.

상태는 판단을 담지 않는다. 직전 반복의 문서와 반론이 어떤 모습이었는지에 대한
해시와 이력만 담는다. 정직성 규칙은 이 스냅샷과 현재를 비교해서 성립한다.

쓰기는 임시 파일에 쓰고 fsync한 뒤 `os.replace`로 갈아끼운다. 중간에 죽어도
`state/state.json`이 잘린 채로 남지 않는다.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_HISTORY_LIMIT = 50
LEDGER_NAME = "ledger.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def history_limit(environ: dict[str, str] | None = None) -> int:
    """`HANIK_HISTORY_LIMIT`을 읽는다. 잘못된 값은 기본값으로 되돌린다."""
    source = os.environ if environ is None else environ
    try:
        value = int(source.get("HANIK_HISTORY_LIMIT", DEFAULT_HISTORY_LIMIT))
    except (TypeError, ValueError):
        return DEFAULT_HISTORY_LIMIT
    return value if value > 0 else DEFAULT_HISTORY_LIMIT


@dataclass
class State:
    """직전 반복의 스냅샷."""

    version: int = SCHEMA_VERSION
    iteration: int = 0
    updated_at: str = ""
    document: dict[str, Any] = field(default_factory=dict)
    conditions: dict[str, dict[str, str]] = field(default_factory=dict)
    objections: dict[str, dict[str, str]] = field(default_factory=dict)
    signature: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_first_run(self) -> bool:
        """비교 대상이 없는가.

        반복 번호가 아니라 **승인된 스냅샷의 유무**로 판단한다. 규칙을 어긴 반복은
        스냅샷을 갱신하지 않으므로, 첫 반복이 실패해도 다음 반복이 비교 대상 없이
        규칙에 걸리는 일이 없다.
        """
        return not self.conditions

    def to_json(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "iteration": self.iteration,
            "updated_at": self.updated_at,
            "document": self.document,
            "conditions": self.conditions,
            "objections": self.objections,
            "signature": self.signature,
            "history": self.history,
        }


def _coerce(payload: Any) -> tuple[State, list[str]]:
    """읽어들인 값을 State로 만든다. 구조가 어긋나면 새 상태로 되돌린다."""
    problems: list[str] = []
    if not isinstance(payload, dict):
        return State(), ["state.json의 최상위가 객체가 아니다. 새 상태로 시작한다."]

    state = State()
    version = payload.get("version")
    if not isinstance(version, int) or version > SCHEMA_VERSION:
        problems.append(f"알 수 없는 상태 스키마 {version!r}. 새 상태로 시작한다.")
        return State(), problems

    iteration = payload.get("iteration", 0)
    if not isinstance(iteration, int) or iteration < 0:
        problems.append(f"반복 번호 {iteration!r}가 올바르지 않다. 0으로 되돌린다.")
        iteration = 0
    state.iteration = iteration
    state.updated_at = payload.get("updated_at") if isinstance(payload.get("updated_at"), str) else ""
    state.signature = payload.get("signature") if isinstance(payload.get("signature"), str) else ""

    document = payload.get("document")
    state.document = document if isinstance(document, dict) else {}

    conditions = payload.get("conditions")
    if isinstance(conditions, dict):
        state.conditions = {
            key: value for key, value in conditions.items() if isinstance(value, dict)
        }
    else:
        problems.append("조건 스냅샷이 없거나 형식이 어긋난다. 비운 채 시작한다.")

    objections = payload.get("objections")
    if isinstance(objections, dict):
        state.objections = {
            key: value for key, value in objections.items() if isinstance(value, dict)
        }
    else:
        problems.append("반론 스냅샷이 없거나 형식이 어긋난다. 비운 채 시작한다.")

    history = payload.get("history")
    if isinstance(history, list):
        state.history = [entry for entry in history if isinstance(entry, dict)]
    else:
        problems.append("이력이 없거나 형식이 어긋난다. 비운 채 시작한다.")

    return state, problems


def load_state(path: Path) -> tuple[State, list[str]]:
    """상태를 읽는다. 없거나 망가졌으면 새 상태로 복구하고 이유를 함께 돌려준다."""
    if not path.is_file():
        return State(), []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return State(), [f"state.json을 읽을 수 없다({error.__class__.__name__}). 새 상태로 시작한다."]
    return _coerce(payload)


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), prefix=f".{path.name}.", delete=False
    )
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


def load_ledger(path: Path) -> list[dict[str, Any]]:
    """인덱스를 만들기 위한 전체 반복 기록. 잘리지 않는다."""
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [entry for entry in payload if isinstance(entry, dict)] if isinstance(payload, list) else []


def save_ledger(path: Path, entries: list[dict[str, Any]]) -> None:
    """원장을 원자적으로 쓴다. state.json의 이력이 잘려도 여기에는 남는다."""
    _atomic_write(path, json.dumps(entries, ensure_ascii=False, indent=2) + "\n")


def save_state(path: Path, state: State, limit: int | None = None) -> None:
    """상태를 원자적으로 쓴다. 상한을 넘는 이력은 잘라낸다.

    잘려나간 이력은 `state/ledger.json`에 그대로 남아 있으므로 손실이 아니다.
    """
    bound = history_limit() if limit is None else limit
    if len(state.history) > bound:
        state.history = state.history[len(state.history) - bound :]

    state.version = SCHEMA_VERSION
    state.updated_at = _now()
    _atomic_write(path, json.dumps(state.to_json(), ensure_ascii=False, indent=2) + "\n")
