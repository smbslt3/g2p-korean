"""공식 한국어 표기를 확인한 고유 명칭과 보류 항목을 검증한다."""

import pytest

from g2p_ko import G2P
from g2p_ko.english.conventional import CONVENTIONAL_READINGS


@pytest.mark.parametrize("source,expected", [
    ("OPEC", "오펙"), ("BRICS", "브릭스"), ("Interpol", "인터폴"),
    ("TOPIK", "토픽"), ("IELTS", "아이엘츠"), ("Bluetooth", "블루투스"),
    ("LEGO", "레고"), ("Google", "구글"), ("YouTube", "유튜브"),
    ("Netflix", "넷플릭스"), ("TikTok", "틱톡"), ("Instagram", "인스타그램"),
    ("Spotify", "스포티파이"), ("Airbnb", "에어비앤비"), ("adidas", "아디다스"),
    ("Nintendo", "닌텐도"), ("Microsoft", "마이크로소프트"),
    ("OpenAI", "오픈에이아이"), ("Intel", "인텔"),
    ("NAVER", "네이버"), ("NVIDIA", "엔비디아"), ("Adobe", "어도비"),
    ("Kakao", "카카오"), ("Coupang", "쿠팡"),
    ("UN", "유엔"), ("FIFA", "피파"),
])
def test_reviewed_name_readings(source: str, expected: str) -> None:
    g2p = G2P()
    for form in (source, source.upper(), source.lower()):
        result = g2p.convert(form)
        assert result.normalized_text == expected
        assert result.surface_pronunciation == g2p(expected)
        assert result.complete


@pytest.mark.parametrize("source", ["WHO", "EU", "UEFA", "CERN", "ISO", "GIF", "GUI", "SQL", "NIKE", "WIFI"])
def test_ambiguous_or_unverified_exceptions_are_not_added(source: str) -> None:
    assert source not in CONVENTIONAL_READINGS


def test_new_names_still_spell_inside_identifiers_and_addresses() -> None:
    g2p = G2P()
    result = g2p.convert("https://google.com?q=OpenAI")
    assert result.normalized_text == "에이치티티피에스://지오오지엘이.씨오엠?큐=오피이엔에이아이"
    assert g2p.convert("GoogleCloud").normalized_text == "지오오지엘이씨엘오유디"
    assert g2p.convert("OpenAI_API").normalized_text == "오피이엔에이아이_에이피아이"
