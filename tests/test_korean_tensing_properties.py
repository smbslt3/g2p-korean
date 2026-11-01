"""한자어 속성과 고유어 합성 경음화가 조사·파생형에 합성되는지 검증한다."""

from unittest.mock import patch

import pytest

from g2p_ko import G2P
from g2p_ko.analyzer import KiwiAnalyzer
from g2p_ko.korean.engine import _build_units, pronounce
from g2p_ko.korean.morphology import _Annotation, _apply_derived_seong_tensing, _apply_derived_kwon_tensing
from g2p_ko.korean.owned_lexical import _token_aligned_nng_component_owner, owned_root_matches
from g2p_ko.korean.semantic_policy import SenseSelection
import g2p_ko.korean.engine as engine_module
from g2p_ko.model import AnalysisToken, Boundary, Handler, OutputSegment, SourceSpan


def _segment(source, start=0, end=None, *, hard=False):
    end = len(source) if end is None else end
    boundaries = {"boundary_before": Boundary.HARD, "boundary_after": Boundary.HARD} if hard else {}
    return OutputSegment(source[start:end], (SourceSpan.from_source(source, start, end),),
                         Handler.KOREAN, "test", **boundaries)


@pytest.mark.parametrize(("base", "tail", "tag", "expected", "rule"), [
    ("출동", "", "", "출똥", "ko.sino.tensing.26"),
    ("출동", "이", "JKS", "출똥이", "ko.sino.tensing.26"),
    ("출동", "은", "JX", "출똥은", "ko.sino.tensing.26"),
    ("출동", "만", "JX", "출똥만", "ko.sino.tensing.26"),
    ("손길", "", "", "손낄", "ko.lexical.tensing"),
    ("손길", "이", "JKS", "손끼리", "ko.lexical.tensing"),
    ("손길", "은", "JX", "손끼른", "ko.lexical.tensing"),
    ("손길", "만", "JX", "손낄만", "ko.lexical.tensing"),
    ("손길", "도", "JX", "손낄도", "ko.lexical.tensing"),
])
@pytest.mark.parametrize("analysis", ["whole", "actual"])
def test_registered_tensing_properties_compose_with_particles(base, tail, tag, expected, rule, analysis):
    # 기본형은 공식 규범·사전, 조사 결합은 일반 연음 규칙으로 기대값을 정한다.
    # https://krdict.korean.go.kr/eng/dicSearch/SearchView?ParaWordNo=15598
    # https://www.korean.go.kr/kornorms/regltn/regltnView.do?regltn_code=0002
    source = base + tail
    if analysis == "actual":
        result = G2P().convert(source)
        assert result.surface_pronunciation == expected
        assert result.complete
        return

    class CorrectAnalyzer:
        def analyze(self, text):
            assert text == source
            tokens = (AnalysisToken(base, "NNG", 0, len(base)),)
            return tokens + ((AnalysisToken(tail, tag, len(base), len(source)),) if tail else ())

    with patch.object(engine_module, "KiwiAnalyzer", CorrectAnalyzer):
        result = engine_module.pronounce((_segment(source),))
    assert result.text == expected
    assert rule in {item.rule_id for item in result.rewrites}
    assert not {"ko.lexical.verified", "ko.official.morpheme"} & {item.rule_id for item in result.rewrites}


@pytest.mark.parametrize(("source", "expected"), [
    ("출동하다", "출똥하다"), ("출동해", "출똥해"), ("출동했다", "출똥핻따"),
])
def test_sino_property_remains_available_before_verbal_derivation(source, expected):
    assert G2P()(source) == expected


@pytest.mark.parametrize("source", ["출동", "손길"])
def test_registered_tensing_respects_hard_boundaries(source):
    parts = (_segment(source, 0, 1, hard=True), _segment(source, 1, 2, hard=True))
    assert engine_module.pronounce(parts).text == "".join(engine_module.pronounce((part,)).text for part in parts)


