"""텍스트 유틸리티 테스트."""

from __future__ import annotations

from src.text import digest, normalize, sentences, visible_length


def test_문장_부호로_나눈_뒤에_서식을_지운다() -> None:
    """지우기를 먼저 하면 마침표가 사라져 한 줄이 통째로 한 덩어리가 된다."""
    text = "체현은 소유가 아니라 존재 방식이다. 몸은 관점의 위치이며 선택된 적이 없다."
    assert len(sentences(text)) == 2


def test_목록_기호와_강조는_문장에서_제외된다() -> None:
    plain = sentences("체현의 최소 요건을 재료와 무관하게 진술해야 한다.")
    decorated = sentences("1. **체현의 최소 요건**을 재료와 무관하게 진술해야 한다.")
    assert plain == decorated


def test_짧은_조각은_세지_않는다() -> None:
    assert sentences("짧다. 또 짧다.") == []


def test_공백을_뺀_글자_수를_센다() -> None:
    assert visible_length(" 인간의  조건 \n") == 5


def test_서식_차이는_해시를_바꾸지_않는다() -> None:
    assert digest("가\n\n\n나") == digest("가  \n\n나")
    assert digest("가", "나") != digest("가나")


def test_정규화는_줄바꿈과_꼬리_공백을_정리한다() -> None:
    assert normalize("가\r\n나   \n\n\n\n다\n") == "가\n나\n\n다"
