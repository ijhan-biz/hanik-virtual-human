"""공용 텍스트 유틸리티.

파서와 정직성 규칙이 같은 방식으로 텍스트를 정규화하고 해시해야 하므로,
그 정의를 한곳에 모아 둔다.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

_TRAILING_SPACE = re.compile(r"[ \t]+$", re.MULTILINE)
_BLANK_RUN = re.compile(r"\n{3,}")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。])\s+|\n+")
_LIST_PREFIX = re.compile(r"^\s*(?:[-•]|\d+[.)])\s*")
_INLINE_DECORATION = re.compile(r"[*_`#>]+")


def normalize(text: str) -> str:
    """줄바꿈과 공백을 정규화한다. 서식 차이가 해시를 바꾸지 않도록 한다."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _TRAILING_SPACE.sub("", text)
    text = _BLANK_RUN.sub("\n\n", text)
    return text.strip()


def digest(*parts: str) -> str:
    """정규화한 조각들의 SHA-256 요약을 반환한다."""
    hasher = hashlib.sha256()
    for part in parts:
        hasher.update(normalize(part).encode("utf-8"))
        hasher.update(b"\x00")
    return hasher.hexdigest()


def visible_length(text: str) -> int:
    """공백을 뺀 글자 수. 한국어 분량의 척도로 쓴다."""
    return len("".join(text.split()))


def sentences(text: str) -> list[str]:
    """중복 검사를 위해 문장 단위로 자른다.

    문장 부호를 지우기 전에 먼저 나눈다. 순서를 바꾸면 마침표가 사라진 뒤라
    한 줄에 이어 쓴 문장들이 통째로 한 덩어리가 된다.

    너무 짧아 우연히 겹칠 수 있는 조각은 버린다. 짧은 문장을 반복해 분량을 채우는
    경우는 이 검사가 잡지 못한다.
    """
    found = []
    for chunk in _SENTENCE_SPLIT.split(normalize(text)):
        cleaned = _INLINE_DECORATION.sub("", _LIST_PREFIX.sub("", chunk))
        collapsed = " ".join(cleaned.split())
        if visible_length(collapsed) >= 12:
            found.append(collapsed)
    return found