def test_sino_property_requires_a_compatible_pos():
    # 한자어 속성의 품사 조건에 대한 합성 입력이며 실제 발음 정확도 분모와 구분한다.
    source = "출동"
    class NonNounAnalyzer:
        def analyze(self, text):
            return (AnalysisToken(text, "VV", 0, len(text)),)

    with patch.object(engine_module, "KiwiAnalyzer", NonNounAnalyzer):
        result = engine_module.pronounce((_segment(source),))
    assert "ko.sino.tensing.26" not in {item.rule_id for item in result.rewrites}


@pytest.mark.parametrize(("tail", "expected"), [("", "손낄"), ("이", "손끼리")])
def test_native_compound_keeps_valid_component_analysis(tail, expected):
    source = "손길" + tail

    class CorrectAnalyzer:
        def analyze(self, text):
            assert text == source
            tokens = (AnalysisToken("손", "NNG", 0, 1), AnalysisToken("길", "NNG", 1, 2))
            return tokens + ((AnalysisToken("이", "JKS", 2, 3),) if tail else ())

    with patch.object(engine_module, "KiwiAnalyzer", CorrectAnalyzer):
        result = engine_module.pronounce((_segment(source),))
    assert result.text == expected
    assert "ko.lexical.tensing" in {item.rule_id for item in result.rewrites}


@pytest.mark.parametrize(("base", "particle", "expected", "rule"), [
    ("출전", "", "출쩐", "ko.sino.tensing.26"),
    ("출전", "이", "출쩌니", "ko.sino.tensing.26"),
    ("갈대", "", "갈때", "ko.lexical.tensing"),
    ("갈대", "가", "갈때가", "ko.lexical.tensing"),
    ("날짐승", "", "날찜승", "ko.ending.tensing.27"),
    ("날짐승", "이", "날찜승이", "ko.ending.tensing.27"),
])
@pytest.mark.parametrize("analysis", ["whole", "actual"])
def test_related_tensing_families_reuse_their_distinct_properties(base, particle, expected, rule, analysis):
    # 표제어의 규범 발음과 조사 연음을 분리해 구성한 회귀다.
    # https://stdict.korean.go.kr/search/searchView.do?word_no=334706
    # https://stdict.korean.go.kr/search/searchView.do?word_no=390781
    # https://stdict.korean.go.kr/search/searchView.do?word_no=60042
    source = base + particle
    if analysis == "actual":
        assert G2P()(source) == expected
        return

    class CorrectAnalyzer:
        def analyze(self, text):
            assert text == source
            tokens = (AnalysisToken(base, "NNG", 0, len(base)),)
            return tokens + ((AnalysisToken(particle, "JKS", len(base), len(source)),) if particle else ())

    with patch.object(engine_module, "KiwiAnalyzer", CorrectAnalyzer):
        result = engine_module.pronounce((_segment(source),))
    assert result.text == expected
    assert rule in {item.rule_id for item in result.rewrites}
    assert not {"ko.lexical.verified", "ko.official.morpheme"} & {item.rule_id for item in result.rewrites}


@pytest.mark.parametrize(("source", "expected"), [("물들다", "물들다"), ("열다", "열다")])
def test_liquid_dental_spelling_does_not_imply_sino_tensing(source, expected):
    assert G2P()(source) == expected


def _derived_segment(text, source=None, start=0, **kwargs):
    source = text if source is None else source
    spans = tuple(SourceSpan.from_source(source, start + i, start + i + 1) for i in range(len(text)))
    return OutputSegment(text, spans, Handler.KOREAN, "cleanroom fixture", **kwargs)


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        ("다양성", "다양썽"),
        ("정체성은", "정체썽은"),
        ("필요성으로", "피료썽으로"),
        ("중요성에", "중요썽에"),
        ("주체성이", "주체썽이"),
        ("책임성은", "채김썽은"),
        ("시간성의", "시간썽에"),
        ("공간성에서", "공간썽에서"),
    ),
)
def test_analyzed_derivational_seong_is_tensed_with_ordinary_continuations(text, expected):
    tokens = KiwiAnalyzer().analyze(text)
    suffix = next(token for token in tokens if token.form == "성")
    assert suffix.tag == "XSN"
    assert G2P()(text) == expected


