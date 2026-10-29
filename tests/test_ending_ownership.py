# SPDX-License-Identifier: MIT
"""제공 형태 분석만으로 어미 받침 소유와 기존 경음화의 대조를 검증한다."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

import g2p_ko.analyzer as analyzer_module
import g2p_ko.korean.engine as engine
from g2p_ko.analyzer import KiwiAnalyzer
from g2p_ko.korean.ending_ownership import ending_coda_owner
from g2p_ko.merge import _TextSegment
from g2p_ko.model import AnalysisToken, Boundary, Handler, OutputSegment, SourceSpan


STEMS = (("돌보", "돌볼"), ("설계하", "설계할"), ("열거하", "열거할"),
         ("몰두하", "몰두할"), ("발견하", "발견할"))


@pytest.fixture(autouse=True)
def no_real_kiwi():
    # 실제 분석기는 이 작성 단계의 허용 범위 밖이다.
    with patch.object(analyzer_module, "_create_kiwi", side_effect=AssertionError("실제 Kiwi 초기화 금지")):
        yield


def token(form, tag, start, morphemes=()):
    return AnalysisToken(form, tag, start, start + len(form), morphemes)


def segment(text, *, source=None, source_start=0, before=Boundary.WORD, after=Boundary.WORD):
    source = text if source is None else source
    return OutputSegment(text, (SourceSpan.from_source(source, source_start, source_start + len(text)),),
                         Handler.KOREAN, "제공 분석 검사", boundary_before=before, boundary_after=after)


def run(text, tokens, *, pauses=(), segments=None):
    class ProvidedAnalyzer:
        def analyze(self, given):
            assert given == text
            return tokens

    with patch.object(engine, "KiwiAnalyzer", ProvidedAnalyzer):
        result = engine.pronounce(segments or (segment(text),), pause_boundaries=pauses)
    assert not result.diagnostics
    return result


def adapter_tokens(text, raw):
    class ProvidedRawAnalyzer:
        def tokenize(self, given, **kwargs):
            assert given == text
            return tuple(SimpleNamespace(form=form, tag=tag, start=start, len=length)
                         for form, tag, start, length in raw)

    with patch.object(analyzer_module, "_get_kiwi", return_value=ProvidedRawAnalyzer()):
        return KiwiAnalyzer().analyze(text)


def predicate_tokens(stem, surface, variant, *, ending="ㄹ", ending_tag="ETM", tail="", noun="", space=""):
    pred = surface + tail
    text = pred + space + noun
    if variant in {"overlap", "zero_overlap"}:
        raw = [(stem, "VV", 0, len(stem)),
               (ending, ending_tag, len(surface) - 1, 0 if variant == "zero_overlap" else 1 + len(tail))]
        if noun:
            raw.append((noun, "NNB", len(pred) + len(space), len(noun)))
        return adapter_tokens(text, raw)
    if variant == "split":
        prefix = surface[:-1]
        pieces = (token(prefix, "VV", 0, ((stem[:-1], "VV"),)),) if prefix else ()
        pieces += (token(surface[-1] + tail, "VV+" + ending_tag, len(prefix),
                         ((stem[-1], "VV"), (ending, ending_tag))),)
    elif variant == "whole_with_noun":
        assert not space and noun
        return (token(text, "VV+" + ending_tag + "+NNB", 0,
                      ((stem, "VV"), (ending, ending_tag), (noun, "NNB"))),)
    else:
        pieces = (token(pred, "VV+" + ending_tag, 0, ((stem, "VV"), (ending, ending_tag))),)
    if noun:
        pieces += (token(noun, "NNB", len(pred) + len(space), ((noun, "NNB"),)),)
    return pieces


@pytest.mark.parametrize("stem,surface", STEMS)
@pytest.mark.parametrize("variant", ["whole", "split", "overlap", "zero_overlap"])
@pytest.mark.parametrize("space", ["", " ", "  "])
def test_stem_internal_liquid_and_actual_modifier_coda_are_distinct(stem, surface, variant, space):
    text = surface + space + "수"
    tokens = predicate_tokens(stem, surface, variant, noun="수", space=space)
    result = run(text, tokens)
    assert result.text == surface + space + "쑤"
    tense = [row for row in result.rewrites if row.rule_id in {"ko.ending.tensing.27", "ko.modifier.tensing.27"}]
    assert len(tense) == 1
    assert tense[0].before == surface[-1] + space + "수"
    assert tense[0].after == surface[-1] + space + "쑤"


@pytest.mark.parametrize("stem,surface", STEMS)
def test_whole_predicate_and_noun_with_original_forms(stem, surface):
    text = surface + "수"
    result = run(text, predicate_tokens(stem, surface, "whole_with_noun", noun="수"))
    assert result.text == surface + "쑤"


@pytest.mark.parametrize("stem,surface", STEMS[:3])
@pytest.mark.parametrize("tail,tag,expected_tail", [("수록", "EC", "쑤록"), ("게", "EF", "께"), ("걸", "EF", "껄")])
@pytest.mark.parametrize("variant", ["whole", "split", "overlap"])
def test_true_ending_internal_liquid_remains_productive(stem, surface, tail, tag, expected_tail, variant):
    text = surface + tail
    result = run(text, predicate_tokens(stem, surface, variant, ending="ㄹ" + tail,
                                       ending_tag=tag, tail=tail))
    assert result.text == surface + expected_tail
    rows = [row for row in result.rewrites if row.rule_id == "ko.ending.tensing.27"]
    assert len(rows) == 1
    assert rows[0].before == surface[-1] + tail[0]


@pytest.mark.parametrize("ending", ["ㄹ수록", "ᆯ수록", "을수록"])
def test_compatibility_trailing_jamo_and_optional_eu_use_surface_coda(ending):
    tokens = (token("돌볼수록", "VV+EC", 0, (("돌보", "VV"), (ending, "EC"))),)
    assert run("돌볼수록", tokens).text == "돌볼쑤록"


@pytest.mark.parametrize("variant", ["whole", "split"])
@pytest.mark.parametrize("space", ["", " "])
def test_eu_ending_and_earlier_liaison_are_preserved(variant, space):
    text = "먹을" + space + "수"
    if variant == "whole":
        pieces = (token("먹을", "VV+ETM", 0, (("먹", "VV"), ("을", "ETM"))),)
    else:
        pieces = (token("먹", "VV", 0), token("을", "ETM", 1, (("을", "ETM"),)))
    result = run(text, pieces + (token("수", "NNB", 2 + len(space)),))
    assert result.text == "머글" + space + "쑤"
    assert "ko.liaison.single" in {row.rule_id for row in result.rewrites}


@pytest.mark.parametrize("noun,tag,expected", [("수", "NNB", "쑤"), ("도구", "NNG", "또구"),
                                            ("사람", "NNG", "싸람"), ("집", "NNG", "찝")])
@pytest.mark.parametrize("space", ["", " "])
def test_independent_and_bound_nouns_keep_modifier_positive(noun, tag, expected, space):
    text = "돌볼" + space + noun
    pieces = (token("돌볼", "VV+ETM", 0, (("돌보", "VV"), ("ㄹ", "ETM"))),
              token(noun, tag, 2 + len(space)))
    assert run(text, pieces).text == "돌볼" + space + expected


@pytest.mark.parametrize("stem,surface", STEMS)
@pytest.mark.parametrize("ending", ["고", "다", "면"])
def test_adding_ending_metadata_outside_stem_internal_codas_cannot_create_tensing(stem, surface, ending):
    text = stem + ending
    baseline = run(text, (token(text, "VV", 0, ((text, "VV"),)),))
    candidate = run(text, (token(text, "VV+EC", 0, ((stem, "VV"), (ending, "EC"))),))
    assert candidate.text == baseline.text
    assert not any(row.rule_id in {"ko.ending.tensing.27", "ko.modifier.tensing.27"} for row in candidate.rewrites)


def test_same_surface_distinguishes_stem_rieul_from_ending_rieul():
    stem_liquid = (token("알게", "VV+EC", 0, (("알", "VV"), ("게", "EC"))),)
    ending_liquid = (token("알게", "VV+EF", 0, (("알", "VV"), ("ㄹ게", "EF"))),)
    assert run("알게", stem_liquid).text == "알게"
    assert run("알게", ending_liquid).text == "알께"


@pytest.mark.parametrize("text,tag,expected", [("갈수록", "MAG", "갈쑤록"), ("할밖에", "MAG", "할빠께"),
                                            ("날짐승", "NNG", "날찜승"), ("할수록", "EC", "할쑤록"),
                                            ("할게", "EF", "할께"), ("할걸", "EF", "할껄")])
def test_existing_lexicalized_and_explicit_ending_spans_stay_positive(text, tag, expected):
    result = run(text, (token(text, tag, 0),))
    assert result.text == expected
    assert "ko.ending.tensing.27" in {row.rule_id for row in result.rewrites}


@pytest.mark.parametrize("text,tag", [("돌보", "VV"), ("돌볼", "NNG"), ("돌보고", "VV+EC"),
                                   ("알게", "VV+EC"), ("돌볼수록", "VV+EC")])
def test_tag_only_merged_tokens_do_not_prove_arbitrary_internal_ending(text, tag):
    result = run(text, (token(text, tag, 0),))
    assert not any(row.rule_id == "ko.ending.tensing.27" for row in result.rewrites)


@pytest.mark.parametrize("space", ["", " "])
def test_legacy_combined_etm_compatibility_is_bounded_to_final_coda(space):
    text = "돌볼" + space + "수"
    result = run(text, (token("돌볼", "VV+ETM", 0), token("수", "NNB", 2 + len(space))))
    assert result.text == "돌볼" + space + "쑤"


@pytest.mark.parametrize("space", ["", " ", "  "])
def test_explicit_pause_blocks_actual_modifier_and_keeps_stem_unchanged(space):
    text = "돌볼" + space + "수"
    pieces = predicate_tokens("돌보", "돌볼", "overlap", noun="수", space=space)
    for pause in range(2, 3 + len(space)):
        if pause <= len(text) - 1:
            result = run(text, pieces, pauses=(pause,))
            assert result.text == text
            assert not any(row.rule_id in {"ko.ending.tensing.27", "ko.modifier.tensing.27"} for row in result.rewrites)


@pytest.mark.parametrize("tail", ["수록", "게", "걸"])
def test_explicit_pause_blocks_true_ending_internal_boundary(tail):
    text = "돌볼" + tail
    pieces = predicate_tokens("돌보", "돌볼", "whole", ending="ㄹ" + tail,
                              ending_tag="EC", tail=tail)
    assert run(text, pieces, pauses=(2,)).text == text


def test_hard_boundary_blocks_modifier_and_analyzer_island_offsets_are_local():
    text = "돌볼 수"
    segments = (segment("돌볼 ", source=text, after=Boundary.HARD),
                segment("수", source=text, source_start=3, before=Boundary.HARD))

    class ProvidedIslands:
        def analyze(self, given):
            assert given == "돌볼 "
            return (token("돌볼", "VV+ETM", 0, (("돌보", "VV"), ("ㄹ", "ETM"))),)

    with patch.object(engine, "KiwiAnalyzer", ProvidedIslands):
        result = engine.pronounce(segments)
    assert not result.diagnostics
    assert result.text == text
    assert not any(row.rule_id in {"ko.ending.tensing.27", "ko.modifier.tensing.27"} for row in result.rewrites)


@pytest.mark.parametrize("tail", ["수록", "게", "걸"])
def test_hard_boundary_blocks_actual_ending_internal_boundary(tail):
    text = "돌볼" + tail
    segments = (segment("돌볼", source=text, after=Boundary.HARD),
                segment(tail, source=text, source_start=2, before=Boundary.HARD))

    class ProvidedIslands:
        def analyze(self, given):
            assert given == "돌볼"
            return (token("돌볼", "VV+ETM", 0, (("돌보", "VV"), ("ㄹ", "ETM"))),)

    with patch.object(engine, "KiwiAnalyzer", ProvidedIslands):
        result = engine.pronounce(segments)
    assert not result.diagnostics
    assert result.text == text
    assert not any(row.rule_id == "ko.ending.tensing.27" for row in result.rewrites)


def test_noninitial_hard_island_rebases_owned_coda_from_local_coordinates():
    text = "나 돌볼 수"
    segments = (segment("나 ", source=text, after=Boundary.HARD),
                segment("돌볼 수", source=text, source_start=2, before=Boundary.HARD))

    class ProvidedIslands:
        def analyze(self, given):
            assert given == "돌볼 수"
            return predicate_tokens("돌보", "돌볼", "whole", noun="수", space=" ")

    with patch.object(engine, "KiwiAnalyzer", ProvidedIslands):
        result = engine.pronounce(segments)
    assert not result.diagnostics
    assert result.text == "나 돌볼 쑤"
    row, = [row for row in result.rewrites if row.rule_id == "ko.modifier.tensing.27"]
    assert [(span.start, span.end) for span in row.source_spans] == [(3, 4), (4, 5), (5, 6)]


def test_ending_before_following_particle_keeps_its_actual_coda():
    text = "돌볼게요"
    pieces = (token(text, "VV+EF+JX", 0, (("돌보", "VV"), ("ㄹ게", "EF"), ("요", "JX"))),)
    assert run(text, pieces).text == "돌볼께요"


def test_nonzero_source_offsets_and_rewrite_window_remain_exact():
    text = "돌볼 수"
    source = "기록:" + text + ":끝"
    pieces = predicate_tokens("돌보", "돌볼", "overlap", noun="수", space=" ")
    result = run(text, pieces, segments=(segment(text, source=source, source_start=3),))
    row, = [row for row in result.rewrites if row.rule_id == "ko.modifier.tensing.27"]
    assert (row.before, row.after) == ("볼 수", "볼 쑤")
    assert [(span.start, span.end, span.surface) for span in row.source_spans] == [(4, 5, "볼"), (5, 6, " "), (6, 7, "수")]
    assert all(source[span.start:span.end] == span.surface and span.source_length == len(source)
               for row in result.rewrites for span in row.source_spans)


def test_normalized_prefix_and_both_trace_modes_use_same_ownership():
    text = "나 돌볼 수"
    pieces = (token("나", "NP", 0), token("돌볼", "VV+ETM", 2, (("돌보", "VV"), ("ㄹ", "ETM"))),
              token("수", "NNB", 5))
    detailed = run(text, pieces)

    class ProvidedAnalyzer:
        def analyze(self, given):
            assert given == text
            return pieces

    plain_segment = _TextSegment(text, Handler.KOREAN, "제공 분석 검사")
    with patch.object(engine, "KiwiAnalyzer", ProvidedAnalyzer):
        plain = engine.pronounce_text((plain_segment,))
    assert detailed.text == plain == "나 돌볼 쑤"
    row, = [row for row in detailed.rewrites if row.rule_id == "ko.modifier.tensing.27"]
    assert min(span.start for span in row.source_spans) == 3
    assert max(span.end for span in row.source_spans) == 6


def test_owner_indices_are_source_coordinates_not_lemma_lengths():
    item = token("돌볼수록", "VV+EC", 7, (("돌보", "VV"), ("ㄹ수록", "EC")))
    assert ending_coda_owner(item, 7) is None
    assert ending_coda_owner(item, 8).form == "ㄹ수록"


def test_eu_ending_internal_and_separate_ending_tail():
    text = "먹을수록"
    pieces = (token("먹", "VV", 0), token("을수록", "EC", 1, (("을수록", "EC"),)))
    assert run(text, pieces).text == "머글쑤록"
    split = (token("돌볼", "VV+ETM", 0, (("돌보", "VV"), ("ㄹ", "ETM"))), token("수록", "EC", 2))
    assert run("돌볼수록", split).text == "돌볼쑤록"
