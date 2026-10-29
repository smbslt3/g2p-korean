"""고정 제공 분석을 공개 경로로 보내는 어댑터 보조 함수다."""

from __future__ import annotations

from unittest.mock import patch


def run_public(payload):
    """실제 발음·네이티브 결과·분석 호출 기록을 반환하며 권한은 판정하지 않는다."""
    # 동결된 실행기가 어댑터를 명시적으로 호출한 뒤에만 런타임을 가져온다.
    from g2p_ko import G2P
    from g2p_ko.analyzer import KiwiAnalyzer
    from g2p_ko.korean.engine import pronounce
    from g2p_ko.model import AnalysisToken, Boundary, Handler, OutputSegment, SourceSpan

    source = payload["source"]
    tokens = tuple(
        AnalysisToken(
            form=t["form"], tag=t["tag"], normalized_start=t["start"],
            normalized_end=t["end"], morphemes=tuple(tuple(p) for p in t["morphemes"]),
            morpheme_spans=tuple(tuple(p) for p in t["morpheme_spans"]),
        )
        for t in payload["analysis_tokens"]
    )
    calls = []

    def supplied(self, text, *, split_complex=False, saisiot=False):
        calls.append({"text": text, "split_complex": split_complex, "saisiot": saisiot})
        if text != source:
            raise ValueError("요청 원문과 다른 분석 단위를 묵시 재정렬하지 않습니다.")
        return tokens

    def components(self, text):
        return supplied(self, text, split_complex=True, saisiot=True)

    with patch.object(KiwiAnalyzer, "analyze", supplied), patch.object(KiwiAnalyzer, "analyze_components", components):
        if payload["route"] == "G2P":
            native = G2P().convert(source, pause_boundaries=tuple(payload["pause_boundaries"]))
            phone = native.surface_pronunciation
        elif payload["route"] == "engine.pronounce":
            segment = OutputSegment(
                source, (SourceSpan.from_source(source, 0, len(source)),), Handler.KOREAN,
                "고정 제공 분석의 독립 평가", boundary_before=Boundary.HARD, boundary_after=Boundary.HARD,
            )
            native = pronounce((segment,), pause_boundaries=tuple(payload["pause_boundaries"]))
            phone = native.text
        else:
            raise ValueError("이 보조 함수는 붙은 단어의 G2P/engine.pronounce 경로만 지원합니다.")
    return phone, native, calls


def construct_invalid(payload):
    """생성자 거부만 관찰하고 음운 엔진은 호출하지 않는다."""
    from g2p_ko.model import AnalysisToken

    if payload["model"] != "AnalysisToken":
        raise ValueError("알려지지 않은 생성자 모델입니다.")
    try:
        AnalysisToken(**payload["args"])
    except Exception as error:
        return type(error).__name__
    return None