def test_existing_lexical_positive_remains_correct():
    assert G2P()("가능성") == "가능썽"


def test_one_rule_trace_records_the_productive_change():
    result = pronounce((_derived_segment("다양성"),))
    assert result.text == "다양썽"
    assert [rewrite.rule_id for rewrite in result.rewrites].count(
        "ko.derivational.seong_tensing"
    ) == 1


@pytest.mark.parametrize("text", ("남성", "여성", "화성", "수성", "성명", "성"))
def test_whole_noun_and_standalone_controls_do_not_trigger_suffix_rule(text):
    tokens = KiwiAnalyzer().analyze(text)
    assert not any(token.form == "성" and token.tag == "XSN" for token in tokens)
    result = pronounce((_derived_segment(text),))
    assert result.text == G2P()(text)
    assert all(rewrite.rule_id != "ko.derivational.seong_tensing" for rewrite in result.rewrites)


def test_spelling_alone_and_whitespace_do_not_create_a_suffix():
    assert G2P()("다양 성") == "다양 성"
    result = pronounce((_derived_segment("다양 성"),))
    assert result.text == "다양 성"
    assert all(rewrite.rule_id != "ko.derivational.seong_tensing" for rewrite in result.rewrites)


def test_pause_at_morpheme_boundary_blocks_new_tensing():
    assert G2P()("다양성", pause_boundaries=(2,)) == "다양성"


def test_hard_segment_boundary_blocks_new_tensing():
    text = "다양성"
    left = _derived_segment(text[:2], source=text, start=0, boundary_after=Boundary.HARD)
    right = _derived_segment(text[2:], source=text, start=2, boundary_before=Boundary.HARD)
    result = pronounce((left, right))
    assert result.text == "다양성"
    assert all(rewrite.rule_id != "ko.derivational.seong_tensing" for rewrite in result.rewrites)


@pytest.mark.parametrize(
    "tokens",
    (
        (AnalysisToken("다양", "NNG", 0, 2), AnalysisToken("성", "NNG", 2, 3)),
        (AnalysisToken("다양", "VV", 0, 2), AnalysisToken("성", "XSN", 2, 3)),
        (AnalysisToken("다양", "NNG", 0, 2), AnalysisToken("성", "XSN+NNG", 2, 3)),
        (AnalysisToken("다양", "NNG", 0, 2), AnalysisToken("생", "XSN", 2, 3)),
        (AnalysisToken("다양", "NNG", 0, 1), AnalysisToken("성", "XSN", 2, 3)),
    ),
)
def test_malformed_or_contradictory_annotations_do_not_create_a_license(tokens):
    text = "다양성"
    segment = _derived_segment(text)
    units = _build_units((segment,), trace=True)
    annotation = _Annotation.from_tokens(tokens, text)
    rewrites = []

    _apply_derived_seong_tensing(units, (segment,), annotation, rewrites)

    assert "".join(unit.text for unit in units) == text
    assert rewrites == []


@pytest.mark.parametrize(("source", "expected"), [
    ('평가', '평까'),
    ('사건', '사껀'),
    ('조건', '조껀'),
    ('여건', '여껀'),
    ('관점', '관쩜'),
    ('시점', '시쩜'),
    ('초점', '초쩜'),
    ('쟁점', '쟁쩜'),
    ('수도권', '수도꿘'),
    ('증권', '증꿘'),
    ('인권', '인꿘'),
    ('주권', '주꿘'),
    ('정권', '정꿘'),
    ('채권', '채꿘'),
    ('문자', '문짜'),
    ('실밥', '실빱'),
    ('눈길', '눈낄'),
    ('열심히', '열씸히'),
    ('법률적', '범뉼쩍'),
    ('현실적', '현실쩍'),
    ('확률적', '황뉼쩍'),
    ('확률적으로', '황뉼쩌그로'),
    ('활성화', '활썽화'),
    ('활성화를 위한 업무협약', '활썽화르 뤼하 넘무혀뱍'),
])
def test_attested_tensing_root_positive(source, expected):
    assert G2P()(source) == expected


