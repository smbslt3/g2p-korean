import pytest

from g2p_ko import Boundary, G2P, Handler, InputValidationError, OutputSegment, SourceSpan
from g2p_ko import pipeline as pipeline_module
from g2p_ko.korean import engine as korean_engine
from g2p_ko.korean import morphology
from g2p_ko.merge import Marker, _TextSegment
from g2p_ko.model import AnalysisToken
from g2p_ko.pipeline import Pipeline


@pytest.fixture
def independent_sound_rules(monkeypatch):
    """이 테스트에서는 형태소 분석 결과와 독립된 음운 전이만 확인한다."""

    def no_morphology(*args, **kwargs):
        return [], frozenset(), frozenset(), None

    monkeypatch.setattr(korean_engine, "_apply_morphology_rules", no_morphology)


def test_connected_and_paused_sound_rules(independent_sound_rules):
    g2p = G2P()
    pairs = (
        ("옷이", 1),
        ("국물", 1),
        ("신라", 1),
        ("국밥", 1),
    )
    for text, offset in pairs:
        connected = g2p(text)
        paused = g2p(text, pause_boundaries=(offset,))
        assert connected != paused
        assert len(connected) == len(text)
        assert len(paused) == len(text)

    assert g2p("옷이") == "오시"
    assert g2p("옷이", pause_boundaries=(1,)) == "옫이"
    assert g2p("국물") == "궁물"
    assert g2p("국물", pause_boundaries=(1,)) == "국물"
    assert g2p("신라") == "실라"
    assert g2p("신라", pause_boundaries=(1,)) == "신라"


def test_empty_duplicates_default_parity_and_detail_parity(independent_sound_rules):
    g2p = G2P()
    for text in ("옷이", "국물", "신라", "국밥", "옷  이"):
        assert g2p(text) == g2p(text, pause_boundaries=())
        paused = g2p(text, pause_boundaries=(0, len(text), len(text)))
        detailed = g2p.convert(text, pause_boundaries=(0, len(text)))
        assert paused == g2p(text)
        assert detailed.surface_pronunciation == paused
        assert len(paused) == len(text)
    assert g2p("", pause_boundaries=(0, 0)) == ""
    assert g2p("옷이", pause_boundaries=(1, 1)) == g2p("옷이", pause_boundaries=(1,))


def test_pause_positions_around_spaces_keep_spaces(independent_sound_rules):
    g2p = G2P()
    text = "옷  이"
    expected = g2p(text)
    for offset in (1, 2, 3, 4):
        actual = g2p(text, pause_boundaries=(offset,))
        assert actual == expected
        assert "  " in actual
        assert len(actual) == len(text)


def test_kernel_offsets_use_joined_segment_text(independent_sound_rules):
    segments = (
        _TextSegment("옷 ", Handler.KOREAN, "test"),
        _TextSegment(" 이", Handler.KOREAN, "test"),
    )
    joined = "옷  이"
    baseline = korean_engine.pronounce_text(segments)
    for offset in (1, 2, 3, 4):
        actual = korean_engine.pronounce_text(segments, pause_boundaries=(offset,))
        assert actual == baseline
        assert len(actual) == len(joined)
    word_segments = (
        _TextSegment("옷", Handler.KOREAN, "test"),
        _TextSegment("이", Handler.KOREAN, "test"),
    )
    assert korean_engine.pronounce_text(word_segments, pause_boundaries=(1,)) == "옫이"
    with pytest.raises(InputValidationError):
        korean_engine.pronounce_text(word_segments, pause_boundaries=(3,))


@pytest.mark.parametrize("boundaries", ["1", b"1", None, 1])
def test_pause_container_must_be_an_iterable_of_offsets(boundaries):
    with pytest.raises(InputValidationError):
        G2P()("옷이", pause_boundaries=boundaries)


@pytest.mark.parametrize("offset", [True, "1", 1.0, -1, 3])
def test_pause_offset_type_and_range_validation(offset):
    with pytest.raises(InputValidationError):
        G2P()("옷이", pause_boundaries=(offset,))


