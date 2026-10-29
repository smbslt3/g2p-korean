"""기존 일곱 장벽과 추가 세 역할·이형태 검사를 고정 기대대로 확인한다."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import sys
import unicodedata

import g2p_ko.analyzer as analyzer_module
import g2p_ko.korean.engine as engine
from g2p_ko.model import AnalysisToken, Handler, OutputSegment, SourceSpan
from g2p_ko.reading_conditions import _MappedReadingBoundary, ReadingBoundary, prepare_reading_boundaries
from g2p_ko.unicode import normalize_nfc


def token(form, tag, start, parts=(), spans=()):
    return AnalysisToken(form, tag, start, start+len(form), parts, spans)


def run(text, tokens, *, offsets=(), segments=None, requests=None):
    """실제 생성자에 독을 넣고 제공 분석의 원문 일치도도 확인한다."""
    class ProvidedAnalyzer:
        def analyze(self, given):
            assert given == text
            return tokens
    segments = segments or (OutputSegment(text, (SourceSpan.from_source(text, 0, len(text)),),
                                          Handler.KOREAN, "추가 제공 분석"),)
    requests = requests or tuple(_MappedReadingBoundary(o, o, o, "ordinary_liaison") for o in offsets)
    with patch.object(analyzer_module, "_create_kiwi", side_effect=AssertionError("실제 Kiwi 생성 금지")), \
         patch.object(engine, "KiwiAnalyzer", ProvidedAnalyzer):
        result = engine.pronounce(segments, reading_conditions=requests)
    return result


def check_split_right():
    text = "밭 이다"
    result = run(text, (token("밭", "NNG", 0), token("이", "VCP", 2), token("다", "EF", 3)), offsets=(2,))
    assert result.text == "바 치다"
    assert result.condition_executions[0].rule_ids == ("ko.palatalization",)
    return result


def check_adapter_fused_tail():
    text = "갔 음"
    raw = (("가", "VV", 0, 1), ("았", "EP", 0, 1), ("음", "ETN", 2, 1))
    class RawAnalyzer:
        def tokenize(self, given, **kwargs):
            assert given == text
            return tuple(SimpleNamespace(form=f, tag=t, start=s, len=n) for f, t, s, n in raw)
    with patch.object(analyzer_module, "_create_kiwi", side_effect=AssertionError("실제 Kiwi 생성 금지")), \
         patch.object(analyzer_module, "_get_kiwi", return_value=RawAnalyzer()):
        tokens = analyzer_module.KiwiAnalyzer().analyze_components(text)
    assert tokens[0].morpheme_spans == ((0, 1), (0, 1))
    result = run(text, tokens, offsets=(2,))
    assert result.text == "가 씀"
    assert result.condition_executions[0].rule_ids == ("ko.liaison.single",)
    return result


def check_nfd_source_edges():
    text = "밭 이"
    raw = unicodedata.normalize("NFD", text)
    normalized = normalize_nfc(raw)
    raw_offset = len(unicodedata.normalize("NFD", "밭 "))
    requests = prepare_reading_boundaries(normalized, (ReadingBoundary(raw_offset, "ordinary_liaison"),))
    segments = (OutputSegment(text, normalized.character_spans, Handler.KOREAN, "NFD 원문"),)
    result = run(text, (token("밭", "NNG", 0), token("이", "JKS", 2)),
                 segments=segments, requests=requests)
    assert result.text == "바 치"
    entry, = result.condition_executions
    assert (entry.source_offset, entry.nfc_offset, entry.output_offset) == (raw_offset, 2, 2)
    for rewrite in result.rewrites:
        assert all(raw[span.start:span.end] == span.surface for span in rewrite.source_spans)
    return result


def check_h_particle_not_inherited():
    text = "히읗 이"
    result = run(text, (token("히읗", "NNG", 0), token("이", "JKS", 3)), offsets=(3,))
    assert result.text == "히읃 이"
    entry, = result.condition_executions
    assert entry.status == "unknown" and entry.reason == "letter_name_relation_not_frozen"
    assert entry.sound_effect == "unchanged" and entry.rule_ids == ()
    assert any(row.rule_id == "ko.coda.9" for row in result.rewrites)
    return result


def check_later_particle_not_pulled_forward():
    text = "옷 아이는"
    result = run(text, (token("옷", "NNG", 0), token("아이는", "NNG+JX", 2,
                 (("아이", "NNG"), ("는", "JX")))), offsets=(2,))
    assert result.text == "오 다이는"
    entry, = result.condition_executions
    assert entry.rule_ids == ("ko.liaison.lexical",)
    return result


def check_source_attachment_chain():
    text = "먹 었 음"
    result = run(text, (token("먹", "VV", 0), token("었", "EP", 2), token("음", "ETN", 4)), offsets=(2, 4))
    assert result.text == "머 거 씀"
    assert all(entry.applicability == "eligible" and entry.rule_ids == ("ko.liaison.single",)
               for entry in result.condition_executions)
    assert len([row for row in result.rewrites if row.rule_id == "ko.liaison.single"]) == 2
    return result


def check_source_identity():
    text, original = "옷 을", "꽃 을"
    segments = (OutputSegment(text, (SourceSpan.from_source(original, 0, len(original)),), Handler.KOREAN, "원문 불일치"),)
    result = run(text, (token("옷", "NNG", 0), token("을", "JKO", 2)), offsets=(2,), segments=segments)
    assert result.text == "옫 을"
    entry, = result.condition_executions
    assert entry.status == "unknown" and entry.reason == "whole_source_ownership_unresolved"
    assert entry.sound_effect == "unchanged" and entry.rule_ids == ()
    assert any(row.rule_id == "ko.coda.9" for row in result.rewrites)
    return result


def check_canonical_ending_allomorph_adapter():
    """관측된 아/EF 범위에 canonical 어/EF가 대응하는 일반 이형태다."""
    text = "많 아"
    raw = (("많", "VA", 0, 1), ("어", "EF", 2, 1))
    class RawAnalyzer:
        def tokenize(self, given, **kwargs):
            assert given == text
            return tuple(SimpleNamespace(form=f, tag=t, start=s, len=n) for f, t, s, n in raw)
    with patch.object(analyzer_module, "_create_kiwi", side_effect=AssertionError("실제 Kiwi 생성 금지")), \
         patch.object(analyzer_module, "_get_kiwi", return_value=RawAnalyzer()):
        tokens = analyzer_module.KiwiAnalyzer().analyze_components(text)
    assert tokens[1].form == "아" and tokens[1].morphemes == (("어", "EF"),)
    assert tokens[1].morpheme_spans == ((2, 3),)
    result = run(text, tokens, offsets=(1,))
    assert result.text == "마 나"
    entry, = result.condition_executions
    assert (entry.status, entry.applicability, entry.sound_effect) == ("selected", "eligible", "changed")
    assert entry.rule_ids == ("ko.hieuh.vowel",)
    return result


def check_lexical_xr_suffix_tag_conflict():
    """뒤 접미사 정체성 충돌은 연음의 미확정 근거로 남긴다."""
    text = "옷 어지간히"
    tokens = (token("옷", "NNG", 0), token("어지간히", "XR+XSM", 2,
              (("어지간", "XR"), ("히", "ZZ"))))
    result = run(text, tokens, offsets=(2,))
    entry, = result.condition_executions
    assert (entry.status, entry.applicability) == ("unknown", "unknown")
    assert not any(row.rule_id == "ko.liaison.lexical" for row in result.rewrites)
    return result


def check_lexical_xr_ending_tag_conflict():
    """융합 어미 태그 충돌을 규범상 비적격으로 확정하지 않는다."""
    text = "옷 우아해"
    tokens = (token("옷", "NNG", 0), token("우아해", "XR+XSA-R+EF", 2,
              (("우아", "XR"), ("하", "XSA-R"), ("어", "EC"))))
    result = run(text, tokens, offsets=(2,))
    entry, = result.condition_executions
    assert (entry.status, entry.applicability) == ("unknown", "unknown")
    assert not any(row.rule_id == "ko.liaison.lexical" for row in result.rewrites)
    return result


CHECKS = (check_split_right, check_adapter_fused_tail, check_nfd_source_edges,
          check_h_particle_not_inherited, check_later_particle_not_pulled_forward,
          check_source_attachment_chain, check_source_identity,
          check_canonical_ending_allomorph_adapter, check_lexical_xr_suffix_tag_conflict,
          check_lexical_xr_ending_tag_conflict)


def test_frozen_guards():
    for check in CHECKS:
        check()


if __name__ == "__main__":
    target = Path(sys.argv[1])
    assert not target.exists(), "기존 실행은 덮어쓰지 않습니다."
    rows = []
    for check in CHECKS:
        try:
            result = check()
            rows.append({"id": check.__name__, "passed": True, "output": result.text,
                         "executions": [entry.to_dict() for entry in result.condition_executions]})
        except Exception as error:
            rows.append({"id": check.__name__, "passed": False, "error": repr(error)})
    target.write_text(json.dumps({"cases": len(rows), "passed": sum(row["passed"] for row in rows),
                                 "records": rows}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False))