@pytest.mark.parametrize(("source", "expected"), [
    ('물건', '물건'),
    ('문장', '문장'),
    ('대리점', '대리점'),
    ('화가', '화가'),
    ('비평가', '비평가'),
    ('주주가', '주주가'),
    ('입주가', '입쭈가'),
    ('자유가', '자유가'),
    ('토대가', '토대가'),
])
def test_attested_tensing_root_control(source, expected):
    assert G2P()(source) == expected


def test_attested_tensing_root_particles_and_barriers():
    engine = G2P()
    assert engine("평가를") == "평까를"
    assert engine("평가", pause_boundaries=(1,)) == "평가"
    assert engine("평 가") == "평 가"


@pytest.mark.parametrize(("source", "expected"), [
    ("운영평가를", "우녕평까를"),
    ("자동평가를", "자동평까를"),
    ("정성평가", "정성평까"),
    ("평가점수", "평까점수"),
])
def test_internal_root_onset_survives_an_actual_nng_component_chain(source, expected):
    assert G2P()(source) == expected


def test_internal_nng_component_chain_respects_pause():
    assert G2P()("운영평가", pause_boundaries=(3,)) == "우녕평가"


@pytest.mark.parametrize(("text", "tokens", "start"), [
    ("비운영평가", (AnalysisToken("비", "XPN", 0, 1), AnalysisToken("운영", "NNG", 1, 3),
                    AnalysisToken("평가", "NNG", 3, 5)), 3),
    ("한국운영평가", (AnalysisToken("한국", "NNP", 0, 2), AnalysisToken("운영", "NNG", 2, 4),
                      AnalysisToken("평가", "NNG", 4, 6)), 4),
])
def test_internal_nng_component_chain_does_not_skip_an_unlicensed_prefix(text, tokens, start):
    annotation = _Annotation.from_tokens(tokens, text)
    assert _token_aligned_nng_component_owner(text, annotation, start, start + 2, None) is None


def test_explicit_competing_selection_blocks_internal_nng_component_chain():
    text = "운영평가"
    annotation = _Annotation.from_tokens((AnalysisToken("운영", "NNG", 0, 2),
                                         AnalysisToken("평가", "NNG", 2, 4)), text)
    competing = SenseSelection(2, 4, "평가", "other.evaluation", (), "competing_lexical_identity")
    assert not any(match.root.identity == "pyeongga_evaluation"
                   for match in owned_root_matches(text, annotation, (competing,)))


@pytest.mark.parametrize(("source", "expected"), [
    ("평가되었으나", "평까되어쓰나"),
    ("평가하다", "평까하다"),
    ("초점화", "초쩜화"),
    ("초점화된", "초쩜화된"),
    ("제도권", "제도꿘"),
    ("고기압권", "고기압꿘"),
])
def test_registered_onsets_survive_derivation_and_kwon_is_a_productive_suffix(source, expected):
    assert G2P()(source) == expected


@pytest.mark.parametrize("barrier", ["pause", "hard"])
def test_kwon_suffix_respects_a_real_phonological_barrier(barrier):
    text = "수도권"
    if barrier == "hard":
        segments = (_derived_segment("수도", source=text, boundary_after=Boundary.HARD),
                    _derived_segment("권", source=text, start=2, boundary_before=Boundary.HARD))
    else:
        segments = (_derived_segment(text),)
    units = _build_units(segments, trace=True)
    annotation = _Annotation.from_tokens((AnalysisToken("수도", "NNG", 0, 2),
                                         AnalysisToken("권", "XSN", 2, 3)), text)
    _apply_derived_kwon_tensing(units, segments, annotation, None, (2,) if barrier == "pause" else ())
    assert "".join(unit.text for unit in units) == text


