"""루프 자체의 안전성.

이 저장소는 오프라인에서 돌고, 자기가 만든 텍스트를 실행하지 않는다. 관례가 아니라
AST 검사로 강제한다. 반론과 조건은 사람이 쓴 글이므로 그것을 실행 가능한 것으로
다루기 시작하면 이 루프는 전혀 다른 위험을 갖게 된다.
"""

from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "src"

FORBIDDEN_MODULES = {
    "socket",
    "ssl",
    "http",
    "urllib",
    "urllib2",
    "requests",
    "httpx",
    "aiohttp",
    "ftplib",
    "smtplib",
    "poplib",
    "imaplib",
    "telnetlib",
    "xmlrpc",
    "webbrowser",
    "subprocess",
    "multiprocessing",
    "pty",
}

FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__"}

FORBIDDEN_OS_ATTRIBUTES = {
    "system",
    "popen",
    "execv",
    "execve",
    "execl",
    "execlp",
    "execvp",
    "spawnl",
    "spawnv",
    "spawnve",
    "fork",
    "forkpty",
}


def _modules() -> list[tuple[Path, ast.Module]]:
    return [(path, ast.parse(path.read_text(encoding="utf-8"))) for path in sorted(SOURCE.rglob("*.py"))]


def test_src에_파이썬_모듈이_있다() -> None:
    assert _modules(), "검사할 모듈이 없다. 경로가 잘못되었을 수 있다."


def test_네트워크_모듈을_가져오지_않는다() -> None:
    offenders: list[str] = []
    for path, tree in _modules():
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.split(".")[0] in FORBIDDEN_MODULES:
                    offenders.append(f"{path.name}:{node.lineno} {name}")
    assert not offenders, f"네트워크·프로세스 모듈을 가져온다: {offenders}"


def test_동적_실행을_하지_않는다() -> None:
    offenders: list[str] = []
    for path, tree in _modules():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if isinstance(function, ast.Name) and function.id in FORBIDDEN_CALLS:
                offenders.append(f"{path.name}:{node.lineno} {function.id}")
            if (
                isinstance(function, ast.Attribute)
                and isinstance(function.value, ast.Name)
                and function.value.id == "os"
                and function.attr in FORBIDDEN_OS_ATTRIBUTES
            ):
                offenders.append(f"{path.name}:{node.lineno} os.{function.attr}")
    assert not offenders, f"동적 실행 또는 프로세스 생성이 있다: {offenders}"
