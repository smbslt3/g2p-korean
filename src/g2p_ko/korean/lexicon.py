# SPDX-License-Identifier: MIT
"""음운 규칙에 필요한 불변 어휘 속성.

이 모듈은 명세와 작성자의 일반 언어 지식에 근거하여 새로 작성했다.
읽은 입력 파일: ../spec/IMPLEMENTATION_SPEC.md,
../spec/FEEDBACK_01.json, ../spec/FEEDBACK_02.json, ../spec/FEEDBACK_03.json,
../spec/FEEDBACK_04.json
추가 입력 기능 피드백:
../../g2p_structural_cycle_20261025/implementation_feedback.json
../../g2p_structural_cycle_20261025/lexical_feedback07.json
../../g2p_tensing_cycle_20261025/lexical_feedback08.json
../../g2p_tensing_cycle_20261025/lexical_feedback09.json
완성 발음, 외부 사전 레코드, 외부 코드 또는 별도 자료 파일은 포함하지 않는다.
이 작성 기록은 저장소 전체의 법적 상태를 보증하지 않는다.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class LexicalStructure:
    """표기 성분과 성분 사이의 음운 경계를 나타낸다."""

    parts: tuple[tuple[str, str], ...]
    tense_boundaries: tuple[int, ...] = ()
    nasal_liquid_boundaries: tuple[int, ...] = ()
    owner_pos: frozenset[str] = frozenset()
    allow_owned_composition: bool = False

    def __post_init__(self) -> None:
        parts = tuple(tuple(part) for part in self.parts)
        if not parts or any(
            len(part) != 2
            or not isinstance(part[0], str)
            or not part[0]
            or not isinstance(part[1], str)
            or not part[1]
            for part in parts
        ):
            raise ValueError("성분은 비어 있지 않은 표기와 품사 문자열의 쌍이어야 합니다.")
        object.__setattr__(self, "parts", parts)
        owner_pos = frozenset(self.owner_pos)
        if any(pos not in {"NNG", "NNP"} for pos in owner_pos):
            raise ValueError("정확 owner 품사는 NNG 또는 NNP만 허용합니다.")
        object.__setattr__(self, "owner_pos", owner_pos)
        if type(self.allow_owned_composition) is not bool or (self.allow_owned_composition and not owner_pos):
            raise ValueError("성분 재사용은 명시적인 명사 소유 품사와 불리언 설정이 필요합니다.")
        for name in ("tense_boundaries", "nasal_liquid_boundaries"):
            boundaries = tuple(getattr(self, name))
            if any(type(index) is not int or not 0 < index < len(parts) for index in boundaries):
                raise ValueError("경계는 뒤 성분의 유효한 인덱스여야 합니다.")
            if len(boundaries) != len(set(boundaries)):
                raise ValueError("같은 경계를 중복해서 지정할 수 없습니다.")
            object.__setattr__(self, name, boundaries)

    @property
    def spelling(self) -> str:
        """성분 표기를 이어 붙인 원래 표기."""
        return "".join(form for form, _ in self.parts)


@dataclass(frozen=True)
class SinoFeature:
    """한자어 여부를 판단하는 품사와 선택적인 한자 표기."""

    pos: frozenset[str]
    hanja_variants: frozenset[str]

    def __post_init__(self) -> None:
        for name in ("pos", "hanja_variants"):
            values = frozenset(getattr(self, name))
            if any(not isinstance(value, str) or not value for value in values):
                raise ValueError("속성 원소는 비어 있지 않은 문자열이어야 합니다.")
            object.__setattr__(self, name, values)


@dataclass(frozen=True)
class SinoAttachment:
    """뒤에 결합하는 한자 성분의 품사와 경계 속성."""

    form: str
    tag: str
    hanja: str
    nasal_liquid: bool = False


def _compound(
    first: str, second: str, *, tense: bool = False, first_tag: str = "NNG"
) -> LexicalStructure:
    """명사 또는 접두 성분 뒤의 명시적인 어휘 경계를 만든다."""
    return LexicalStructure(((first, first_tag), (second, "NNG")), (1,) if tense else ())


# 합성 경계는 어휘별로 선언하며 임의의 명사 결합을 자동 등록하지 않는다.
LEXICAL_STRUCTURES: Mapping[str, LexicalStructure] = MappingProxyType({
    "솜이불": _compound("솜", "이불"),
    "홑이불": _compound("홑", "이불", first_tag="XPN"),
    "꽃잎": _compound("꽃", "잎"),
    "나뭇잎": _compound("나뭇", "잎"),
    "깻잎": _compound("깻", "잎"),
    "막일": _compound("막", "일", first_tag="XPN"),
    "밭일": _compound("밭", "일"),
    "부엌일": _compound("부엌", "일"),
    "밤일": _compound("밤", "일"),
    "앞일": _compound("앞", "일"),
    "알약": _compound("알", "약"),
    "늦여름": _compound("늦", "여름", first_tag="XPN"),
    # 보+ㄹ이 융합한 관형형의 표면 성분을 명사로 오인하지 않는다.
    "볼일": LexicalStructure((("볼", "VV+ETM"), ("일", "NNG"))),
    "청산유수": _compound("청산", "유수"),
    "맨입": _compound("맨", "입", first_tag="XPN"),
    "한여름": _compound("한", "여름", first_tag="XPN"),
    "젖어미": _compound("젖", "어미"),
    "겉옷": _compound("겉", "옷"),
    "끝인사": _compound("끝", "인사"),
    "첫인사": _compound("첫", "인사", first_tag="MM"),
    "첫인상": _compound("첫", "인상", first_tag="MM"),
    "낱알": _compound("낱", "알", first_tag="XPN"),
    "팥알": _compound("팥", "알"),
    "삯일": _compound("삯", "일"),
    "내복약": _compound("내복", "약"),
    "남존여비": _compound("남존", "여비"),
    "색연필": _compound("색", "연필"),
    "직행열차": _compound("직행", "열차"),
    "늑막염": LexicalStructure((("늑막", "NNG"), ("염", "XSN"))),
    "콩엿": _compound("콩", "엿"),
    "담요": _compound("담", "요"),
    "눈요기": _compound("눈", "요기"),
    "식용유": _compound("식용", "유"),
    "백분율": LexicalStructure((("백분", "NNG"), ("율", "XSN"))),
    "밤윷": _compound("밤", "윷"),
    "도리깻열": _compound("도리깻", "열"),
    "솔잎": _compound("솔", "잎"),
    "설익": LexicalStructure((("설", "XPN"), ("익", "VV"))),
    "물약": _compound("물", "약"),
    "불여우": _compound("불", "여우", first_tag="XPN"),
    "물엿": _compound("물", "엿"),
    "휘발유": _compound("휘발", "유"),
    "서울역": LexicalStructure((("서울", "NNP"), ("역", "NNG"))),
    "공공요금": _compound("공공", "요금"),
    "나랏일": _compound("나랏", "일"),
    "의견란": LexicalStructure((("의견", "NNG"), ("란", "NNG")), nasal_liquid_boundaries=(1,)),
    "임진란": LexicalStructure((("임진", "NNG"), ("란", "NNG")), nasal_liquid_boundaries=(1,)),
    "결단력": LexicalStructure((("결단", "NNG"), ("력", "XSN")), nasal_liquid_boundaries=(1,)),
    "동원령": LexicalStructure((("동원", "NNG"), ("령", "NNG")), nasal_liquid_boundaries=(1,)),
    "상견례": LexicalStructure((("상견", "NNG"), ("례", "NNG")), nasal_liquid_boundaries=(1,)),
    "횡단로": LexicalStructure((("횡단", "NNG"), ("로", "NNG")), nasal_liquid_boundaries=(1,)),
    "입원료": LexicalStructure((("입원", "NNG"), ("료", "XSN")), nasal_liquid_boundaries=(1,)),
    "문고리": _compound("문", "고리", tense=True),
    "눈동자": _compound("눈", "동자", tense=True),
    "손등": _compound("손", "등", tense=True),
    "손길": _compound("손", "길", tense=True),
    "갈대": _compound("갈", "대", tense=True),
    # 날다의 관형형이 명사 앞에 오는 문법 구조로 일반 경음화에 맡긴다.
    "날짐승": LexicalStructure((("날", "VV+ETM"), ("짐승", "NNG"))),
    # 두 어휘의 확인된 내부 경음화만 선언하고 독립 분석된 명사 성분에 재사용한다.
    "글자": LexicalStructure((("글", "NNG"), ("자", "NNG")), (1,), owner_pos=frozenset({"NNG", "NNP"}), allow_owned_composition=True),
    "땅바닥": LexicalStructure((("땅", "NNG"), ("바닥", "NNG")), (1,), owner_pos=frozenset({"NNG", "NNP"}), allow_owned_composition=True),
    "손바닥": _compound("손", "바닥", tense=True),
    "발바닥": _compound("발", "바닥", tense=True),
    "발등": _compound("발", "등", tense=True),
    "팔심": _compound("팔", "심", tense=True),
    "산길": _compound("산", "길", tense=True),
    "길가": _compound("길", "가", tense=True),
    "물가": _compound("물", "가", tense=True),
    "물고기": _compound("물", "고기", tense=True),
    "술잔": _compound("술", "잔", tense=True),
    "신바람": _compound("신", "바람", tense=True),
    "산새": _compound("산", "새", tense=True),
    "손재주": _compound("손", "재주", tense=True),
    "물동이": _compound("물", "동이", tense=True),
    "물살": _compound("물", "살", tense=True),
    "굴속": _compound("굴", "속", tense=True),
    "바람결": _compound("바람", "결", tense=True),
    "그믐달": _compound("그믐", "달", tense=True),
    "아침밥": _compound("아침", "밥", tense=True),
    "초승달": _compound("초승", "달", tense=True),
    "등불": _compound("등", "불", tense=True),
    "창살": _compound("창", "살", tense=True),
    "강줄기": _compound("강", "줄기", tense=True),
    "줄넘기": LexicalStructure((("줄", "NNG"), ("넘", "VV"), ("기", "XSN"))),
    # 굳어진 어휘의 경음화 속성이며 일반 명사 파생 접미사 전체의 속성이 아니다.
    "싫증": LexicalStructure((("싫", "VA"), ("증", "XSN")), tense_boundaries=(1,)),
    "밤길": _compound("밤", "길", tense=True),
    "밤거리": _compound("밤", "거리", tense=True),
    "공것": LexicalStructure((("공", "XPN"), ("것", "NNB")), tense_boundaries=(1,)),
    "문법": _compound("문", "법", tense=True),
    # 확인한 세 어휘의 내부 경음화만 일반 경계 규칙에 연결한다.
    "민법": _compound("민", "법", tense=True),
    "헌법": _compound("헌", "법", tense=True),
    "형법": _compound("형", "법", tense=True),
    "형성평가": LexicalStructure((("형성", "NNG"), ("평", "NNG"), ("가", "NNG")), (2,), owner_pos=frozenset({"NNG", "NNP"})),
    "총괄평가": LexicalStructure((("총괄", "NNG"), ("평", "NNG"), ("가", "NNG")), (2,), owner_pos=frozenset({"NNG", "NNP"})),
    "수행평가": LexicalStructure((("수행", "NNG"), ("평", "NNG"), ("가", "NNG")), (2,), owner_pos=frozenset({"NNG", "NNP"})),
    "진단평가": LexicalStructure((("진단", "NNG"), ("평", "NNG"), ("가", "NNG")), (2,), owner_pos=frozenset({"NNG", "NNP"})),
})


def _sino(hanja: str, *pos: str) -> SinoFeature:
    """확신할 수 있는 한자 표기 하나와 실제 품사를 선언한다."""
    return SinoFeature(frozenset(pos), frozenset((hanja,)))


# 소규모 독립 선언이며 어떤 외부 목록의 행 수나 구성도 재현하지 않는다.
SINO_ORIGINS: Mapping[str, SinoFeature] = MappingProxyType({
    "갈등": _sino("葛藤", "NNG"),
    "발달": _sino("發達", "NNG"),
    "결단": _sino("決斷", "NNG"),
    "철도": _sino("鐵道", "NNG"),
    "활동": _sino("活動", "NNG"),
    "발사": _sino("發射", "NNG"),
    "일상": _sino("日常", "NNG"),
    "월세": _sino("月貰", "NNG"),
    "실적": _sino("實績", "NNG"),
    "열정": _sino("熱情", "NNG"),
    "절정": _sino("絕頂", "NNG"),
    "생산": _sino("生産", "NNG"),
    "제한": _sino("制限", "NNG"),
    "수량": _sino("數量", "NNG"),
    "발동": _sino("發動", "NNG"),
    "출동": _sino("出動", "NNG"),
    "출전": SinoFeature(frozenset({"NNG"}), frozenset({"出戰", "出典"})),
    "절도": SinoFeature(frozenset({"NNG"}), frozenset({"竊盜", "節度"})),
    "말살": _sino("抹殺", "NNG"),
    "불소": _sino("弗素", "NNG"),
    "일시": _sino("一時", "NNG", "MAG"),
    "갈증": _sino("渴症", "NNG"),
    "발전": SinoFeature(frozenset({"NNG"}), frozenset({"發展", "發電"})),
    "몰상식": _sino("沒常識", "NNG"),
    "불세출": _sino("不世出", "NNG"),
    "의견": _sino("意見", "NNG"),
    "임진": _sino("壬辰", "NNG"),
    "동원": _sino("動員", "NNG"),
    "상견": _sino("相見", "NNG"),
    "횡단": _sino("橫斷", "NNG"),
    "입원": _sino("入院", "NNG"),
    # 독립 명사 기반 속성이므로 적법한 후행 성분 여러 개에 재사용할 수 있다.
    "추진": _sino("推進", "NNG"),
    "해군": _sino("海軍", "NNG"),
    "출연": _sino("出演", "NNG"),
    "수신": _sino("受信", "NNG"),
    "등산": _sino("登山", "NNG"),
    "이원": _sino("二元", "NNG"),
    "결정": SinoFeature(frozenset({"NNG"}), frozenset({"決定", "結晶"})),
    "일정": SinoFeature(frozenset({"NNG"}), frozenset({"日程", "一定"})),
    "달성": _sino("達成", "NNG"),
    "설정": _sino("設定", "NNG"),
    "실수": SinoFeature(frozenset({"NNG"}), frozenset({"失手", "實數"})),
    "불일치": _sino("不一致", "NNG"),
    "결산": _sino("決算", "NNG"),
    "결석": _sino("缺席", "NNG"),
    "발생": _sino("發生", "NNG"),
    "일종": _sino("一種", "NNG"),
    "필수": _sino("必須", "NNG"),
    "절대": _sino("絕對", "NNG", "MAG"),
    "실제": _sino("實際", "NNG", "MAG"),
    "실상": _sino("實相", "NNG", "MAG"),
    "일절": _sino("一切", "MAG"),
    "일단": _sino("一旦", "MAG"),
    "질주": _sino("疾走", "NNG"),
    "질서": _sino("秩序", "NNG"),
    "골절": _sino("骨折", "NNG"),
    "결실": _sino("結實", "NNG"),
    "결심": _sino("決心", "NNG"),
    "결제": _sino("決濟", "NNG"),
    "결재": _sino("決裁", "NNG"),
    "골수": _sino("骨髓", "NNG"),
    "필자": _sino("筆者", "NNG"),
    "탈세": _sino("脫稅", "NNG"),
    "탈색": _sino("脫色", "NNG"),
    "살생": _sino("殺生", "NNG"),
    "살상": _sino("殺傷", "NNG"),
    "실질": _sino("實質", "NNG"),
    "실정": SinoFeature(frozenset({"NNG"}), frozenset({"實情", "失政"})),
    "일당": _sino("日當", "NNG"),
    "일심": _sino("一心", "NNG"),
    "철수": _sino("撤收", "NNG"),
    "절제": _sino("節制", "NNG"),
    "절수": _sino("節水", "NNG"),
    "절단": _sino("切斷", "NNG"),
    "발신": _sino("發信", "NNG"),
    "설득": _sino("說得", "NNG"),
    "필독": _sino("必讀", "NNG"),
    "필사": SinoFeature(frozenset({"NNG"}), frozenset({"筆寫", "必死"})),
    "실시": _sino("實施", "NNG"),
    "일": _sino("一", "NR"),
    "이": _sino("二", "NR"),
    "삼": _sino("三", "NR"),
    "사": _sino("四", "NR"),
    "오": _sino("五", "NR"),
    "육": _sino("六", "NR"),
    "칠": _sino("七", "NR"),
    "팔": _sino("八", "NR"),
    "구": _sino("九", "NR"),
    "십": _sino("十", "NR"),
    "백": _sino("百", "NR"),
    "천": _sino("千", "NR"),
    "만": _sino("萬", "NR"),
    "억": _sino("億", "NR"),
    "조": _sino("兆", "NR"),
})

SINO_KOREAN_LEXEMES: frozenset[str] = frozenset(SINO_ORIGINS)

SAISIOT_COMBINING_FORMS: frozenset[str] = frozenset({
    "나뭇", "깻", "뒷", "윗", "아랫", "햇", "콧", "귓", "잇", "바닷", "도리깻", "나랏",
})

NO_N_INSERTION_LEXEMES: frozenset[str] = frozenset({
    "할인", "확인", "독일", "석유", "금요일",
    "끝인사", "첫인사", "첫인상", "불일치",
})

# 띄어 쓴 명사 성분의 ㄴ 비첨가 경계다. 발음형이 아닌 원문 성분과 품사만 선언한다.
NO_N_INSERTION_COMPONENT_BOUNDARIES: tuple[tuple[str, str, str, str], ...] = (
    ("아침", "NNG", "인사", "NNG"),
    ("작품", "NNG", "이름", "NNG"),
)

SINO_ATTACHMENTS: tuple[SinoAttachment, ...] = (
    SinoAttachment("량", "NNG", "量", nasal_liquid=True),
    SinoAttachment("란", "NNG", "欄", nasal_liquid=True),
    SinoAttachment("력", "XSN", "力", nasal_liquid=True),
    SinoAttachment("령", "NNG", "令", nasal_liquid=True),
    SinoAttachment("례", "NNG", "禮", nasal_liquid=True),
    SinoAttachment("로", "NNG", "路", nasal_liquid=True),
    SinoAttachment("료", "XSN", "料", nasal_liquid=True),
    SinoAttachment("론", "XSN", "論", nasal_liquid=True),
    SinoAttachment("문", "XSN", "文"),
)

__all__ = (
    "LexicalStructure", "SinoFeature", "SinoAttachment", "LEXICAL_STRUCTURES",
    "SINO_ORIGINS", "SINO_KOREAN_LEXEMES", "SAISIOT_COMBINING_FORMS",
    "NO_N_INSERTION_LEXEMES", "NO_N_INSERTION_COMPONENT_BOUNDARIES", "SINO_ATTACHMENTS",
)