@pytest.mark.parametrize(("word", "tag"), [("기권", "NNG"), ("상권", "NNG"), ("한빛권", "NNP")])
def test_whole_noun_spelling_does_not_create_kwon_suffix_ownership(word, tag):
    segments = (_derived_segment(word),)
    units = _build_units(segments, trace=True)
    annotation = _Annotation.from_tokens((AnalysisToken(word, tag, 0, len(word)),), word)
    _apply_derived_kwon_tensing(units, segments, annotation, None)
    assert "".join(unit.text for unit in units) == word


@pytest.mark.parametrize(
    ("text", "expected"),
    (("확실성", "확씰썽"), ("확실성은", "확씰썽은")),
)
def test_selected_xr_host_is_tensed_with_ordinary_continuation(text, expected):
    tokens = KiwiAnalyzer().analyze(text)
    assert [(token.form, token.tag) for token in tokens[:2]] == [
        ("확실", "XR"),
        ("성", "XSN"),
    ]
    assert G2P()(text) == expected


def test_synthetic_xr_host_plus_suffix_is_tensed():
    text = "확실성"
    tokens = (
        AnalysisToken("확실", "XR", 0, 2),
        AnalysisToken("성", "XSN", 2, 3),
    )
    segment = _derived_segment(text)
    units = _build_units((segment,), trace=True)
    annotation = _Annotation.from_tokens(tokens, text)
    rewrites = []

    _apply_derived_seong_tensing(units, (segment,), annotation, rewrites)

    assert "".join(unit.text for unit in units) == "확실썽"
    assert [rewrite.rule_id for rewrite in rewrites] == [
        "ko.derivational.seong_tensing"
    ]


def test_xr_host_with_space_or_pause_does_not_tense_the_suffix():
    assert G2P()("확실 성") == "확씰 성"
    assert G2P()("확실성", pause_boundaries=(2,)) == "확씰성"


def test_xr_host_across_hard_segment_boundary_does_not_tense_the_suffix():
    text = "확실성"
    left = _derived_segment(text[:2], source=text, start=0, boundary_after=Boundary.HARD)
    right = _derived_segment(text[2:], source=text, start=2, boundary_before=Boundary.HARD)
    result = pronounce((left, right))

    assert result.text == "확씰성"
    assert all(rewrite.rule_id != "ko.derivational.seong_tensing" for rewrite in result.rewrites)


def test_malformed_xr_host_offset_does_not_create_a_license():
    text = "확실성"
    tokens = (
        AnalysisToken("확실", "XR", 0, 1),
        AnalysisToken("성", "XSN", 2, 3),
    )
    segment = _derived_segment(text)
    units = _build_units((segment,), trace=True)
    annotation = _Annotation.from_tokens(tokens, text)
    rewrites = []

    _apply_derived_seong_tensing(units, (segment,), annotation, rewrites)

    assert "".join(unit.text for unit in units) == text
    assert rewrites == []


@pytest.mark.parametrize(
    ("host", "tag"),
    (("먹", "VV"), ("높", "VA")),
)
def test_predicate_hosts_do_not_license_xsn_seong(host, tag):
    text = host + "성"
    tokens = (
        AnalysisToken(host, tag, 0, 1),
        AnalysisToken("성", "XSN", 1, 2),
    )
    segment = _derived_segment(text)
    units = _build_units((segment,), trace=True)
    annotation = _Annotation.from_tokens(tokens, text)
    rewrites = []

    _apply_derived_seong_tensing(units, (segment,), annotation, rewrites)

    assert "".join(unit.text for unit in units) == text
    assert rewrites == []


def _run_derived_rule(text: str, tokens: tuple[AnalysisToken, ...]):
    segment = _derived_segment(text)
    units = _build_units((segment,), trace=True)
    annotation = _Annotation.from_tokens(tokens, text)
    rewrites = []
    _apply_derived_seong_tensing(units, (segment,), annotation, rewrites)
    return "".join(unit.text for unit in units), rewrites


