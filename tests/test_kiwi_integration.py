"""PyPI 배포 Kiwi.tokenize와 원문 정렬 어댑터의 통합을 검증한다."""

from __future__ import annotations

import pytest
from kiwipiepy import Kiwi

import g2p_ko.analyzer as analyzer_module
from g2p_ko.analyzer import KiwiAnalyzer
from g2p_ko.model import AnalysisToken
from tests._internal_pipeline import convert_pipeline


@pytest.fixture(scope="module")
def kiwi() -> Kiwi:
    """비용이 큰 형태소 모델을 모듈 내 실제 통합 테스트에서 재사용한다."""

    return Kiwi()


@pytest.fixture(autouse=True)
def use_real_kiwi(monkeypatch: pytest.MonkeyPatch, kiwi: Kiwi) -> None:
    monkeypatch.setattr(analyzer_module, "_runtime_kiwi", kiwi)


def test_installed_kiwi_exposes_source_aligned_tokenize(kiwi: Kiwi) -> None:
    assert [(part.tag, part.start, part.len) for part in kiwi.tokenize("했다")] == [
        ("VV", 0, 1),
        ("EP", 0, 1),
        ("EF", 1, 1),
    ]
    assert [
        (part.form, part.tag, part.start, part.len)
        for part in kiwi.tokenize("A\u2800B")
    ] == [
        ("A", "SL", 0, 1),
        ("B", "SL", 2, 1),
    ]


def test_real_tokens_merge_into_source_aligned_analysis_tokens(kiwi: Kiwi) -> None:
    source = "우리의 맑게 할 것을"

    tokens = KiwiAnalyzer().analyze(source)

    assert tokens == (
        AnalysisToken("우리", "NP", 0, 2),
        AnalysisToken("의", "JKG", 2, 3),
        AnalysisToken("맑", "VA", 4, 5),
        AnalysisToken("게", "EC", 5, 6),
        AnalysisToken("할", "VX+ETM", 7, 8),
        AnalysisToken("것", "NNB", 9, 10),
        AnalysisToken("을", "JKO", 10, 11),
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "3개라고",
            (
                AnalysisToken("3", "SN", 0, 1),
                AnalysisToken("개", "NNB", 1, 2),
                AnalysisToken("라고", "VCP+EC", 2, 4),
            ),
        ),
        (
            "회사다",
            (
                AnalysisToken("회사", "NNG", 0, 2),
                AnalysisToken("다", "VCP+EF", 2, 3),
            ),
        ),
        ("닥", (AnalysisToken("닥", "VV+EF+Z_CODA", 0, 1),)),
    ],
)
def test_zero_length_morpheme_tags_keep_the_split_style_contract(
    kiwi: Kiwi,
    source: str,
    expected: tuple[AnalysisToken, ...],
) -> None:
    assert KiwiAnalyzer().analyze(source) == expected


def test_real_kiwi_drives_morphology_rules_after_nfc_normalization(kiwi: Kiwi) -> None:
    source = "\u110b\u116e리의 맑게 할 것을"

    result = convert_pipeline(source)

    assert result.normalized_text == "우리의 맑게 할 것을"
    assert result.surface_pronunciation == "우리에 말께 할 꺼슬"
    assert result.complete
    assert not result.diagnostics
    assert {
        "ko.ui.particle",
        "ko.stem.rieul_giyeok",
        "ko.modifier.tensing.27",
    } <= {item.rule_id for item in result.rewrites}
    particle = next(item for item in result.rewrites if item.rule_id == "ko.ui.particle")
    assert [(span.start, span.end) for span in particle.source_spans] == [(3, 4)]


def test_real_kiwi_analyzes_many_candidates_in_one_tokenize_call(
    monkeypatch: pytest.MonkeyPatch,
    kiwi: Kiwi,
) -> None:
    count = 1_000
    source = "맑게 " * count
    calls = 0

    class CountingKiwi:
        """실제 Kiwi에 위임하면서 tokenize 호출 수만 기록한다."""

        def tokenize(self, text: str):
            nonlocal calls
            calls += 1
            return kiwi.tokenize(text)

    monkeypatch.setattr(analyzer_module, "_runtime_kiwi", CountingKiwi())
    result = convert_pipeline(source, max_length=len(source))

    assert calls == 1
    assert result.surface_pronunciation == "말께 " * count
    assert result.complete
    assert not result.diagnostics


def test_real_kiwi_saisiot_batch_preserves_order_but_not_split_semantics(
    kiwi: Kiwi,
) -> None:
    """사이시옷 전용 분해도 batch 순서와 원문 offset을 보존한다."""

    texts = ("냇가", "시곗바늘")
    batch = list(
        kiwi.tokenize(
            iter(texts),
            split_complex=True,
            saisiot=True,
        )
    )

    assert [
        [(token.form, str(token.tag), token.start, token.len) for token in tokens]
        for tokens in batch
    ] == [
        [
            (token.form, str(token.tag), token.start, token.len)
            for token in kiwi.tokenize(
                text,
                split_complex=True,
                saisiot=True,
            )
        ]
        for text in texts
    ]
    assert [
        (token.start, token.len)
        for tokens in batch
        for token in tokens
        if token.tag == "Z_SIOT"
    ] == [(0, 1), (1, 1)]