def test_pause_offsets_use_nfc_code_points_and_keep_input_length_limit():
    g2p = G2P()
    decomposed = "옷이"
    result = g2p(decomposed, pause_boundaries=(1,))
    assert len(result) == len("옷이")
    assert len(g2p(decomposed, pause_boundaries=(2,))) == len("옷이")
    with pytest.raises(InputValidationError):
        g2p(decomposed, pause_boundaries=(3,))
    with pytest.raises(InputValidationError):
        G2P(max_length=1)("가", pause_boundaries=(0,))


def test_full_analyzer_and_sense_context_cross_the_pause(monkeypatch):
    analyzer_inputs = []
    sense_inputs = []

    class FakeAnalyzer:
        def analyze_components(self, text):
            analyzer_inputs.append(text)
            return tuple(
                AnalysisToken(character, "NNG", index, index + 1)
                for index, character in enumerate(text)
                if "가" <= character <= "힣"
            )

        analyze = analyze_components

    def observe_sense_context(text, tokens, hard_boundaries=frozenset()):
        sense_inputs.append((text, frozenset(hard_boundaries)))
        return ()

    monkeypatch.setattr(korean_engine, "KiwiAnalyzer", FakeAnalyzer)
    monkeypatch.setattr(morphology, "select_senses", observe_sense_context)
    text = "옷이 신라"
    result = G2P()(text, pause_boundaries=(1,))

    assert analyzer_inputs == [text]
    assert sense_inputs == [(text, frozenset())]
    assert len(result) == len(text)


def test_existing_hard_segment_boundary_still_blocks_liaison(independent_sound_rules):
    text = "옷이"
    segments = (
        OutputSegment(
            "옷",
            (SourceSpan(0, 1, "옷", 2),),
            Handler.KOREAN,
            "test",
            boundary_after=Boundary.HARD,
        ),
        OutputSegment(
            "이",
            (SourceSpan(1, 2, "이", 2),),
            Handler.KOREAN,
            "test",
            boundary_before=Boundary.HARD,
        ),
    )
    result = korean_engine.pronounce(segments)
    assert result.text == "옫이"


def test_english_replacement_maps_endpoint_and_later_offsets(monkeypatch):
    observed = []

    def observe(segments, *, pause_boundaries=()):
        observed.append(tuple(pause_boundaries))
        return "".join(segment.text for segment in segments)

    monkeypatch.setattr(pipeline_module, "pronounce_text", observe)
    pipeline = Pipeline(max_length=100)
    source = "AI옷"
    routed = pipeline_module.route_spelling_candidates(source)
    candidate = routed.candidates[0]
    resolution = pipeline._resolve_candidate(source, candidate, ())
    assert resolution is not None
    assert len(resolution.replacement) != candidate.end - candidate.start

    pipeline.run_text(source, pause_boundaries=(candidate.start, candidate.end, len(source)))
    shift = len(resolution.replacement) - (candidate.end - candidate.start)
    assert observed == [
        (candidate.start, candidate.end + shift, len(source) + shift),
    ]


def test_pause_inside_length_changing_replacement_is_rejected(monkeypatch):
    def observe(segments, *, pause_boundaries=()):
        return "".join(segment.text for segment in segments)

    monkeypatch.setattr(pipeline_module, "pronounce_text", observe)
    with pytest.raises(InputValidationError):
        Pipeline(max_length=100).run_text("AI옷", pause_boundaries=(1,))


def test_identity_length_replacement_keeps_relative_pause_offset():
    marker = Marker(1, 3, "XY", Handler.KOREAN, "test")
    mapped = Pipeline._map_pause_boundaries("aBCd", [marker], (0, 2, 3, 4))
    assert mapped == (0, 2, 3, 4)


def test_pause_does_not_change_trace_source_spans(independent_sound_rules):
    result = Pipeline(max_length=100).run("옷이", pause_boundaries=(1,))
    for rewrite in result.rewrites:
        for span in rewrite.source_spans:
            assert 0 <= span.start <= span.end <= len("옷이")
            assert span.source_length == len("옷이")
    assert len(result.surface_pronunciation) == len("옷이")
