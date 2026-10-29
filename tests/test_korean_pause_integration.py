"""실제 분석기에서 휴지의 음운 효과와 문맥 보존을 독립 확인한다."""
import unicodedata

import pytest

from g2p_ko import G2P, InputValidationError
from g2p_ko.analyzer import KiwiAnalyzer
import g2p_ko.korean.engine as engine


@pytest.mark.parametrize("text,offset,connected,paused", [
    ("옷이", 1, "오시", "옫이"),
    ("국물", 1, "궁물", "국물"),
    ("신라", 1, "실라", "신라"),
    ("국밥", 1, "국빱", "국밥"),
    ("같이", 1, "가치", "갇이"),
    ("굳히다", 1, "구치다", "굳히다"),
    ("물살", 1, "물쌀", "물살"),
    ("탈색", 1, "탈쌕", "탈색"),
    ("꽃잎", 1, "꼰닙", "꼳입"),
    ("밟고", 1, "밥꼬", "밥고"),
    ("옷 안", 2, "오 단", "옫 안"),
    ("국 물", 2, "궁 물", "국 물"),
    ("신 라", 2, "실 라", "신 라"),
    ("국 밥", 2, "국 빱", "국 밥"),
])
def test_actual_analysis_blocks_only_crossing_sound_dependencies(text, offset, connected, paused):
    converter = G2P()
    assert converter(text) == connected
    actual = converter(text, pause_boundaries=(offset,))
    assert actual == paused
    detailed = converter.convert(text, pause_boundaries=(offset,))
    assert detailed.surface_pronunciation == actual
    assert len(detailed.normalized_text) == len(actual) == len(text)


@pytest.mark.parametrize("text,offset,expected", [
    ("같이만", 2, "가치만"),
    ("물살만", 2, "물쌀만"),
    ("탈색만", 2, "탈쌕만"),
])
def test_pause_preserves_sound_changes_on_its_own_side(text, offset, expected):
    assert G2P()(text, pause_boundaries=(offset,)) == expected


def test_actual_semantic_evidence_and_analyzer_input_survive_pause(monkeypatch):
    seen = []

    class ObservedAnalyzer(KiwiAnalyzer):
        def analyze_components(self, source):
            seen.append(source)
            return super().analyze_components(source)

    monkeypatch.setattr(engine, "KiwiAnalyzer", ObservedAnalyzer)
    source = "그림을 고가에 샀다."
    output = G2P()(source, pause_boundaries=(source.index("샀"),))
    assert output[4:6] == "고까"
    assert seen == [source]


def test_public_offset_mapping_handles_real_english_and_nfc():
    source = "AI 옷 안"
    converter = G2P()
    actual = converter.convert(source, pause_boundaries=(source.index("안"),))
    assert actual.surface_pronunciation == "에이아이 옫 안"
    assert converter(source, pause_boundaries=(source.index("안"),)) == actual.surface_pronunciation
    with pytest.raises(InputValidationError):
        converter(source, pause_boundaries=(1,))
    decomposed = unicodedata.normalize("NFD", "옷 안")
    assert converter(decomposed, pause_boundaries=(2,)) == "옫 안"


def test_space_run_offsets_all_represent_the_same_pause():
    converter = G2P()
    source = "국   물"
    assert converter(source) == "궁   물"
    for offset in (1, 2, 3, 4):
        assert converter(source, pause_boundaries=(offset,)) == source
