"""TTS 전용 수량 복원의 값·경계·출처와 기존 모델 계약을 검증한다."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import re

import pytest

from g2p_ko import ConversionPolicyError, G2P, KoreanTTSNormalizer


@pytest.fixture(scope="module")
def tts() -> KoreanTTSNormalizer:
    normalizer = KoreanTTSNormalizer(output_policy="tts")
    # 새 복원은 학습 계수와 독립된 기본 수량 읽기이므로 모델 없이 검증한다.
    normalizer._number_reader = None
    return normalizer


@pytest.mark.parametrize(("source", "expected"), [
    ("7군데만 확인해요.", "일곱 군데만 확인해요."),
    ("24마리인 상태입니다.", "스물네 마리인 상태입니다."),
    ("7200원이라고요.", "칠천이백 원이라고요."),
    ("48000원이고요.", "사만팔천 원이고요."),
    ("12억 원이랍니다.", "십이억 원이랍니다."),
    ("5천원이니 확인해요.", "오천 원이니 확인해요."),
    ("2백원인 경우입니다.", "이백 원인 경우입니다."),
    ("1.5만원이라고요.", "만오천 원이라고요."),
    ("12년동안 기다렸어요.", "십이 년동안 기다렸어요."),
    ("1880년대와 1997년생입니다.", "천팔백팔십 년대와 천구백구십칠 년생입니다."),
    ("2분기에는 늘었어요.", "이 분기에는 늘었어요."),
    ("8위에 올랐어요.", "팔 위에 올랐어요."),
    ("25프로의 비율입니다.", "이십오 프로의 비율입니다."),
    ("-2.5프로의 변화입니다.", "마이너스 이 점 오 프로의 변화입니다."),
    ("20여 명이 참석했어요.", "이십여 명이 참석했어요."),
    ("2줄로 서세요.", "두 줄로 서세요."),
    ("6월이었어요.", "유월이었어요."),
    ("10월달에 만나요.", "시월달에 만나요."),
    ("4개인 것을 골라요.", "네 개인 것을 골라요."),
    ("7군데예요.", "일곱 군데예요."),
    ("+3.5프로예요.", "플러스 삼 점 오 프로예요."),
    ("4군데였어요.", "네 군데였어요."),
])
def test_recovery_keeps_values_orthography_and_safe_string(tts, source, expected):
    result = tts.convert(source)
    assert result.complete and result.normalized_text == expected
    assert re.fullmatch(r"[가-힣 ,.!?]*", result.normalized_text)
    assert tts(expected) == expected
    assert any(r.rule_id == "normalizer.tts.quantity_recovery.v1" for r in result.rewrites)


@pytest.mark.parametrize("source", [
    "2번인가요.", "3차적으로 바뀌어요.", "4분인가요.", "50대에게 말해요.",
    "007군데만 확인해요.", "02분기입니다.", "0위입니다.", "5분기입니다.",
    "13월달입니다.", "4프로그램을 써요.", "2개인정보를 지워요.",
    "건물7동입니다.", "고2학생입니다.", "AB24군데만 확인해요.",
    "100000000000원이라고요.", "1,2원이라고요.", "1.234원이라고요.",
    "1억 2만 원이라고요.", "20여 갑니다.", "1.5여 명이 있어요.",
    "3~4군데만 확인해요.", "2~3명이서 모여요.", "3**4**마리인 상태입니다.",
    "2년생명체가 있어요.", "4군데알수없는단어를 붙여요.",
])
def test_recovery_never_splits_unsafe_or_ambiguous_structure(tts, source):
    assert not tts.convert(source).complete
    with pytest.raises(ConversionPolicyError):
        tts(source)


@pytest.mark.parametrize("policy", ["preserve", "warn", "error"])
def test_output_policy_and_ambiguity_policy_remain_independent(policy):
    normalizer = KoreanTTSNormalizer(on_ambiguous=policy)
    normalizer._number_reader = None
    source = "7군데만 확인해요."
    if policy == "error":
        with pytest.raises(ConversionPolicyError):
            normalizer.convert(source)
    else:
        before = normalizer.convert(source)
        strict = normalizer.convert_tts(source)
        assert before == normalizer.convert(source)
        assert not before.complete and before.normalized_text == source
        assert strict.complete and strict.normalized_text == "일곱 군데만 확인해요."
    assert normalizer.normalize_tts(source) == "일곱 군데만 확인해요."
    with pytest.raises(ConversionPolicyError):
        normalizer.normalize_tts("007군데만 확인해요.")


def test_recovery_preserves_projected_original_spans_and_optional_g2p(tts):
    source = "\u1100\u1161 **24**마리인 상태, 문을 닫는 동안 <b>7</b>군데만 확인해요."
    result = tts.convert_tts(source)
    assert result.complete
    assert result.normalized_text == "가 스물네 마리인 상태, 문을 닫는 동안 일곱 군데만 확인해요."
    for record in (*result.rewrites, *result.diagnostics):
        for span in record.source_spans:
            assert span.surface == source[span.start:span.end]
    spoken = G2P().convert(result.normalized_text, normalize=False)
    assert spoken.complete and spoken.normalized_text == result.normalized_text
    assert re.fullmatch(r"[가-힣 ,.!?]*", spoken.surface_pronunciation)


def test_explicit_lexicon_precedes_recovery_and_keeps_original_coordinates():
    normalizer = KoreanTTSNormalizer(output_policy="tts", lexicon={"**7**": "칠", "🙂": "웃음", "4군데만": "그곳만"})
    result = normalizer.convert("**7**군데만 🙂 4군데만 확인해요.")
    assert result.complete and result.normalized_text == "칠군데만 웃음 그곳만 확인해요."
    assert not any(r.rule_id == "normalizer.tts.quantity_recovery.v1" for r in result.rewrites)
    for rewrite in result.rewrites:
        for span in rewrite.source_spans:
            assert span.surface == result.source[span.start:span.end]


class _RecordingRun:
    def __init__(self, calls):
        self.calls = calls

    def decide(self, start, end, **options):
        self.calls.append((start,end,options))
        return None

    def take_failure(self):
        return None


class _RecordingReader:
    def __init__(self):
        self.calls = []

    def new_run(self, text):
        return _RecordingRun(self.calls)


def test_recovery_does_not_create_number_model_sites_or_shift_existing_calls():
    reader = _RecordingReader()
    normalizer = KoreanTTSNormalizer()
    normalizer._number_reader = reader
    source = "9번 확인하고 7군데만 표시해요."
    normalizer.convert(source)
    before = list(reader.calls)
    reader.calls.clear()
    strict = normalizer.convert_tts(source)
    assert strict.complete and strict.normalized_text == "아홉 번 확인하고 일곱 군데만 표시해요."
    assert reader.calls == before and len(before) == 1
    assert before[0][2]["unit"] == "번"


def test_shared_instance_does_not_leak_recovery_into_preserve_calls():
    normalizer = KoreanTTSNormalizer()
    normalizer._number_reader = None
    source = "7군데만 확인해요."
    requests = [False,True]*12
    def convert(strict):
        return normalizer.convert_tts(source) if strict else normalizer.convert(source)
    expected = [convert(strict) for strict in requests]
    with ThreadPoolExecutor(max_workers=4) as pool:
        actual = list(pool.map(convert,requests))
    assert actual == expected


@pytest.mark.parametrize("diagnostic", ["ambiguous_identifier", "ambiguous_hyphen", "unsupported_script"])
def test_helper_only_recovers_numeric_ambiguity(diagnostic):
    from g2p_ko.normalizer.policy import ambiguous
    from g2p_ko.normalizer.tts_recovery import recover_tts_quantity
    original = ambiguous("7군데만",diagnostic,"합성 거부 사례")
    assert recover_tts_quantity("7군데만",original) is original
