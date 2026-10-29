"""숫자 전처리를 끝낸 입력과 미등록 영문 철자 읽기 계약을 검증한다."""

import pytest

from g2p_ko import G2P, InputValidationError, KoreanTTSNormalizer


@pytest.mark.parametrize(
    ("source", "spelled"),
    [
        ("AI ai Ai", "에이아이 에이아이 에이아이"),
        ("hello", "에이치이엘엘오"),
        ("GPT삼", "지피티삼"),
        ("A_B.C+D-E/F", "에이_비.씨+디-이/에프"),
        ("don't", "디오엔'티"),
        ("ray’s", "알에이와이’에스"),
        ("https://a.b", "에이치티티피에스://에이.비"),
        ("a@b.c", "에이@비.씨"),
        (r"C:\A\b", r"씨:\에이\비"),
        ("`ABC`", "`에이비씨`"),
        ("ＡｂＣ", "에이비씨"),
        ("𝐀𝑏ℂ", "에이비씨"),
        ("ﬃ", "에프에프아이"),
    ],
)
def test_unknown_english_shapes_use_letter_names(source: str, spelled: str) -> None:
    g2p = G2P()
    for normalize in (True, False):
        result = g2p.convert(source, normalize=normalize)
        assert result.normalized_text == spelled
        assert result.surface_pronunciation == g2p(source, normalize=normalize)
        assert result.complete
        assert not result.diagnostics.pronunciation.diagnostics
        assert len(result.normalized_text) == len(result.surface_pronunciation)


@pytest.mark.parametrize("source", ["16%", "GPT4", "3개", "４２", "²Ⅳ", "①", "٤٢"])
def test_remaining_numeric_input_is_diagnosed(source: str) -> None:
    result = G2P().convert(source)
    assert not result.complete
    diagnostics = result.diagnostics.pronunciation.diagnostics
    assert {item.code for item in diagnostics} == {"unconverted_numeric"}
    for diagnostic in diagnostics:
        for span in diagnostic.source_spans:
            assert span.surface == source[span.start:span.end]


def test_g2p_never_calls_number_or_english_normalizer(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*args, **kwargs):
        raise AssertionError("G2P가 앞단 정규화기를 호출했습니다.")

    monkeypatch.setattr(KoreanTTSNormalizer, "__init__", reject)
    g2p = G2P()
    assert g2p("십육 퍼센트") == "심뉵 퍼센트"
    assert g2p.convert("NASA").normalized_text == "나사"


def test_input_budget_allows_spelling_expansion_but_limits_raw_input() -> None:
    g2p = G2P(max_length=1)
    assert g2p.convert("W").normalized_text == "더블유"
    assert g2p("W") == "더브류"
    assert g2p.convert("W").complete
    for operation in (g2p, g2p.convert):
        with pytest.raises(InputValidationError, match="최대 길이 1"):
            operation("WW")