def test_dictionary_buseong_is_plain_under_contextual_kiwi_split():
    text = "부성을 강조했다"
    tokens = KiwiAnalyzer().analyze(text)
    assert [(token.form, token.tag) for token in tokens[:3]] == [
        ("부", "NNG"), ("성", "XSN"), ("을", "JKO"),
    ]

    assert G2P()(text) == "부성을 강조핻따"
    result = pronounce((_derived_segment(text),))
    assert result.text == "부성을 강조핻따"
    assert "ko.derivational.seong_tensing" not in {
        rewrite.rule_id for rewrite in result.rewrites
    }


def test_one_syllable_noun_host_is_not_a_productive_suffix_license():
    for host in ("부", "효", "상", "횡"):
        text = host + "성"
        actual, rewrites = _run_derived_rule(text, (
            AnalysisToken(host, "NNG", 0, 1),
            AnalysisToken("성", "XSN", 1, 2),
        ))
        assert actual == text
        assert rewrites == []


def test_multisyllable_noun_suffix_and_adjacent_noun_chain_remain_productive():
    assert [(token.form, token.tag) for token in KiwiAnalyzer().analyze("다양성")[:2]] == [
        ("다양", "NNG"), ("성", "XSN"),
    ]
    assert G2P()("다양성") == "다양썽"

    text = "농업생산성"
    actual, rewrites = _run_derived_rule(text, (
        AnalysisToken("농업", "NNG", 0, 2),
        AnalysisToken("생산", "NNG", 2, 4),
        AnalysisToken("성", "XSN", 4, 5),
    ))
    assert actual == "농업생산썽"
    assert [rewrite.rule_id for rewrite in rewrites] == [
        "ko.derivational.seong_tensing",
    ]


def test_lexicalized_buseong_in_a_following_noun_phrase_stays_plain():
    text = "다음 부성"
    tokens = KiwiAnalyzer().analyze(text)
    assert [(token.form, token.tag) for token in tokens[-2:]] == [
        ("부", "NNG"), ("성", "XSN"),
    ]
    assert G2P()(text) == "다음 부성"


@pytest.mark.parametrize(
    ("text", "expected", "host"),
    (
        (
            "충남 천안시가 추진하는 성성호수공원 일대 로컬푸드 직매장 건립 사업을",
            "충남 처난시가 추진하는 성성호수공원 닐대 로컬푸드 징매장 걸립 싸어블",
            "성",
        ),
        (
            "청주 주성리의 백제 금동 귀걸이 등도 눈길을 끌었다.",
            "청주 주성니에 백쩨 금동 귀거리 등도 눈끼를 끄럳따.",
            "주",
        ),
        (
            "평소를 불고 징과 장구를 치며 횡성 전통시장 골목을 누비자, 채소와 생선을 팔",
            "평소를 불고 징과 장구를 치며 횡성 전통시장 골모글 루비자, 채소와 생서늘 팔",
            "횡",
        ),
    ),
)
def test_known_short_base_corpus_contexts_do_not_tense_lexicalized_words(text, expected, host):
    tokens = KiwiAnalyzer().analyze(text)
    assert any(
        left.form == host and left.tag == "NNG"
        and right.form == "성" and right.tag == "XSN"
        and left.normalized_end == right.normalized_start
        for left, right in zip(tokens, tokens[1:])
    )
    assert G2P()(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    (("시각적 물성이", "시각쩡 물썽이"), ("활성화", "활썽화")),
)
def test_verified_sino_ryeol_siot_tensing_remains_separate(text, expected):
    assert G2P()(text) == expected
    result = pronounce((_derived_segment(text),))
    assert result.text == expected
    assert "ko.sino.tensing.26" in {rewrite.rule_id for rewrite in result.rewrites}
    assert "ko.derivational.seong_tensing" not in {
        rewrite.rule_id for rewrite in result.rewrites
    }
