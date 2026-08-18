"""Hanik 루프 패키지.

이 패키지는 네트워크를 쓰지 않고, 생성한 텍스트를 실행하지 않는다.
두 성질 모두 tests/test_safety.py의 AST 검사로 강제된다.
"""

from __future__ import annotations

__all__ = ["document", "objections", "integrity", "state", "reporting", "text"]
