"""리뷰에서 확인한 표준 발음과 활용형·합성어의 회귀 사례를 검증한다.

근거: 국립국어원 표준 발음법 제5·12·15·17항 및 상담 사례 8033.
https://m.korean.go.kr/front/page/pageView.do?mn_id=95&page_id=P000098
https://www.korean.go.kr/front/mcfaq/mcfaqView.do?mcfaq_seq=8033
"""

import pytest

from g2p_ko import G2P
from g2p_ko.analyzer import KiwiAnalyzer
from g2p_ko.model import AnalysisToken


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("꽂히다", "꼬치다"),
        ("맞히다", "마치다"),
        ("잊히다", "이치다"),
        ("묻혀", "무처"),
        ("굳혀", "구처"),
        ("닫혔다", "다첟따"),
        ("붙여", "부처"),
        ("붙였다", "부첟따"),
        ("잊혀진", "이처진"),
        ("젖혀", "저처"),
        ("곧이어", "고디어"),
        ("맏형", "마텽"),
        ("낮 한때", "나 탄때"),
        ("닭 한 마리", "다 칸 마리"),
        ("맛없어요", "마덥써요"),
        ("맛없는", "마덤는"),
        ("겉옷을", "거도슬"),
        ("값어치를", "가버치를"),
        ("같이", "가치"),
        ("밭이", "바치"),
        ("밭일", "반닐"),
        ("밭일을", "반니를"),
        ("끝인사", "끄딘사"),
        ("끝인사를", "끄딘사를"),
        ("여덟 하나", "여덜 하나"),
        ("넓 하늘", "널 하늘"),
        ("의견란은", "의견나는"),
        ("생산량이", "생산냥이"),
        ("신여성의", "신녀성에"),
        ("맛없이", "마덥씨"),
        ("값없는", "가범는"),
        ("낱알", "나달"),
        ("팥알", "파달"),
        ("꽃 위", "꼬 뒤"),
        ("옷 안", "오 단"),
        ("겉옷 아래", "거도 다래"),
        ("꽃잎이", "꼰니피"),
        ("갈수록", "갈쑤록"),
        ("먹을수록", "머글쑤록"),
        ("보일지라도", "보일찌라도"),
        ("서울역", "서울력"),
        ("서울역이", "서울려기"),
        ("서울역만", "서울령만"),
        # ㄴ 첨가와 구개음화를 실질 형태소의 모든 이웃에 확대하지 않는다.
        ("금요일", "그묘일"),
        ("홑이불", "혼니불"),
        ("해돋이", "해도지"),
        ("감기다", "감기다"),
        ("안기다", "안기다"),
        ("미닫이문", "미다지문"),
        ("여닫이문", "여다지문"),
        ("쇠붙이", "쇠부치"),
        ("금붙이를", "금부치를"),
        ("곧이곧대로", "고지곧때로"),
        ("디귿은", "디그슨"),
        ("디귿으로", "디그스로"),
        ("쌍디귿은", "쌍디그슨"),
        ("히읗은", "히으슨"),
        ("히읗으로", "히으스로"),
        ("키읔은", "키으근"),
        ("피읖으로", "피으브로"),
        ("설익은", "설리근"),
        ("설익었다", "설리걷따"),
        ("할 일", "할 릴"),
        ("한 일", "한 닐"),
        ("옷 입다", "온 닙따"),
        ("잘 입다", "잘 립따"),
        ("일 이 삼", "일 이 삼"),
        ("끝이다", "끄치다"),
        ("밭이에요", "바치에요"),
        ("디귿이다", "디그시다"),
        ("히읗이에요", "히으시에요"),
    ],
)
def test_reviewed_pronunciations(source: str, expected: str) -> None:
    g2p = G2P()
    result = g2p.convert(source)

    assert result.surface_pronunciation == expected
    assert g2p(source) == expected
    assert result.complete
    assert not result.diagnostics.pronunciation.diagnostics
    assert len(result.normalized_text) == len(expected)


@pytest.mark.parametrize(("tokens", "expected"), [
    ((AnalysisToken("서울역", "NNP", 0, 3), AnalysisToken("도", "JX", 3, 4)), "서울력또"),
    ((AnalysisToken("서울", "NNP", 0, 2), AnalysisToken("역도", "NNG", 2, 4)), "서우력또"),
])
def test_station_particle_and_weightlifting_follow_selected_analysis(monkeypatch, tokens, expected):
    # 문맥 없는 고립형의 후보 순위와 의도한 의미에서의 음운 규칙을 분리한다.
    monkeypatch.setattr(KiwiAnalyzer, "analyze_components", lambda self, text: tokens)
    result = G2P().convert("서울역도")
    assert result.normalized_text == "서울역도"
    assert result.surface_pronunciation == expected
    assert G2P()("서울역도") == expected
    assert result.complete
    assert not result.diagnostics.pronunciation.diagnostics


def test_station_particle_with_disambiguating_train_context():
    source = "이 열차는 서울역도 지난다."
    tokens = KiwiAnalyzer().analyze_components(source)
    assert any(token.form == "서울역" and token.tag == "NNP" for token in tokens)
    assert any(token.form == "도" and token.tag == "JX" and token.normalized_start == 9 for token in tokens)
    result = G2P().convert(source)
    assert result.surface_pronunciation == "이 열차는 서울력또 지난다."
    assert result.complete
