"""출력 전에 고정한 활용·정렬·소유·불일치 입력의 장단 계약을 확인한다."""
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from g2p_ko import G2P
from g2p_ko.model import AnalysisToken
from g2p_ko.vowel_length import build_vowel_length

CASES = json.loads((Path(__file__).parent / "fixtures/round12_length_independent.json").read_text(encoding="utf-8"))

@pytest.fixture(scope="module")
def converter():
    return G2P()

@pytest.mark.parametrize("case", CASES["parent"], ids=lambda case: case["id"])
def test_independent_public_length_contract(converter, case):
    result = converter.convert_with_vowel_length(case["input"])
    decisions = result.decisions
    if "value" in case:
        matched = [d for d in decisions if d.lemma == case["lemma"]]
        assert matched and matched[0].status == "supported" and matched[0].value == case["value"]
        chosen = matched[0]
        for field in ("nucleus_source_span", "owner_source_span"):
            if field in case:
                span = getattr(chosen, field)
                assert [span.start, span.end] == case[field]
        if "output_nucleus_span" in case:
            assert list(chosen.output_nucleus_syllable_span) == case["output_nucleus_span"]
    elif "values" in case:
        assert [d.value for d in decisions] == case["values"]
        assert [[d.nucleus_source_span.start, d.nucleus_source_span.end] for d in decisions] == case["nucleus_source_spans"]
        assert [[d.owner_source_span.start, d.owner_source_span.end] for d in decisions] == case["owner_source_spans"]
    elif "required_supported_root" in case:
        expected = case["required_supported_root"]
        assert any(d.status == "supported" and d.lemma == expected["lemma"] and d.value == expected["value"] for d in decisions)
        assert not any(d.status == "supported" and d.nucleus_source_span.start in case["forbid_supported_root_at"] for d in decisions)
    else:
        assert not any(d.status == "supported" for d in decisions)
    assert result.auxiliary_analysis_calls <= 1
    json.dumps(result.to_dict(), ensure_ascii=False)

@pytest.mark.parametrize("case", CASES["supplied"] + CASES["structural"], ids=lambda case: case["id"])
def test_independent_owned_analysis_contract(converter, case):
    text = case["text"]
    aligned = converter.convert_with_alignment(text)
    parts = tuple(tuple(part) for part in case["parts"])
    token = AnalysisToken(text, "+".join(tag for _, tag in parts), 0, len(text), parts)
    with patch("g2p_ko.vowel_length.KiwiAnalyzer") as provider:
        provider.return_value.analyze.return_value = (token,)
        decision, = build_vowel_length(aligned).decisions
    assert decision.value == case["value"]
    assert (decision.status == "supported") == (case["value"] != "unknown")
