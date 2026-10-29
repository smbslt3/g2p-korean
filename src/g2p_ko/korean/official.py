"""일반 규칙으로 결정되지 않는 검증된 어휘 발음만 보완한다.

표준발음법의 예시 전체를 런타임 치환표로 쓰지 않는다. 제16·20·24~30항의
생산적 처리는 형태소·어휘 구조와 공통 규칙이 맡고, 공식 예시 정답은
tests/fixtures/korean_official_examples.json에서 독립 회귀 자료로 보존한다.
"""

from __future__ import annotations

from types import MappingProxyType


# 표준발음법 제15항의 허용형 및 현재 분석으로 결정되지 않는 어휘별 발음.
# https://www.korean.go.kr/kornorms/regltn/regltnView.do?regltn_code=0002
_검증_어휘_발음 = {
    "맛있다": "마싣따",
    "멋있다": "머싣따",
    "공권력": "공꿘녁",
    # 모음 조사·어미 앞에서도 같은 예외를 쓸 수 있도록 기저 받침을 유지한다.
    # https://korean.go.kr/front/mcfaq/mcfaqView.do?mcfaq_seq=8062
    "값있": "가빘",
    # https://www.korean.go.kr/front/onlineQna/onlineQnaView.do?qna_seq=335552
    "뜻있": "뜨딨",
    # 단독형을 용언+어미로도 분석하므로 구조 복원으로 강제하지 않는다.
    # https://korean.go.kr/front/onlineQna/onlineQnaView.do?qna_seq=308599
    "알심": "알씸",
}
# 이관한 세 표제의 동형 역할·내부 구조는 boundary_consumers가 증명한다.
NOUN_ONLY_PRONUNCIATIONS = MappingProxyType({})
LEXICAL_PRONUNCIATIONS = MappingProxyType({
    **_검증_어휘_발음, **NOUN_ONLY_PRONUNCIATIONS,
})

__all__: list[str] = []
