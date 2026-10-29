# SPDX-License-Identifier: MIT
"""명시적인 형태소 관계에 근거하여 한정된 동형 명사의 의미를 선택한다."""

from bisect import bisect_left, bisect_right
from contextvars import ContextVar
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Mapping
import unicodedata


# 호출별 상태만 보관하여 재진입과 독립 선택의 인용 소유를 분리한다.
_QUOTE_OWNERSHIP = ContextVar("_quote_ownership", default=None)


@dataclass(frozen=True)
class SemanticToken:
    """원문 표면 구간과 원래 정규 형태소를 함께 보관한다."""

    form: str
    tag: str
    start: int
    end: int
    morphemes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "morphemes", tuple(tuple(pair) for pair in self.morphemes))


@dataclass(frozen=True)
class SenseFeatures:
    """발음 결과가 아닌 의미 분류와 어휘 구성만 표현한다."""

    spelling: str
    semantic_classes: frozenset[str]
    parts: tuple[tuple[str, str], ...] = ()
    tense_boundaries: tuple[int, ...] = ()
    sino: bool = False

    def __post_init__(self):
        object.__setattr__(self, "semantic_classes", frozenset(self.semantic_classes))
        object.__setattr__(self, "parts", tuple(tuple(pair) for pair in self.parts))
        object.__setattr__(self, "tense_boundaries", tuple(self.tense_boundaries))


@dataclass(frozen=True)
class SenseDerivation:
    """명사 뿌리와 파생 접미사의 실제 형태소 결합을 선언한다."""

    root: str
    suffix: str
    suffix_tag: str
    sense_id: str


@dataclass(frozen=True)
class SenseEvidence:
    """대상과 근거의 원문 구간을 연결한다."""

    relation: str
    target_start: int
    target_end: int
    anchor_start: int
    anchor_end: int
    semantic_class: str


@dataclass(frozen=True)
class SenseSelection:
    """대상별 선택 또는 판단 유보와 그 근거를 보관한다."""

    start: int
    end: int
    spelling: str
    sense_id: str | None
    evidence: tuple[SenseEvidence, ...]
    reason: str

    def __post_init__(self):
        object.__setattr__(self, "evidence", tuple(self.evidence))


# 아래 자료는 기능 명세와 일반적인 언어 지식만으로 독립 작성한 어휘 사실이다.
SENSE_FEATURES: Mapping[str, SenseFeatures] = MappingProxyType({
    "munja.text": SenseFeatures("문자", frozenset({"writing_symbol"})),
    "munja.message_shorthand": SenseFeatures("문자", frozenset({"message"})),
    # 제외 뜻의 현재 발음은 결정하지 않고 소유권 기본 읽기만 차단한다.
    "munja.classical_expression": SenseFeatures("문자", frozenset({"classical_expression"})),
    "munja.learning": SenseFeatures("문자", frozenset({"learning"})),
    "jamjari.bedding": SenseFeatures("잠자리", frozenset({"bedding", "sleeping_place"}), (("잠", "NNG"), ("자리", "NNG")), (1,)),
    "jamjari.insect": SenseFeatures("잠자리", frozenset({"animal", "insect"})),
    "gangga.riverbank": SenseFeatures("강가", frozenset({"location", "riverbank"}), (("강", "NNG"), ("가", "NNG")), (1,)),
    "gangga.marriage_event": SenseFeatures("강가", frozenset({"marriage_event"})),
    "muljil.diving": SenseFeatures("물질", frozenset({"activity", "sea_harvesting"}), (("물", "NNG"), ("질", "XSN"))),
    "muljil.substance": SenseFeatures("물질", frozenset({"substance"}), sino=True),
    "goga.expensive_price": SenseFeatures("고가", frozenset({"price", "high_price"}), (("고", "NNG"), ("가", "NNG")), (1,), True),
    "goga.old_house": SenseFeatures("고가", frozenset({"dwelling_house"}), (("고", "NNG"), ("가", "NNG")), (), True),
    "goga.elevated_structure": SenseFeatures("고가", frozenset({"elevated_structure"}), (("고", "NNG"), ("가", "NNG")), (), True),
    "sabeop.judicial_function": SenseFeatures("사법", frozenset({"judicial_function"}), (("사", "NNG"), ("법", "NNG")), (), True),
    "sabeop.private_law": SenseFeatures("사법", frozenset({"private_law"}), (("사", "NNG"), ("법", "NNG")), (1,), True),
    "sosu.minority_quantity": SenseFeatures("소수", frozenset({"minority_quantity"}), (("소", "NNG"), ("수", "NNG")), (), True),
    "sosu.prime_number": SenseFeatures("소수", frozenset({"prime_number"}), (("소", "NNG"), ("수", "NNG")), (1,), True),
    "sosu.decimal_number": SenseFeatures("소수", frozenset({"decimal_number"}), (("소", "NNG"), ("수", "NNG")), (), True),
    "siga.market_price": SenseFeatures("시가", frozenset({"price"}), (("시", "NNG"), ("가", "NNG")), (1,), True),
    "siga.literary_poetry": SenseFeatures("시가", frozenset({"literary_poetry"}), (("시", "NNG"), ("가", "NNG")), (), True),
    # 다른 뜻의 성분ㆍ음운 속성은 이 명세에서 검증하지 않아 지정하지 않는다.
    "siga.spouse_family": SenseFeatures("시가", frozenset({"spouse_family"})),
    "gaesu.count_quantity": SenseFeatures("개수", frozenset({"count_quantity"}), (("개", "NNG"), ("수", "NNG")), (1,), True),
    "gaesu.renovation": SenseFeatures("개수", frozenset({"renovation"}), (("개", "NNG"), ("수", "NNG")), (), True),
    "gaesu.washing_water": SenseFeatures("개수", frozenset({"washing_water"}), (("개", "NNG"), ("수", "NNG"))),
    "gaesu.armour_sleeve": SenseFeatures("개수", frozenset({"armour_sleeve"}), (("개", "NNG"), ("수", "NNG")), (), True),
    "malbal.speech_ability": SenseFeatures("말발", frozenset({"speech_ability"}), (("말", "NNG"), ("발", "NNG")), (1,)),
    "malbal.equinus": SenseFeatures("말발", frozenset({"equinus"})),
    "pyeongga.house": SenseFeatures("평가", frozenset({"dwelling_house", "house_construction"}), (("평", "NNG"), ("가", "NNG")), (), True),
    "pyeongga.parity": SenseFeatures("평가", frozenset({"ordinary_price", "monetary_parity"}), (("평", "NNG"), ("가", "NNG")), (1,), True),
    "pyeongga.appraisal": SenseFeatures("평가", frozenset({"assessment", "value_appraisal"}), (("평", "NNG"), ("가", "NNG")), (1,), True),
})
SENSE_DERIVATIONS = (
    SenseDerivation("평가", "하", "XSV", "pyeongga.appraisal"),
)
TARGET_SPELLINGS = frozenset(value.spelling for value in SENSE_FEATURES.values())

_NOUN_CLASSES = MappingProxyType({
    "기호": frozenset({"writing_symbol"}),
    "메시지": frozenset({"message"}),
    "한문": frozenset({"classical_expression"}),
    "숙어": frozenset({"classical_expression"}),
    "성구": frozenset({"classical_expression"}),
    "문장": frozenset({"classical_expression"}),
    "학식": frozenset({"learning"}),
    "학문": frozenset({"learning"}),
    "날개": frozenset({"biological_part"}),
    "더듬이": frozenset({"biological_part"}),
    "겹눈": frozenset({"biological_part"}),
    "외골격": frozenset({"biological_part"}),
    "원자": frozenset({"physical_constituent"}),
    "분자": frozenset({"physical_constituent"}),
    "원소": frozenset({"physical_constituent"}),
    "성분": frozenset({"physical_constituent"}),
    "전복": frozenset({"sea_product"}),
    "해삼": frozenset({"sea_product"}),
    "성게": frozenset({"sea_product"}),
    "소라": frozenset({"sea_product"}),
    "해산물": frozenset({"sea_product"}),
    "염분": frozenset({"physical_content"}),
    "수분": frozenset({"physical_content"}),
    "당분": frozenset({"physical_content"}),
    "왼쪽": frozenset({"directional_modifier"}),
    "오른쪽": frozenset({"directional_modifier"}),
    "양쪽": frozenset({"directional_modifier"}),
    "앞쪽": frozenset({"directional_modifier"}),
    "뒤쪽": frozenset({"directional_modifier"}),
    "위쪽": frozenset({"directional_modifier"}),
    "아래쪽": frozenset({"directional_modifier"}),
    "해녀": frozenset({"human"}),
    "사람": frozenset({"human", "counted_human"}),
    "학생": frozenset({"human"}),
    "연구자": frozenset({"human"}),
    "과학자": frozenset({"human"}),
    "화학자": frozenset({"human"}),
    "어부": frozenset({"human"}),
    "작업자": frozenset({"human"}),
    "밀도": frozenset({"physical_property"}),
    "질량": frozenset({"physical_property"}),
    "분자량": frozenset({"physical_property"}),
    "부피": frozenset({"physical_property"}),
    "비열": frozenset({"physical_property"}),
    "전도도": frozenset({"physical_property"}),
    "굴절률": frozenset({"physical_property"}),
    "점도": frozenset({"physical_property"}),
    "용해도": frozenset({"physical_property"}),
    "모래톱": frozenset({"terrain_feature"}),
    "갈대": frozenset({"terrain_feature"}),
    "안방": frozenset({"house_part"}),
    "대청": frozenset({"house_part"}),
    "사랑채": frozenset({"house_part"}),
    "온돌방": frozenset({"house_part"}),
    "교각": frozenset({"elevated_structure_part"}),
    "교대": frozenset({"elevated_structure_part"}),
    "교량받침": frozenset({"elevated_structure_part"}),
    "집": frozenset({"dwelling_house", "trade_item"}),
    "평집": frozenset({"dwelling_house", "house_construction"}),
    "가옥": frozenset({"dwelling_house", "trade_item"}),
    "주택": frozenset({"dwelling_house", "trade_item"}),
    "한옥": frozenset({"dwelling_house", "trade_item"}),
    "옛집": frozenset({"dwelling_house", "trade_item"}),
    "고가도로": frozenset({"elevated_structure"}),
    "고가철도": frozenset({"elevated_structure"}),
    "육교": frozenset({"elevated_structure"}),
    "민법": frozenset({"private_law_branch"}),
    "상법": frozenset({"private_law_branch"}),
    "재판권": frozenset({"judicial_function"}),
    "재판": frozenset({"judicial_act"}),
    "판결": frozenset({"judicial_act"}),
    "법원": frozenset({"judicial_institution"}),
    "재판소": frozenset({"judicial_institution"}),
    "기관": frozenset({"institution_head"}),
    "가격": frozenset({"price"}),
    "값": frozenset({"price"}),
    "거래가격": frozenset({"price"}),
    "매매가격": frozenset({"price"}),
    "금액": frozenset({"price"}),
    "시": frozenset({"literary_poetry"}),
    "시문": frozenset({"literary_poetry"}),
    "노래": frozenset({"literary_poetry"}),
    "서정시": frozenset({"poetry_member"}),
    "서사시": frozenset({"poetry_member"}),
    "운율": frozenset({"poetry_part"}),
    "압운": frozenset({"poetry_part"}),
    "시구": frozenset({"poetry_part"}),
    "율격": frozenset({"poetry_part"}),
    "십진소수": frozenset({"decimal_number"}),
    "유한소수": frozenset({"decimal_number", "decimal_member"}),
    "순환소수": frozenset({"decimal_number", "decimal_member"}),
    "소수점": frozenset({"decimal_part"}),
    "소수부": frozenset({"decimal_part"}),
    "순환마디": frozenset({"decimal_part"}),
    "진분수": frozenset({"proper_fraction"}),
    "자연수": frozenset({"natural_number"}),
    "양의정수": frozenset({"natural_number"}),
    "약수": frozenset({"divisor"}),
    "자연수약수": frozenset({"natural_divisor"}),
    "개수": frozenset({"count_head"}),
    "수": frozenset({"number_head"}),
    "일종": frozenset({"membership_head"}),
    "분야": frozenset({"membership_head"}),
    "체계": frozenset({"system_head"}),
    "갈래": frozenset({"membership_head"}),
    "참가자": frozenset({"counted_human"}),
    "유권자": frozenset({"counted_human"}),
    "인원": frozenset({"counted_human"}),
    "의견": frozenset({"counted_opinion"}),
    "가치": frozenset({"value_modifier"}),
    "판단": frozenset({"assessment_head"}),
    "보통": frozenset({"ordinary_price_modifier"}),
    "고택": frozenset({"dwelling_house", "trade_item"}),
    "전통가옥": frozenset({"dwelling_house", "trade_item"}),
    "그림": frozenset({"trade_item"}),
    "물건": frozenset({"trade_item"}),
    "물품": frozenset({"trade_item"}),
    "상품": frozenset({"trade_item"}),
    "작품": frozenset({"trade_item", "creative_work"}),
    "건물": frozenset({"trade_item"}),
    "토지": frozenset({"trade_item"}),
    "주식": frozenset({"trade_item"}),
    "차량": frozenset({"trade_item"}),
    "선물": frozenset({"benefactive_item"}),
    "기념품": frozenset({"benefactive_item"}),
    "친정": frozenset({"family_home"}),
    "처가": frozenset({"family_home"}),
    "본가": frozenset({"family_home"}),
    "외가": frozenset({"family_home"}),
    "바탕": frozenset({"adverbial_basis_head"}),
    "근거": frozenset({"adverbial_basis_head"}),
    "기준": frozenset({"adverbial_basis_head"}),
    "민사법": frozenset({"private_law_branch"}),
    "가족법": frozenset({"private_law_branch"}),
    "채권법": frozenset({"private_law_branch"}),
    "물권법": frozenset({"private_law_branch"}),
    "법": frozenset({"legal_type_head"}),
    "법률관계": frozenset({"legal_relation"}),
    "관계": frozenset({"relation_head"}),
    "개인": frozenset({"private_party"}),
    "사인": frozenset({"private_party"}),
    "간": frozenset({"between_head"}),
    "사이": frozenset({"between_head"}),
    "범주": frozenset({"membership_head"}),
    "영역": frozenset({"membership_head"}),
    "부문": frozenset({"membership_head"}),
    "종류": frozenset({"membership_head"}),
    "중가": frozenset({"price", "middle_price"}),
    "저가": frozenset({"price", "low_price"}),
    "시장가격": frozenset({"price"}),
    "매매가": frozenset({"price"}),
    "공시가격": frozenset({"price"}),
    "호가": frozenset({"price"}),
    "등락": frozenset({"price_change"}),
    "다수": frozenset({"quantity_group", "majority_quantity"}),
    "대다수": frozenset({"quantity_group", "majority_quantity"}),
    "과반수": frozenset({"quantity_group", "majority_quantity"}),
    "극소수": frozenset({"minority_quantity"}),
    "소인수": frozenset({"prime_number"}),
    "정수": frozenset({"integer"}),
    "양수": frozenset({"positive_number"}),
    "양": frozenset({"positive_sign"}),
    "기와집": frozenset({"dwelling_house", "trade_item"}),
    "기와주택": frozenset({"dwelling_house", "trade_item"}),
    "중저가": frozenset({"price", "middle_price", "low_price"}),
    "가격대": frozenset({"price", "price_range"}),
    "가격구간": frozenset({"price", "price_range"}),
    "가격범위": frozenset({"price", "price_range"}),
    "기능": frozenset({"function_head"}),
    "작용": frozenset({"function_head"}),
    "권능": frozenset({"function_head"}),
    "말": frozenset({"designation_head"}),
    "용어": frozenset({"designation_head"}),
    "명칭": frozenset({"designation_head"}),
    "이름": frozenset({"designation_head"}),
    "자기": frozenset({"reflexive_modifier"}),
    "자신": frozenset({"self_reference"}),
    "자기자신": frozenset({"self_reference"}),
    "구간": frozenset({"range_head"}),
    "범위": frozenset({"range_head"}),
    "대역": frozenset({"range_head"}),
    "곤충": frozenset({"animal", "insect"}),
    "동물": frozenset({"animal"}),
    "침구": frozenset({"bedding"}),
    "침구류": frozenset({"bedding"}),
    "수면장소": frozenset({"sleeping_place"}),
    "잠잘자리": frozenset({"sleeping_place"}),
    "화학물질": frozenset({"substance"}),
    "재료": frozenset({"substance"}),
    "활동": frozenset({"activity"}),
    "작업": frozenset({"activity"}),
    "잠수채취": frozenset({"activity", "sea_harvesting"}),
    "강변": frozenset({"location", "riverbank"}),
    "강기슭": frozenset({"location", "riverbank"}),
    "하천변": frozenset({"location", "riverbank"}),
    "장소": frozenset({"location"}),
    "지역": frozenset({"location"}),
    "혼례": frozenset({"marriage_event"}),
    "혼인": frozenset({"marriage_event"}),
    "도로": frozenset({"road_structure_head"}),
    "철도": frozenset({"road_structure_head"}),
    "차도": frozenset({"road_structure_head"}),
    "보행로": frozenset({"road_structure_head"}),
    "문학": frozenset({"literary_domain"}),
    "운문": frozenset({"literary_poetry", "literary_verse"}),
    "운문문학": frozenset({"literary_poetry", "literary_work"}),
    "시문학": frozenset({"literary_poetry", "literary_domain"}),
    "문학작품": frozenset({"literary_work", "trade_item"}),
    "문학장르": frozenset({"literary_domain", "membership_head"}),
    "예전": frozenset({"temporal_anchor"}),
    "옛날": frozenset({"temporal_anchor"}),
    "과거": frozenset({"temporal_anchor"}),
    "교량": frozenset({"elevated_structure", "road_structure_head"}),
    "도로교량": frozenset({"elevated_structure", "road_structure_head"}),
    "형식": frozenset({"form_head"}),
    "양식": frozenset({"form_head"}),
    "형태": frozenset({"form_head"}),
    "곳": frozenset({"location_head"}),
    "공중": frozenset({"elevated_location"}),
    "허공": frozenset({"elevated_location"}),
    "현재": frozenset({"temporal_anchor"}),
    "지금": frozenset({"temporal_anchor"}),
})
# 병렬 유형 지지는 이 명시된 본유 유형의 직접 어휘 근거를 요구한다.
_INTRINSIC_NOUN_CLASSES = frozenset({"human_ability"})
_GENITIVE_EFFECTS = MappingProxyType({
    "biological_part": "animal",
    "physical_constituent": "substance",
    "physical_content": "substance",
    "physical_property": "substance",
    "terrain_feature": "location",
    "house_part": "dwelling_house",
    "elevated_structure_part": "elevated_structure",
    "judicial_act": "judicial_function",
    "judicial_institution": "judicial_function",
    "private_law_branch": "private_law",
    "poetry_part": "literary_poetry",
    "decimal_part": "decimal_number",
    "counted_human": "minority_quantity",
    "counted_opinion": "minority_quantity",
    "price_change": "price",
})
_ADNOMINAL_COMPATIBILITY = MappingProxyType({
    "directional_modifier": frozenset({"biological_part", "terrain_feature"}),
})


@dataclass(frozen=True)
class _Frame:
    """관계 종류, 논항 역할과 필요한 추가 논항 분류를 선언한다."""

    relation: str
    role: str
    classes: frozenset[str]
    support_role: str = ""
    support_class: str = ""
    head_role: str = ""
    predicate_tag: str = ""
    support_unowned: bool = False
    particle_forms: frozenset[str] = frozenset()
    required_adjuncts: frozenset[str] = frozenset()
    require_coordination: bool = False
    require_owned: bool = False
    effect_kind: str = ""
    broad_domain: str = ""
    effect_dependencies: tuple[str, ...] = ()
    narrowing: str = ""


def _argument(role, *classes, support_role="", support_class="", predicate_tag="", particle_forms=(), required_adjuncts=(), require_coordination=False, require_owned=False, effect_kind="", broad_domain="", effect_dependencies=(), narrowing=""):
    """서술어 논항 틀을 선언하기 위한 자료 생성 함수다."""
    return _Frame("predicate_argument", role, frozenset(classes), support_role, support_class,
                  predicate_tag=predicate_tag, particle_forms=frozenset(particle_forms),
                  required_adjuncts=frozenset(required_adjuncts),
                  require_coordination=require_coordination, require_owned=require_owned,
                  effect_kind=effect_kind, broad_domain=broad_domain,
                  effect_dependencies=tuple(effect_dependencies), narrowing=narrowing)


def _relative(*classes, support_role="", support_class="", head_role="", relation="relative_modifier", predicate_tag="", support_unowned=False, required_adjuncts=(), effect_kind="", broad_domain="", effect_dependencies=(), narrowing=""):
    """관형절의 직접 후행 명사에 관한 틀을 선언한다."""
    return _Frame(relation, "head", frozenset(classes), support_role, support_class, head_role, predicate_tag, support_unowned,
                  required_adjuncts=frozenset(required_adjuncts), effect_kind=effect_kind,
                  broad_domain=broad_domain, effect_dependencies=tuple(effect_dependencies), narrowing=narrowing)


_FRAMES = MappingProxyType({
    # 거래의 장소ㆍ판매자ㆍ목적물을 가격 논항으로 바꾸지 않는다.
    "산정하": (_argument("object", "price", effect_kind='lexical_domain', broad_domain='quantitative_value', effect_dependencies=('predicate', 'argument')),),
    "책정하": (_argument("object", "price", effect_kind='lexical_domain', broad_domain='quantitative_value', effect_dependencies=('predicate', 'argument')),),
    "추산하": (_argument("object", "price", effect_kind='lexical_domain', broad_domain='quantitative_value', effect_dependencies=('predicate', 'argument')),),
    "낭송하": (_argument("object", "literary_poetry", effect_kind='lexical_domain', broad_domain='linguistic_content', effect_dependencies=('predicate', 'argument')),),
    "읊": (_argument("object", "literary_poetry", effect_kind='lexical_domain', broad_domain='linguistic_content', effect_dependencies=('predicate', 'argument')),),
    "작시하": (_argument("object", "literary_poetry", effect_kind='lexical_domain', broad_domain='linguistic_content', effect_dependencies=('predicate', 'argument')),),
    "재판하": (_argument("subject", "judicial_function", effect_kind='affirmative_type', broad_domain='relation_dependent_classification', effect_dependencies=('predicate', 'argument')),),
    "급등하": (_argument("subject", "price", effect_kind='lexical_domain', broad_domain='quantitative_value', effect_dependencies=('predicate', 'argument')),),
    "폭등하": (_argument("subject", "price", effect_kind='lexical_domain', broad_domain='quantitative_value', effect_dependencies=('predicate', 'argument')),),
    "폭락하": (_argument("subject", "price", effect_kind='lexical_domain', broad_domain='quantitative_value', effect_dependencies=('predicate', 'argument')),),
    "등락하": (_argument("subject", "price", effect_kind='lexical_domain', broad_domain='quantitative_value', effect_dependencies=('predicate', 'argument')),),
    "담당하": (_argument("subject", "judicial_function", support_role="object", support_class="judicial_act", effect_kind='affirmative_type', broad_domain='relation_dependent_classification', effect_dependencies=('predicate', 'argument', 'support')), _relative("judicial_function", support_role="object", support_class="judicial_act", head_role="subject", effect_kind='affirmative_type', broad_domain='relation_dependent_classification', effect_dependencies=('predicate', 'argument', 'support'))),
    "관장하": (_argument("subject", "judicial_function", support_role="object", support_class="judicial_act", effect_kind='affirmative_type', broad_domain='relation_dependent_classification', effect_dependencies=('predicate', 'argument', 'support')), _relative("judicial_function", support_role="object", support_class="judicial_act", head_role="subject", effect_kind='affirmative_type', broad_domain='relation_dependent_classification', effect_dependencies=('predicate', 'argument', 'support'))),
    "수행하": (_argument("subject", "judicial_function", support_role="object", support_class="judicial_act", effect_kind='affirmative_type', broad_domain='relation_dependent_classification', effect_dependencies=('predicate', 'argument', 'support')), _relative("judicial_function", support_role="object", support_class="judicial_act", head_role="subject", effect_kind='affirmative_type', broad_domain='relation_dependent_classification', effect_dependencies=('predicate', 'argument', 'support'))),
    "규율하": (_argument("subject", "private_law", support_role="object", support_class="private_relation", effect_kind='affirmative_type', broad_domain='relation_dependent_classification', effect_dependencies=('predicate', 'argument', 'support')), _relative("private_law", support_role="object", support_class="private_relation", head_role="subject", effect_kind='affirmative_type', broad_domain='relation_dependent_classification', effect_dependencies=('predicate', 'argument', 'support'))),
    "나타내": (_argument("object", "decimal_number", support_role="via", support_class="proper_fraction", effect_kind='affirmative_type', broad_domain='relation_dependent_classification', effect_dependencies=('predicate', 'argument', 'support')),),
    "펴": (_argument("object", "bedding", effect_kind='lexical_domain', broad_domain='foldable_object', effect_dependencies=('predicate', 'argument')),),
    "개": (_argument("object", "bedding", effect_kind='lexical_domain', broad_domain='foldable_object', effect_dependencies=('predicate', 'argument')),),
    "자": (_argument("location", "sleeping_place", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument')),),
    "눕": (_argument("location", "sleeping_place", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument')),),
    "쉬": (_argument("location", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument')),),
    "앉": (_argument("location", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument')),),
    "머물": (_argument("location", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument')),),
    "살": (_argument("location", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument')),),
    "걷": (_argument("location", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument')),),
    "놀": (_argument("location", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument')),),
    "낚시하": (_argument("location", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument')),),
    "산책하": (_argument("location", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument')),),
    "가": (_argument("location", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument')), _argument("via", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument'))),
    "오": (_argument("location", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument')), _argument("via", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument'))),
    "이동하": (_argument("location", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument')), _argument("via", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument'))),
    "나가": (_argument("location", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument')), _argument("via", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument'))),
    "나오": (_argument("location", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument')), _argument("via", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument'))),
    "들어가": (_argument("location", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument')), _argument("via", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument'))),
    "들어오": (_argument("location", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument')), _argument("via", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument'))),
    "다가가": (_argument("location", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument')), _argument("via", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument'))),
    "다가오": (_argument("location", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument')), _argument("via", "location", effect_kind='lexical_domain', broad_domain='spatial_argument', effect_dependencies=('predicate', 'argument'))),
    "채집하": (_argument("object", "animal", effect_kind='narrowing_domain', broad_domain='event_participant', effect_dependencies=('predicate', 'argument'), narrowing='owned_domain'), _relative("animal", head_role="object", effect_kind='narrowing_domain', broad_domain='event_participant', effect_dependencies=('predicate', 'argument'), narrowing='owned_domain')),
    "날": (_argument("subject", "animal", effect_kind='narrowing_domain', broad_domain='event_participant', effect_dependencies=('predicate', 'argument'), narrowing='owned_domain'), _relative("animal", head_role="subject", effect_kind='narrowing_domain', broad_domain='event_participant', effect_dependencies=('predicate', 'argument'), narrowing='owned_domain')),
    "날아가": (_argument("subject", "animal", effect_kind='narrowing_domain', broad_domain='event_participant', effect_dependencies=('predicate', 'argument'), narrowing='owned_domain'), _relative("animal", head_role="subject", effect_kind='narrowing_domain', broad_domain='event_participant', effect_dependencies=('predicate', 'argument'), narrowing='owned_domain')),
    "날아다니": (_argument("subject", "animal", effect_kind='narrowing_domain', broad_domain='event_participant', effect_dependencies=('predicate', 'argument'), narrowing='owned_domain'), _relative("animal", head_role="subject", effect_kind='narrowing_domain', broad_domain='event_participant', effect_dependencies=('predicate', 'argument'), narrowing='owned_domain')),
    "부화하": (_argument("subject", "animal", effect_kind='narrowing_domain', broad_domain='event_participant', effect_dependencies=('predicate', 'argument'), narrowing='owned_domain'), _relative("animal", head_role="subject", effect_kind='narrowing_domain', broad_domain='event_participant', effect_dependencies=('predicate', 'argument'), narrowing='owned_domain')),
    "가지": (_relative("animal", support_role="object", support_class="biological_part", head_role="subject", effect_kind='owned_domain', broad_domain='original_part_owner', effect_dependencies=('predicate', 'argument', 'support'), narrowing='owned_domain'),),
    "달리": (_relative("animal", support_role="subject", support_class="biological_part", head_role="location", effect_kind='owned_domain', broad_domain='original_part_owner', effect_dependencies=('predicate', 'argument', 'support'), narrowing='owned_domain'),),
    "시작하": (_argument("object", "activity", effect_kind='lexical_domain', broad_domain='action_nominal', effect_dependencies=('predicate', 'argument')),),
    "마치": (_argument("object", "activity", effect_kind='lexical_domain', broad_domain='action_nominal', effect_dependencies=('predicate', 'argument')),),
    "끝내": (_argument("object", "activity", effect_kind='lexical_domain', broad_domain='action_nominal', effect_dependencies=('predicate', 'argument')),),
    "그만두": (_argument("object", "activity", effect_kind='lexical_domain', broad_domain='action_nominal', effect_dependencies=('predicate', 'argument')),),
    "계속하": (_argument("object", "activity", effect_kind='lexical_domain', broad_domain='action_nominal', effect_dependencies=('predicate', 'argument')),),
    "캐": (_relative("sea_harvesting", support_role="object", support_class="sea_product", effect_kind='affirmative_type', broad_domain='relation_dependent_classification', effect_dependencies=('predicate', 'argument', 'support')),),
    "채취하": (_relative("sea_harvesting", support_role="object", support_class="sea_product", effect_kind='affirmative_type', broad_domain='relation_dependent_classification', effect_dependencies=('predicate', 'argument', 'support')),),
    "이루어지": (
        _argument("subject", "substance", support_role="via", support_class="physical_constituent", effect_kind='affirmative_type', broad_domain='relation_dependent_classification', effect_dependencies=('predicate', 'argument', 'support')),
        _relative("substance", support_role="via", support_class="physical_constituent", head_role="subject", effect_kind='affirmative_type', broad_domain='relation_dependent_classification', effect_dependencies=('predicate', 'argument', 'support')),
    ),
    "구성되": (
        _argument("subject", "substance", support_role="via", support_class="physical_constituent", effect_kind='affirmative_type', broad_domain='relation_dependent_classification', effect_dependencies=('predicate', 'argument', 'support')),
        _relative("substance", support_role="via", support_class="physical_constituent", head_role="subject", effect_kind='affirmative_type', broad_domain='relation_dependent_classification', effect_dependencies=('predicate', 'argument', 'support')),
    ),
    "포함하": (_argument("subject", "substance", support_role="object", support_class="physical_constituent", effect_kind='affirmative_type', broad_domain='relation_dependent_classification', effect_dependencies=('predicate', 'argument', 'support')),),
    "찢어지": (_relative("animal", support_role="subject", support_class="biological_part", relation="relative_part_owner", support_unowned=True, effect_kind='owned_domain', broad_domain='original_part_owner', effect_dependencies=('predicate', 'argument', 'support'), narrowing='owned_domain'),),
    "부러지": (_relative("animal", support_role="subject", support_class="biological_part", relation="relative_part_owner", support_unowned=True, effect_kind='owned_domain', broad_domain='original_part_owner', effect_dependencies=('predicate', 'argument', 'support'), narrowing='owned_domain'),),
    "잘리": (_relative("animal", support_role="subject", support_class="biological_part", relation="relative_part_owner", support_unowned=True, effect_kind='owned_domain', broad_domain='original_part_owner', effect_dependencies=('predicate', 'argument', 'support'), narrowing='owned_domain'),),
    "손상되": (_relative("animal", support_role="subject", support_class="biological_part", relation="relative_part_owner", support_unowned=True, effect_kind='owned_domain', broad_domain='original_part_owner', effect_dependencies=('predicate', 'argument', 'support'), narrowing='owned_domain'),),
    "다치": (_relative("animal", support_role="subject", support_class="biological_part", relation="relative_part_owner", support_unowned=True, effect_kind='owned_domain', broad_domain='original_part_owner', effect_dependencies=('predicate', 'argument', 'support'), narrowing='owned_domain'),),
    "하": (
        _argument("object", "activity", support_role="subject", support_class="human", predicate_tag="VV", effect_kind='lexical_domain', broad_domain='action_nominal', effect_dependencies=('predicate', 'argument', 'support')),
        _argument("incorporated_object", "activity", support_role="subject", support_class="human", predicate_tag="XSV", effect_kind='derived_nominal', broad_domain='original_derived_nominal', effect_dependencies=('predicate', 'argument', 'support', 'root_suffix')),
        _relative("activity", support_role="subject", support_class="human", head_role="object", relation="relative_activity", predicate_tag="VV", effect_kind='lexical_domain', broad_domain='action_nominal', effect_dependencies=('predicate', 'argument', 'support')),
    ),
})

# 수량ㆍ소유 관계는 실제 논항과 질문 부사에 연결한다. 말발은 공동 목적어의
# 다른 모든 성분이 명시된 사람 능력일 때만 소유 구문에서 언변 뜻을 얻는다.
_COUNT_QUESTION = (
    _argument("subject", "count_quantity", support_role="topic", required_adjuncts={"얼마나"}, effect_kind='lexical_domain', broad_domain='counted_quantity', effect_dependencies=('predicate', 'argument', 'support')),
    _argument("subject", "count_quantity", required_adjuncts={"얼마나"}, require_owned=True, effect_kind='lexical_domain', broad_domain='counted_quantity', effect_dependencies=('predicate', 'argument', 'owner')),
    _argument("topic", "count_quantity", required_adjuncts={"얼마나"}, require_owned=True, effect_kind='lexical_domain', broad_domain='counted_quantity', effect_dependencies=('predicate', 'argument', 'owner')),
)
_COUNTING = (
    _argument("object", "count_quantity", effect_kind='lexical_domain', broad_domain='counted_quantity', effect_dependencies=('predicate', 'argument')),
    _argument("focus", "count_quantity", effect_kind='lexical_domain', broad_domain='counted_quantity', effect_dependencies=('predicate', 'argument')),
)
_SPEECH_ABILITY_POSSESSION = (
    _argument("object", "speech_ability", support_role="object", support_class="human_ability", require_coordination=True, effect_kind='narrowing_domain', broad_domain='possessed_entity', effect_dependencies=('predicate', 'argument', 'support'), narrowing='owned_domain'),
    _argument("focus", "speech_ability", support_role="focus", support_class="human_ability", require_coordination=True, effect_kind='narrowing_domain', broad_domain='possessed_entity', effect_dependencies=('predicate', 'argument', 'support'), narrowing='owned_domain'),
)
_FRAMES = MappingProxyType(dict(_FRAMES) | {
    "있": _FRAMES.get("있", ()) + _COUNT_QUESTION,
    "되": _FRAMES.get("되", ()) + _COUNT_QUESTION + (_argument("incorporated_object", "renovation", predicate_tag="XSV", effect_kind='derived_nominal', broad_domain='original_derived_nominal', effect_dependencies=('predicate', 'argument', 'root_suffix')),),
    "하": _FRAMES.get("하", ()) + (_argument("incorporated_object", "renovation", predicate_tag="XSV", effect_kind='derived_nominal', broad_domain='original_derived_nominal', effect_dependencies=('predicate', 'argument', 'root_suffix')),),
    "세": _FRAMES.get("세", ()) + _COUNTING,
    "헤아리": _FRAMES.get("헤아리", ()) + _COUNTING,
    "계산하": _FRAMES.get("계산하", ()) + _COUNTING,
    "집계하": _FRAMES.get("집계하", ()) + _COUNTING,
    "파악하": _FRAMES.get("파악하", ()) + _COUNTING,
    "많": _FRAMES.get("많", ()) + (
        _argument("subject", "count_quantity", predicate_tag="VA", effect_kind='lexical_domain', broad_domain='counted_quantity', effect_dependencies=('predicate', 'argument')),
        _relative("count_quantity", predicate_tag="VA", effect_kind='lexical_domain', broad_domain='counted_quantity', effect_dependencies=('predicate', 'argument')),
    ),
    "적": _FRAMES.get("적", ()) + (
        _argument("subject", "count_quantity", predicate_tag="VA", effect_kind='lexical_domain', broad_domain='counted_quantity', effect_dependencies=('predicate', 'argument')),
        _relative("count_quantity", predicate_tag="VA", effect_kind='lexical_domain', broad_domain='counted_quantity', effect_dependencies=('predicate', 'argument')),
    ),
    "가지": _FRAMES.get("가지", ()) + _SPEECH_ABILITY_POSSESSION,
    "가지고있": _FRAMES.get("가지고있", ()) + _SPEECH_ABILITY_POSSESSION,
    "갖고있": _FRAMES.get("갖고있", ()) + _SPEECH_ABILITY_POSSESSION,
    "지니": _FRAMES.get("지니", ()) + _SPEECH_ABILITY_POSSESSION,
    "지니고있": _FRAMES.get("지니고있", ()) + _SPEECH_ABILITY_POSSESSION,
    "갖": _FRAMES.get("갖", ()) + _SPEECH_ABILITY_POSSESSION,
    "보유하": _FRAMES.get("보유하", ()) + _SPEECH_ABILITY_POSSESSION,
    "소유하": _FRAMES.get("소유하", ()) + _SPEECH_ABILITY_POSSESSION,
})
_CASE_ROLES = MappingProxyType({
    "LABEL": MappingProxyType({"*": "label"}),
    "JKQ": MappingProxyType({"라고": "label", "이라고": "label", "라": "label"}),
    "JKO": MappingProxyType({"*": "object"}),
    "JKS": MappingProxyType({"*": "subject"}),
    "JKC": MappingProxyType({"*": "complement"}),
    "JKB": MappingProxyType({
        "에": "location", "에서": "location", "로": "via", "으로": "via",
        "에게": "recipient", "한테": "recipient", "께": "recipient",
        "에게서": "source", "한테서": "source", "로부터": "source", "으로부터": "source", "부터": "source",
        "와": "comitative", "과": "comitative", "처럼": "comparison", "보다": "comparison",
        "라고": "label", "이라고": "label",
    }),
})
_NOUN_TAGS = frozenset({"NNG", "NNP", "NP", "NR", "SN", "COUNT"})
_NOMINAL_FRAGMENT_TAGS = _NOUN_TAGS | {"XPN", "XSN"}
_PREDICATE_TAGS = frozenset({"VV", "VA", "VX", "VCP", "VCN", "XSV", "XSA"})
_ENDINGS = frozenset({"EF", "EC", "ETM", "ETN"})


@dataclass(frozen=True)
class _VerbComplex:
    """허용된 정규 서술어ㆍ연결 어미ㆍ보조 용언의 구성을 선언한다."""

    base_tags: frozenset[str]
    connector_tag: str
    connector_forms: frozenset[str]
    auxiliary_tag: str
    auxiliary_forms: frozenset[str]
    result_tag: str


_VERB_COMPLEXES = (
    _VerbComplex(frozenset({"VV"}), "EC", frozenset({"아", "어", "고"}), "VX", frozenset({"있"}), "VV"),
    _VerbComplex(frozenset({"VV", "VA"}), "EC", frozenset({"아", "어"}), "VX", frozenset({"지"}), "VV"),
)
_SENSES_BY_SPELLING = MappingProxyType({
    spelling: tuple(key for key, value in SENSE_FEATURES.items() if value.spelling == spelling)
    for spelling in TARGET_SPELLINGS
})


@dataclass(frozen=True)
class _FunctionalOccurrence:
    """추정 좌표 없이 원래 canonical 항목과 전체 원태그를 보관한다."""

    token_index: int
    canonical_index: int
    form: str
    raw_tag: str
    start: int
    end: int
    canonical_supplied: bool = True
    token_tag: str = ""
    token_roles_consistent: bool = True
    role_consistent: bool = True
    core_role_consistent: bool = True


@dataclass(frozen=True)
class _NominalSource:
    """두 기존 명사 생산자의 논리 명사와 실제 완전 성분열을 기록한다."""

    form: str
    start: int
    end: int
    morphemes: tuple[tuple[str, str], ...]
    source_occurrences: tuple[_FunctionalOccurrence, ...]
    token_sources: tuple[tuple[int, str, str, int, int, tuple[tuple[str, str], ...]], ...]


@dataclass(frozen=True)
class _NominalHead(SemanticToken):
    """대상 핵어 신원과 실제 전체 성분은 공통 명사 증명과 구별해 보존한다."""

    source_occurrences: tuple[_FunctionalOccurrence, ...] = ()
    nominal_source: _NominalSource | None = None


@dataclass(frozen=True)
class _LongNegativeComplex:
    """실제 본용언 소유와 순서 있는 부정 읽기를 함께 운반한다."""

    base_occurrences: tuple[_FunctionalOccurrence, ...]
    operator_occurrences: tuple[tuple[_FunctionalOccurrence, ...], ...]
    prefinals: tuple[_FunctionalOccurrence, ...]
    final: tuple[_FunctionalOccurrence, str] | None
    readings: tuple[frozenset[str], ...]
    relative_kind: str
    unresolved_dependencies: tuple[str, ...]
    start: int
    end: int
    short_negatives: tuple[_FunctionalOccurrence, ...] = ()
    licensed: bool = True
    unlicensed_readings: tuple[str, ...] = ()
    base_unresolved: bool = False
    core_end: int = -1
    nominal_source: _NominalSource | None = None


@dataclass(frozen=True)
class _Unit:
    """정규 형태소 하나와 그것을 제공한 표면 토큰을 연결한다."""

    form: str
    tag: str
    start: int
    end: int
    token_index: int
    endings: tuple[str, ...] = ()
    noun_classes: frozenset[str] = frozenset()
    nominal_owners: tuple["_Mention", ...] = ()
    nominal_components: tuple[tuple[int, int], ...] = ()
    occurrences: tuple[_FunctionalOccurrence, ...] = ()
    long_negative: _LongNegativeComplex | None = None
    nominal_source: _NominalSource | None = None
    nominal_facts: tuple[tuple[str, str, int, int], ...] = ()


@dataclass(frozen=True)
class _Mention:
    """구체적인 명사 출현을 나타내며 대상 간 의미를 복사하지 않는다."""

    token_index: int
    form: str
    start: int
    end: int
    noun_classes: frozenset[str] = frozenset()
    owned: bool = False
    owners: tuple["_Mention", ...] = ()
    facts: tuple[tuple[str, str, int, int], ...] = ()
    bound_arguments: tuple["_Argument", ...] = ()


@dataclass(frozen=True)
class _Argument:
    """하나의 실제 격 조사를 공유하는 명사구다."""

    role: str
    members: tuple[_Mention, ...]
    particle_form: str = ""
    particle_start: int = -1
    particle_end: int = -1


@dataclass(frozen=True)
class _Event:
    """첫 서술어가 소비한 논항과 서술어 구간을 보관한다."""

    predicate: str
    start: int
    end: int
    arguments: tuple[_Argument, ...]
    tag: str = ""
    negated: bool = False
    adjuncts: tuple[str, ...] = ()
    long_negative: _LongNegativeComplex | None = None
    source_tokens: tuple[SemanticToken, ...] = ()


def _tag(raw):
    """불규칙 표지 접미사를 제거하되 어형은 변경하지 않는다."""
    return raw.split("-", 1)[0]


def _valid_span(token, size):
    """유효하지 않은 좌표가 관계 추론에 쓰이지 않도록 한다."""
    return (
        isinstance(token.start, int) and not isinstance(token.start, bool)
        and isinstance(token.end, int) and not isinstance(token.end, bool)
        and 0 <= token.start < token.end <= size
    )


def _scope_index(text, tokens, hard_boundaries):
    """문장 부호와 절단 위치를 한 번 색인하여 토큰별 범위를 결정한다."""
    separators = [
        index for index, char in enumerate(text)
        if char in "\r\n<>{}[]()`" or unicodedata.category(char).startswith("P")
    ]
    cuts = sorted(set(separators) | {index + 1 for index in separators} | set(hard_boundaries))
    groups = {}
    unsupported = set()
    for index, token in enumerate(tokens):
        if not _valid_span(token, len(text)):
            unsupported.add(index)
            continue
        left = bisect_right(cuts, token.start)
        if left < len(cuts) and cuts[left] < token.end:
            unsupported.add(index)
            continue
        separator_index = bisect_left(separators, token.start)
        if separator_index < len(separators) and separators[separator_index] < token.end:
            unsupported.add(index)
            continue
        groups.setdefault(left, []).append(index)
    return groups, unsupported


def _complete_nominal_fragment(tokens, members):
    """범위 절단으로 더 큰 연속 명사의 일부만 핵어가 되는 것을 막는다."""
    first, last = members[0], members[-1]
    if first > 0 and tokens[first - 1].end == tokens[first].start:
        if _tag(tokens[first - 1].tag) in _NOMINAL_FRAGMENT_TAGS:
            return False
    if last + 1 < len(tokens) and tokens[last].end == tokens[last + 1].start:
        if _tag(tokens[last + 1].tag) in _NOMINAL_FRAGMENT_TAGS:
            return False
    return True


def _recognize_heads(text, tokens, scopes, unsupported):
    """선언된 표제어와 완전히 일치하는 인접 명사 토큰 묶음만 인식한다."""
    heads = {}
    skipped = set()
    for indices in scopes.values():
        position = 0
        while position < len(indices):
            first = indices[position]
            if _tag(tokens[first].tag) not in _NOMINAL_FRAGMENT_TAGS:
                position += 1
                continue
            stop = position + 1
            while stop < len(indices):
                before, after = tokens[indices[stop - 1]], tokens[indices[stop]]
                if before.end != after.start or _tag(after.tag) not in _NOMINAL_FRAGMENT_TAGS:
                    break
                stop += 1
            members = indices[position:stop]
            tags = tuple(_tag(tokens[index].tag) for index in members)
            spelling = "".join(tokens[index].form for index in members)
            start, end = tokens[first].start, tokens[members[-1]].end
            common = _complete_common_nominal(tags)
            if common and _complete_nominal_fragment(tokens, members) and spelling in TARGET_SPELLINGS and text[start:end] == spelling:
                pairs = tuple(pair for index in members for pair in (tokens[index].morphemes or ((tokens[index].form, tokens[index].tag),)))
                source = _complete_nominal_source(tokens, members, spelling, start, end)
                heads[first] = _NominalHead(spelling, "NNG", start, end, pairs,
                                            _original_occurrences(tokens, members), source)
                skipped.update(members[1:])
            position = stop
    for index in unsupported:
        token = tokens[index]
        if token.form in TARGET_SPELLINGS and _tag(token.tag) == "NNG":
            heads[index] = token
    return heads, skipped


def _modifier_compatible(modifier_classes, head_classes):
    """선언된 명사 수식어와 후행 핵어 분류의 호환성만 확인한다."""
    return any(_ADNOMINAL_COMPATIBILITY.get(noun_class, frozenset()) & head_classes for noun_class in modifier_classes)


_DECLARED_NON_NNG_NOUN_TAGS = MappingProxyType({"평집": frozenset({"NNP"})})


def _nominal_classes(form, tag, pairs):
    """완전한 명사 또는 허용된 수식어와 핵어의 전체 구성만 분류한다."""
    if tag == "SN" and form == "1":
        return frozenset({"number_one"})
    if tag not in {"NNG", "NNP"}:
        return frozenset()
    if tag == "NNP" and tag not in _DECLARED_NON_NNG_NOUN_TAGS.get(form, frozenset()):
        return frozenset()
    if form in _NOUN_CLASSES:
        return _NOUN_CLASSES[form]
    if tag != "NNG":
        return frozenset()
    # 복수 접미사는 완전한 원래 형태소 구성에서만 제거해 분류한다.
    if len(pairs) > 1 and pairs[-1] == ("들", "XSN") and "".join(part for part, _ in pairs) == form:
        return _nominal_classes("".join(part for part, _ in pairs[:-1]), "NNG", pairs[:-1])
    if len(pairs) < 2 or any(_tag(pos) != "NNG" for _, pos in pairs):
        return frozenset()
    if "".join(part for part, _ in pairs) != form:
        return frozenset()
    head_classes = _NOUN_CLASSES.get(pairs[-1][0], frozenset())
    if all(_modifier_compatible(_NOUN_CLASSES.get(part, frozenset()), head_classes) for part, _ in pairs[:-1]):
        return head_classes | {"coordinated_adnominal_head"}
    return _nominal_component_classes(pairs)


def _morpheme_units(tokens, indices, heads, skipped):
    """정규 서술어는 보존하고, 완전한 연속 명사 조각은 하나의 명사구로 묶는다."""
    position = 0
    while position < len(indices):
        index = indices[position]
        if index in skipped:
            position += 1
            continue
        if index in heads:
            head = heads[index]
            yield _Unit(head.form, "NNG", head.start, head.end, index,
                        occurrences=(head.source_occurrences if isinstance(head, _NominalHead)
                                     else _original_occurrences(tokens, (index,))),
                        nominal_source=head.nominal_source if isinstance(head, _NominalHead) else None)
            position += 1
            continue
        token = tokens[index]
        if _tag(token.tag) in _NOMINAL_FRAGMENT_TAGS and all(_tag(tag) in _NOMINAL_FRAGMENT_TAGS for _, tag in (token.morphemes or ((token.form, token.tag),))):
            stop = position + 1
            while stop < len(indices):
                before, after = tokens[indices[stop - 1]], tokens[indices[stop]]
                if before.end != after.start or _tag(after.tag) not in _NOMINAL_FRAGMENT_TAGS:
                    break
                stop += 1
            members = indices[position:stop]
            form = "".join(tokens[item].form for item in members)
            pairs = tuple(pair for item in members for pair in (tokens[item].morphemes or ((tokens[item].form, tokens[item].tag),)))
            tags = tuple(_tag(tokens[item].tag) for item in members)
            common = _complete_common_nominal(tags)
            tag = "NNG" if common else _tag(token.tag)
            registered_proper_noun = len(members) == 1 and tag == "NNP" and tag in _DECLARED_NON_NNG_NOUN_TAGS.get(form, frozenset())
            classes = _nominal_classes(form, tag, pairs) if (common or (len(members) == 1 and tag == "SN") or registered_proper_noun) and _complete_nominal_fragment(tokens, members) else frozenset()
            occurrences = _original_occurrences(tokens, members)
            source = None
            if common and _complete_nominal_fragment(tokens, members):
                source = _complete_nominal_source(tokens, members, form, token.start, tokens[members[-1]].end)
            yield _Unit(form, tag, token.start, tokens[members[-1]].end, index, noun_classes=classes,
                        occurrences=occurrences, nominal_source=source)
            position = stop
            continue
        parts = token.morphemes
        if parts and _complete_common_nominal(tuple(_tag(tag) for _, tag in parts)):
            source = _complete_nominal_source(tokens, (index,), token.form, token.start, token.end)
            classes = _nominal_classes(token.form, "NNG", parts) if source is not None else frozenset()
            if classes:
                yield _Unit(token.form, token.tag, token.start, token.end, index, noun_classes=classes,
                            occurrences=source.source_occurrences, nominal_source=source)
                position += 1
                continue
        for canonical_index, (form, raw_tag) in enumerate(token.morphemes or ((token.form, token.tag),)):
            tags = tuple(_tag(item) for item in raw_tag.split("+"))
            classes = _nominal_classes(form, tags[0], ((form, tags[0]),))
            occurrence = _FunctionalOccurrence(index, canonical_index, form, raw_tag, token.start, token.end,
                                               bool(token.morphemes), token.tag, _token_roles_consistent(token),
                                               _canonical_role_consistent(token, canonical_index),
                                               _canonical_role_consistent(token, canonical_index, prefix_only=True))
            yield _Unit(form, tags[0], token.start, token.end, index,
                        tuple(tag for tag in tags[1:] if tag in _ENDINGS), classes,
                        occurrences=(occurrence,))
        position += 1


def _contiguous(left, right):
    """같은 표면 토큰의 정규형 또는 원문에서 맞닿은 토큰만 연결한다."""
    if left.occurrences and right.occurrences:
        before, after = left.occurrences[-1], right.occurrences[0]
        return before.token_index == after.token_index or before.end == after.start
    return left.token_index == right.token_index or left.end == right.start


def _original_occurrences(tokens, indices):
    """공급 항목의 순번과 겹칠 수 있는 원래 토큰 구간만 읽는다."""
    return tuple(
        _FunctionalOccurrence(index, ordinal, form, raw_tag, tokens[index].start, tokens[index].end,
                              bool(tokens[index].morphemes), tokens[index].tag, _token_roles_consistent(tokens[index]),
                              _canonical_role_consistent(tokens[index], ordinal),
                              _canonical_role_consistent(tokens[index], ordinal, prefix_only=True))
        for index in indices
        for ordinal, (form, raw_tag) in enumerate(tokens[index].morphemes or ((tokens[index].form, tokens[index].tag),))
    )


def _token_roles_consistent(token):
    """원래 전체 태그와 실제 공급 항목열의 모순을 감추지 않는다."""
    if not token.morphemes:
        return True
    whole = tuple(_tag(tag) for tag in token.tag.split("+"))
    supplied = tuple(_tag(tag) for _, raw in token.morphemes for tag in raw.split("+"))
    return whole == supplied


def _canonical_role_consistent(token, ordinal, prefix_only=False):
    """다른 기능 항목의 모순을 실제 본용언 역할에 무차별 복제하지 않는다."""
    if not token.morphemes:
        return True
    parts = tuple(tuple(_tag(tag) for tag in raw.split("+")) for _, raw in token.morphemes)
    offset = sum(len(part) for part in parts[:ordinal])
    whole = tuple(_tag(tag) for tag in token.tag.split("+"))
    if prefix_only:
        required = 2 if parts[ordinal][:2] == ("MAG", "XSV") else 1
        supplied = tuple(tag for part in parts[:ordinal] for tag in part) + parts[ordinal][:required]
        return whole[:offset + required] == supplied
    return whole[offset:offset + len(parts[ordinal])] == parts[ordinal]


def _base_roles_confirmed(occurrences, nominal_source=None):
    """P의 실제 구성 역할과 그 뒤 선택적 기능 꼬리를 구별한다."""
    occurrences = occurrences[_nominal_prefix_role_count(occurrences, nominal_source):]
    for position, occurrence in enumerate(occurrences):
        if not occurrence.core_role_consistent:
            return False
        if occurrence.token_index != occurrences[-1].token_index and not occurrence.token_roles_consistent:
            return False
        roles = _occurrence_tags(occurrence)
        if roles[0] in {"NNG", "XR", "MAG", "EC"}:
            if len(roles) != 1:
                return False
        elif any(role not in {"EP"} | _ENDINGS for role in roles[1:]):
            return False
        if position < len(occurrences) - 1 and (not occurrence.role_consistent or _invalid_functional_order(occurrence)):
            return False
    return bool(occurrences)


def _owned_core_confirmed(prefix, nominal_source=None):
    """마지막 보조 앞의 실제 순서와 보조의 최소 원역할만 확인한다."""
    prefix = prefix[_nominal_prefix_role_count(prefix, nominal_source):]
    if not prefix or not all(item.core_role_consistent for item in prefix):
        return False
    for item in prefix[:-1]:
        roles = _occurrence_tags(item)
        if item.token_index != prefix[-1].token_index and not item.token_roles_consistent:
            return False
        if not item.role_consistent or _invalid_functional_order(item):
            return False
        if roles[0] in {"NNG", "XR", "MAG", "EC"} and len(roles) != 1:
            return False
    last = _occurrence_tags(prefix[-1])
    count = 2 if last[:2] == ("MAG", "XSV") else 1
    return all(role in {"EP"} | _ENDINGS for role in last[count:])


def _invalid_functional_order(occurrence):
    roles = _occurrence_tags(occurrence)
    suffix_roles = roles[2:] if roles[:2] == ("MAG", "XSV") else roles[1:]
    endings = [index for index, role in enumerate(suffix_roles) if role in _ENDINGS]
    return (any(role not in {"EP"} | _ENDINGS for role in suffix_roles)
            or len(endings) > 1 or bool(endings and endings[0] != len(suffix_roles) - 1))


def _occurrence_tags(occurrence):
    return tuple(_tag(tag) for tag in occurrence.raw_tag.split("+"))


def _functional_neighbors(left, right):
    """공급 순서와 실제 절ㆍ인용 소유 안의 정상 간격만 허가한다."""
    if left.occurrences and right.occurrences:
        before, after = left.occurrences[-1], right.occurrences[0]
        if (before.token_index, before.canonical_index) >= (after.token_index, after.canonical_index):
            return False
    ownership = _QUOTE_OWNERSHIP.get()
    if ownership is None:
        return left.end <= right.start or left.token_index == right.token_index
    if ownership.chain((left.start, left.end)) != ownership.chain((right.start, right.end)):
        return False
    start, end = min(left.start, right.start), max(left.end, right.end)
    if any(start < cut < end for cut in ownership.hard_boundaries):
        return False
    if left.end <= right.start and ownership.text[left.end:right.start].strip():
        return False
    return ownership.chain((start, end)) is not None


def _attached_auxiliary(left, right):
    """못/MAG+하/XSV의 원래 단어 내부 부착을 별도로 확인한다."""
    return _contiguous(left, right) and _functional_neighbors(left, right)


def _unit_prefinals(unit):
    return tuple(occurrence for occurrence in unit.occurrences if "EP" in _occurrence_tags(occurrence))


def _long_negative_readings(base_tag, auxiliary):
    if auxiliary in {"않", "아니하"}:
        return frozenset({"R2" if base_tag in {"VA", "XSA"} else "R1"})
    if auxiliary == "못하":
        return frozenset({"R5"}) if base_tag in {"VA", "XSA"} else frozenset({"R3", "R4"})
    return frozenset({"R6"})


def _eligible_state_reading(base):
    """기존에 선언된 상태 읽기 없이 모든 VA의 미흡 용법을 인증하지 않는다."""
    if base.form in _NEUTRAL_RELATIVES or base.form in _PRICE_COMPARISONS:
        return True
    if any(not frame.predicate_tag or frame.predicate_tag == base.tag for frame in _FRAMES.get(base.form, ())):
        return True
    return any(base.form in frame.predicates and base.tag in frame.tags
               for frame in _NEUTRAL_FRAMES + _INHERENT_HEAD_NEUTRAL_FRAMES)


def _relative_ending_kind(final):
    """실제 어미형이 없는 복합 태그를 직접 관형형으로 복원하지 않는다."""
    if final is None or final[1] != "ETM":
        return "none"
    occurrence, _ = final
    if _occurrence_tags(occurrence)[0] != "ETM":
        return "unknown"
    if occurrence.form in {"다는", "단", "라는", "란", "냐는", "냔", "자는", "잔", "으라는", "으란"}:
        return "reported"
    if occurrence.form in {"ㄴ", "은", "는", "ㄹ", "을", "던", "은던"}:
        return "direct"
    return "unknown"


def _compose_long_negative_complexes(units):
    """실제 P부터 마지막 기능 어미까지 먼저 소비하여 빈 보조 사건을 막는다."""
    units = tuple(units)
    position = 0
    while position < len(units):
        base = units[position]
        if base.long_negative is not None or base.tag not in {"VV", "VA", "XSV", "XSA"} or base.endings:
            yield base
            position += 1
            continue
        cursor = position + 1
        previous = base
        prefinals = list(_unit_prefinals(base))
        while cursor < len(units) and units[cursor].tag == "EP" and not units[cursor].endings and _functional_neighbors(previous, units[cursor]):
            previous = units[cursor]
            prefinals.extend(previous.occurrences)
            cursor += 1
        operators = []
        core_prefixes = []
        readings = []
        consumed = list(units[position:cursor])
        final = None
        unresolved = []
        unlicensed_readings = []
        while cursor + 1 < len(units):
            connector = units[cursor]
            if connector.tag != "EC" or connector.endings or not _functional_neighbors(previous, connector):
                break
            auxiliary = units[cursor + 1]
            auxiliary_end = cursor + 2
            operator = (connector, auxiliary)
            auxiliary_form = auxiliary.form
            if not _functional_neighbors(connector, auxiliary):
                break
            modal = connector.form != "지" and bool(operators) and any(
                base.tag in construction.base_tags and connector.form in construction.connector_forms
                and connector.tag == construction.connector_tag and auxiliary.tag == construction.auxiliary_tag
                and auxiliary.form in construction.auxiliary_forms
                for construction in _VERB_COMPLEXES
            )
            if connector.form != "지" and not modal:
                break
            complete_attached = (
                auxiliary.tag == "MAG" and auxiliary.form == "못하" and len(auxiliary.occurrences) == 1
                and auxiliary.occurrences[0].canonical_supplied
                and _occurrence_tags(auxiliary.occurrences[0])[:2] == ("MAG", "XSV")
                and all(role in {"EP", "EF", "EC", "ETM", "ETN"} for role in _occurrence_tags(auxiliary.occurrences[0])[2:])
            )
            if modal:
                pass
            elif complete_attached:
                auxiliary_form = "못하"
            elif auxiliary.tag == "MAG" and auxiliary.form == "못" and not auxiliary.endings:
                if auxiliary_end >= len(units):
                    break
                suffix = units[auxiliary_end]
                if suffix.tag != "XSV" or suffix.form != "하" or not _attached_auxiliary(auxiliary, suffix):
                    break
                operator = (connector, auxiliary, suffix)
                auxiliary_form = "못하"
                auxiliary = suffix
                auxiliary_end += 1
            elif auxiliary.tag != "VX" or auxiliary.form not in {"않", "아니하", "못하", "말"}:
                break
            operators.append(tuple(occurrence for unit in operator for occurrence in unit.occurrences))
            readings.append(frozenset({"U2"}) if modal else _long_negative_readings(base.tag, auxiliary_form))
            if not modal and auxiliary_form == "못하" and base.tag in {"VA", "XSA"} and not _eligible_state_reading(base):
                unlicensed_readings.append("R5")
            consumed.extend(operator)
            core_prefixes.append(tuple(item for unit in consumed for item in unit.occurrences))
            prefinals.extend(_unit_prefinals(auxiliary))
            cursor = auxiliary_end
            previous = auxiliary
            if auxiliary.endings:
                roles = auxiliary.endings
                final = (auxiliary.occurrences[-1], roles[-1]) if auxiliary.occurrences else None
                if len(roles) != 1:
                    unresolved.append("contradictory_final_roles")
                break
            while cursor < len(units) and units[cursor].tag == "EP" and _functional_neighbors(previous, units[cursor]):
                previous = units[cursor]
                consumed.append(previous)
                prefinals.extend(previous.occurrences)
                cursor += 1
                if previous.endings:
                    final = (previous.occurrences[-1], previous.endings[-1]) if previous.occurrences else None
                    if len(previous.endings) != 1:
                        unresolved.append("contradictory_final_roles")
                    break
            if final is not None:
                break
            if cursor < len(units) and units[cursor].tag in _ENDINGS and _functional_neighbors(previous, units[cursor]):
                tail = units[cursor]
                # 반복 지는 다음 연산자와 함께 소비하고 일반 EC로 닫지 않는다.
                modal_tail = cursor + 1 < len(units) and any(
                    base.tag in construction.base_tags and tail.form in construction.connector_forms
                    and tail.tag == construction.connector_tag
                    and units[cursor + 1].tag == construction.auxiliary_tag
                    and units[cursor + 1].form in construction.auxiliary_forms
                    for construction in _VERB_COMPLEXES
                )
                if tail.tag == "EC" and (tail.form == "지" or modal_tail):
                    continue
                consumed.append(tail)
                final = (tail.occurrences[0], tail.tag) if tail.occurrences else None
                if tail.endings:
                    unresolved.append("contradictory_final_roles")
                cursor += 1
            break
        if not operators:
            yield base
            position += 1
            continue
        if final is None:
            unresolved.append("missing_owned_final")
        relative_kind = _relative_ending_kind(final)
        if relative_kind == "unknown":
            unresolved.append("relative_reading")
        for operator, reading in zip(operators, readings):
            if "R6" not in reading or final is None:
                continue
            ending, ending_tag = final
            actual_form = ending.form if _occurrence_tags(ending)[0] == ending_tag else ""
            command = ending_tag == "EF" and actual_form in {"아", "어", "라", "아라", "어라", "으라", "자", "읍시다", "ㅂ시다", "세요", "으세요", "십시오", "으십시오", "아요", "어요"}
            quoted = (ending_tag == "ETM" and relative_kind == "reported" and actual_form in {"라는", "란", "으라는", "으란", "자는", "잔"}) or (ending_tag == "EC" and actual_form in {"라고", "라", "으라고", "자고"})
            command_link = ending_tag == "EC" and actual_form == "고"
            if not command and not quoted and not command_link:
                unlicensed_readings.append("R6")
        occurrences = tuple(occurrence for unit in consumed for occurrence in unit.occurrences)
        for occurrence in occurrences:
            if not occurrence.token_roles_consistent:
                unresolved.append("supplied_role_mismatch")
            if _invalid_functional_order(occurrence):
                unresolved.append("functional_role_order")
        prefinals = [occurrence for occurrence in occurrences if "EP" in _occurrence_tags(occurrence)]
        base_occurrences = base.occurrences
        root_occurrences = ()
        nominal_source = None
        start = base.start
        if base.tag in {"XSV", "XSA"} and position and units[position - 1].tag in {"NNG", "XR"} and _nominal_source_attached(units[position - 1], base):
            root = units[position - 1]
            base_occurrences = root.occurrences + base_occurrences
            root_occurrences = root.occurrences
            nominal_source = root.nominal_source
            start = root.start
        end = max(unit.end for unit in consumed)
        core_end = -1
        confirmed_prefixes = 0
        for prefix in core_prefixes:
            if not _owned_core_confirmed(root_occurrences + prefix, nominal_source):
                break
            core_end = max(item.end for item in root_occurrences + prefix)
            confirmed_prefixes += 1
        if core_end >= 0 and confirmed_prefixes == len(core_prefixes) and all(
            item.role_consistent and not _invalid_functional_order(item) for item in occurrences
        ):
            core_end = end
        complex_state = _LongNegativeComplex(base_occurrences, tuple(operators), tuple(dict.fromkeys(prefinals)),
                                             final, tuple(readings), relative_kind,
                                             tuple(dict.fromkeys(unresolved)), start, end,
                                             licensed=core_end >= 0,
                                             unlicensed_readings=tuple(dict.fromkeys(unlicensed_readings)),
                                             base_unresolved=not _base_roles_confirmed(base_occurrences, nominal_source), core_end=core_end,
                                             nominal_source=nominal_source)
        yield replace(base, end=end, endings=((final[1],) if final is not None else ()),
                      occurrences=occurrences, long_negative=complex_state)
        position = max(position + 1, cursor)


def _compose_verb_complexes(units):
    """선언된 연속 구성만 하나의 서술어로 묶어 원래 논항 소유를 보존한다."""
    units = tuple(units)
    position = 0
    while position < len(units):
        base = units[position]
        cursor = position + 1
        while cursor + 1 < len(units):
            connector, auxiliary = units[cursor:cursor + 2]
            combined = None
            for construction in _VERB_COMPLEXES:
                if (
                    base.tag in construction.base_tags
                    and connector.tag == construction.connector_tag
                    and connector.form in construction.connector_forms
                    and auxiliary.tag == construction.auxiliary_tag
                    and auxiliary.form in construction.auxiliary_forms
                    and not base.endings and not connector.endings
                    and _contiguous(base, connector) and _functional_neighbors(connector, auxiliary)
                ):
                    combined = _Unit(
                        base.form + connector.form + auxiliary.form,
                        construction.result_tag, base.start, auxiliary.end,
                        base.token_index, auxiliary.endings,
                        occurrences=base.occurrences + connector.occurrences + auxiliary.occurrences,
                    )
                    break
            if combined is None:
                break
            base = combined
            cursor += 2
        yield base
        position = cursor


def _emit(evidence, mention, relation, start, end, semantic_class):
    """적격 대상의 정확한 구간에만 관계 근거를 추가한다."""
    ownership = _QUOTE_OWNERSHIP.get()
    if ownership is not None:
        ownership.observe(mention, ((start, end),))
        if relation == "unresolved_long_negative_complex" and (mention.start, mention.end, start, end) not in ownership.domain_unresolved:
            ownership.long_negative_unresolved.setdefault((mention.start, mention.end), set()).add((start, end))
    if mention.token_index in evidence:
        item = SenseEvidence(relation, mention.start, mention.end, start, end, semantic_class)
        if item not in evidence[mention.token_index]:
            evidence[mention.token_index].append(item)


def _unique_argument(event, role):
    """같은 역할의 독립 명사구가 여러 개면 소유 관계를 단정하지 않는다."""
    groups = [argument for argument in event.arguments if argument.role == role]
    return groups[0] if len(groups) == 1 else None


def _has_inherent_type(mention, classes):
    """현재 명사의 어휘 핵어에서 직접 확인된 유형만 반환한다."""
    required = frozenset(classes)
    return bool(mention.noun_classes & required) and any(
        fact_class in required
        and relation == "lexical_nominal_head"
        and start == mention.start
        and end == mention.end
        for fact_class, relation, start, end in mention.facts
    )


def _support(event, frame, target=None):
    """추가 의미 조건을 만족하는 실제 논항 명사를 반환한다."""
    if not frame.support_role:
        return ()
    argument = _unique_argument(event, frame.support_role)
    if argument is None:
        return None
    if frame.require_coordination:
        if target is None or len(argument.members) < 2 or not any(member is target for member in argument.members):
            return None
        if any(member.owned or member.noun_classes & {"unresolved_modifier", "unresolved_relation"} for member in argument.members):
            return None
        if any(member is not target and not _has_inherent_type(member, {frame.support_class}) for member in argument.members):
            return None
        members = tuple(member for member in argument.members if member is not target and _has_inherent_type(member, {frame.support_class}))
        return members or None
    if frame.support_class:
        members = tuple(member for member in argument.members if frame.support_class in member.noun_classes)
        if frame.support_unowned and any(member.owned for member in members):
            return None
        return members or None
    members = argument.members
    if not members or any(member.owned or member.noun_classes & {"unresolved_modifier", "unresolved_relation"} for member in members):
        return None
    return members


def _apply_frame(evidence, event, frame, members):
    """선언된 틀을 충족하는 관계만 구체적인 출현에 적용한다."""
    if not frame.required_adjuncts <= frozenset(event.adjuncts):
        return False
    support = None if frame.require_coordination else _support(event, frame)
    if not frame.require_coordination and support is None:
        return False
    supported = False
    for member in members:
        if frame.require_owned and (not member.owned or not member.owners):
            continue
        member_support = _support(event, frame, member) if frame.require_coordination else support
        if member_support is None:
            continue
        possible = frozenset(
            semantic_class
            for sense in _SENSES_BY_SPELLING.get(member.form, ())
            for semantic_class in SENSE_FEATURES[sense].semantic_classes
        )
        permitted = frame.classes
        if event.long_negative is not None:
            # 거절된 P의 효과로 독립 명사 허가를 재발행하지 않는다.
            if not _long_negative_effect_source(event, frame, member, member_support):
                continue
            permitted = _long_negative_frame_classes(event, frame, member, member_support)
            permitted = frozenset(value for value in permitted if not _long_negative_required_base(evidence, event, member, value))
            broad_domain = frame.broad_domain if frame.effect_kind in {"lexical_domain", "narrowing_domain"} else ""
            if permitted or broad_domain:
                supported = _emit_domain_restriction(evidence, member, permitted, event, _long_negative_frame_role(frame),
                                                     member_support, relative=frame.role == "head",
                                                     observed_domains=((broad_domain,) if broad_domain else ())) or supported
            continue
        for semantic_class in sorted(permitted & possible):
            if _long_negative_required_base(evidence, event, member, semantic_class):
                continue
            supported = True
            _emit(evidence, member, frame.relation, event.start, event.end, semantic_class)
            for anchor in member_support:
                _emit(evidence, member, frame.relation + "_support", anchor.start, anchor.end, semantic_class)
    return supported


def _independent_domain(mention, semantic_class):
    """가능 뜻 합집합 대신 실제 명사 출처의 도메인만 읽는다."""
    if mention.noun_classes & {"unresolved_modifier", "unresolved_relation"}:
        return False
    return any(value == semantic_class or _TYPE_EFFECTS.get(value) == semantic_class
               or _DIRECT_HEAD_EFFECTS.get(value) == semantic_class
               for value in mention.noun_classes)


def _long_negative_frame_classes(event, frame, member, support):
    """관계 효과와 실제 출처를 먼저 검사하며 선행 목표 유형을 요구하지 않는다."""
    if not _long_negative_effect_source(event, frame, member, support):
        return frozenset()
    independent = {value for value in frame.classes if _independent_domain(member, value)}
    if frame.effect_kind == "lexical_domain" and not frame.narrowing:
        return frame.classes
    if frame.effect_kind == "derived_nominal":
        return frame.classes
    if frame.effect_kind in {"owned_domain", "narrowing_domain"}:
        return frozenset(independent | _direct_part_owner_domains(event, frame, support)
                         | {value for value in frame.classes if _owned_domain_source(member, value, support)})
    return frozenset()


def _long_negative_frame_role(frame):
    """원래 직접 부분 소유 역할을 일반 격의 빈자리와 구별한다."""
    if frame.role != "head":
        return frame.role
    if frame.head_role:
        return frame.head_role
    if (frame.relation == "relative_part_owner" and frame.support_role
            and frame.support_class and frame.support_unowned):
        return "direct_part_owner"
    return ""


def _direct_part_owner_domains(event, frame, support):
    """선행 목표 유형 대신 실제 직접 관형 부분의 기존 소유 대응을 읽는다."""
    state = event.long_negative
    if (state is None or state.relative_kind != "direct" or state.unresolved_dependencies
            or frame.effect_kind != "owned_domain"
            or _long_negative_frame_role(frame) != "direct_part_owner"):
        return frozenset()
    actual = _support(event, frame)
    if not actual or tuple(support) != actual or any(
        source.owned or source.noun_classes & {"unresolved_modifier", "unresolved_relation"}
        for source in actual
    ):
        return frozenset()
    return frozenset(frame.classes & {
        _GENITIVE_EFFECTS[value]
        for source in actual for value in source.noun_classes if value in _GENITIVE_EFFECTS
    })


def _long_negative_effect_source(event, frame, member, support):
    """공유 효과 선언과 그 효과가 실제 요구하는 출처를 확인한다."""
    role = _long_negative_frame_role(frame)
    if not frame.effect_kind or not role or event.long_negative is None:
        return False
    if frame.effect_kind not in {"lexical_domain", "derived_nominal", "owned_domain", "narrowing_domain"}:
        return False
    producers = _FRAMES.get(event.predicate, ())
    original = replace(frame, relation="predicate_argument", role=role, head_role="") if frame.role == "head" and frame.head_role else frame
    if frame not in producers and original not in producers:
        return False
    required = {"predicate", "argument"}
    if frame.support_role:
        required.add("support")
    if frame.require_owned:
        required.add("owner")
    if frame.effect_kind == "derived_nominal":
        required.add("root_suffix")
    if not required <= frozenset(frame.effect_dependencies):
        return False
    if frame.predicate_tag and frame.predicate_tag != event.tag:
        return False
    for dependency in frame.effect_dependencies:
        if dependency not in {"predicate", "argument", "support", "owner", "root_suffix"}:
            return False
        if dependency == "predicate" and (not event.long_negative.base_occurrences or event.long_negative.base_unresolved):
            return False
        if dependency == "argument":
            if frame.role == "head":
                if event.long_negative.relative_kind != "direct" or event.long_negative.unresolved_dependencies:
                    return False
                if not frame.head_role and not _direct_part_owner_domains(event, frame, support):
                    return False
            elif not any(item.role == role and any(target is member for target in item.members) for item in event.arguments):
                return False
        if dependency == "support" and (not support or any(item.noun_classes & {"unresolved_modifier", "unresolved_relation"} for item in support)):
            return False
        if dependency == "owner" and (not member.owners or member.noun_classes & {"unresolved_modifier", "unresolved_relation"}):
            return False
        if dependency == "root_suffix":
            if role != "incorporated_object" or not _nominal_root_suffix_source(event, member):
                return False
    return True


def _nominal_root_suffix_source(event, member):
    """원래 전체 명사 키ㆍ완전한 성분열ㆍ실제 접미사의 대응만 소비한다."""
    original = event.long_negative.base_occurrences
    if event.tag != "XSV" or len(original) < 2:
        return False
    roots, suffix = original[:-1], original[-1]
    if (suffix.form != event.predicate or _occurrence_tags(suffix)[0] != "XSV"
            or not suffix.core_role_consistent):
        return False
    if (member.token_index != roots[0].token_index
            or not _nominal_source_correspondence(member.form, member.start, member.end, roots,
                                                  event.long_negative.nominal_source)):
        return False
    for left, right in zip(original, original[1:]):
        if left.token_index == right.token_index:
            if right.canonical_index != left.canonical_index + 1:
                return False
        elif left.token_index >= right.token_index or left.end != right.start:
            return False
    return True


def _nominal_source_correspondence(form, start, end, occurrences, source=None, require_roles=True):
    """허가된 전체 명사 출처 또는 원래 단일 일반명사의 완전 대응만 확인한다."""
    if (not occurrences or (start, end) != (occurrences[0].start, occurrences[-1].end)
            or "".join(item.form for item in occurrences) != form):
        return False
    if source is not None:
        if (not isinstance(source, _NominalSource) or (form, start, end) != (source.form, source.start, source.end)
                or tuple(occurrences) != source.source_occurrences
                or tuple((item.form, item.raw_tag) for item in occurrences) != source.morphemes):
            return False
    elif len(occurrences) != 1 or _occurrence_tags(occurrences[0]) != ("NNG",):
        # 조립 출처를 잃은 여러 항목의 문자열 합치기로 허가를 대신하지 않는다.
        return False
    roles = tuple(_occurrence_tags(item) for item in occurrences)
    if (occurrences[0].canonical_index != 0 or any(len(role) != 1 for role in roles)
            or not _complete_common_nominal(tuple(role[0] for role in roles))
            or (require_roles and any(not item.role_consistent or not item.token_roles_consistent for item in occurrences)
                and not _nominal_source_roles_confirmed(source))):
        return False
    for left, right in zip(occurrences, occurrences[1:]):
        if left.token_index == right.token_index:
            if right.canonical_index != left.canonical_index + 1:
                return False
        elif left.token_index >= right.token_index or left.end != right.start or right.canonical_index != 0:
            return False
    return True


def _complete_nominal_source(tokens, members, form, start, end):
    """이미 허가된 두 명사 생산자에 같은 실제 원천ㆍ역할 증명을 만든다."""
    occurrences = _original_occurrences(tokens, members)
    pairs = tuple((item.form, item.raw_tag) for item in occurrences)
    original_tokens = tuple((item, tokens[item].form, tokens[item].tag, tokens[item].start,
                             tokens[item].end, tokens[item].morphemes) for item in members)
    source = _NominalSource(form, start, end, pairs, occurrences, original_tokens)
    return source if _nominal_source_roles_confirmed(source) else None


def _nominal_source_roles_confirmed(source):
    """공통 생산자의 완전 명사 역할과 정확한 외부 NNG 포장 차이만 확인한다."""
    if not isinstance(source, _NominalSource) or not _nominal_source_correspondence(
        source.form, source.start, source.end, source.source_occurrences, source, require_roles=False
    ):
        return False
    position = 0
    for token_index, form, raw_tag, start, end, supplied in source.token_sources:
        parts = supplied or ((form, raw_tag),)
        rows = source.source_occurrences[position:position + len(parts)]
        if (len(rows) != len(parts) or tuple((row.form, row.raw_tag) for row in rows) != parts
                or tuple(row.canonical_index for row in rows) != tuple(range(len(parts)))
                or any((row.token_index, row.token_tag, row.start, row.end, row.canonical_supplied)
                       != (token_index, raw_tag, start, end, bool(supplied)) for row in rows)
                or "".join(part for part, _ in parts) != form):
            return False
        if any(not row.role_consistent or not row.token_roles_consistent or not row.core_role_consistent for row in rows):
            # 기존 명사 생산자가 허가한 원래 NNG 한 항의 다중 명사
            # 성분 포장만 논리 역할로 설명한다. 기능 역할/미상 태그는 포함하지 않는다.
            roles = tuple(_occurrence_tags(row) for row in rows)
            if (_tag(raw_tag) != "NNG" or len(rows) < 2
                    or any(len(role) != 1 for role in roles)
                    or not _complete_common_nominal(tuple(role[0] for role in roles))):
                return False
        position += len(parts)
    return position == len(source.source_occurrences)


def _nominal_prefix_role_count(occurrences, source):
    """확인한 명사 접두 성분만 구별하고 실제 P/연결/보조 역할 검사는 남긴다."""
    if (not isinstance(source, _NominalSource) or len(source.source_occurrences) >= len(occurrences)
            or tuple(occurrences[:len(source.source_occurrences)]) != source.source_occurrences
            or not _nominal_source_roles_confirmed(source)):
        return 0
    return len(source.source_occurrences)


def _nominal_source_attached(root, suffix):
    """기존 뿌리 역할과 완전한 명사 원천이 실제 접미사에 소유ㆍ부착되는지 본다."""
    if not _contiguous(root, suffix) or not _functional_neighbors(root, suffix):
        return False
    if root.tag == "XR":
        return True
    return root.tag == "NNG" and _nominal_source_correspondence(
        root.form, root.start, root.end, root.occurrences, root.nominal_source, require_roles=False
    )


def _owned_domain_source(target, value, sources):
    """원래 명시 소유가 있는 부분/분야 출처만 도메인으로 사용한다."""
    for source in sources:
        if source.noun_classes & {"unresolved_modifier", "unresolved_relation"}:
            continue
        if not any(owner.token_index == target.token_index and (owner.start, owner.end) == (target.start, target.end) for owner in source.owners):
            continue
        if any(_GENITIVE_EFFECTS.get(item) == value for item in source.noun_classes):
            return True
    return False


def _is_reading_restriction(item):
    return item.relation.startswith("lexical_domain_restriction/")


def _is_domain_observation(item):
    return item.relation.startswith("lexical_domain_observation/")


def _is_domain_effect(item):
    return _is_reading_restriction(item) or _is_domain_observation(item)


def _emit_domain_restriction(evidence, target, domains, event, role, sources=(), relative=False, observed_domains=(), source_kind=""):
    """한 출처의 어휘 읽기 대안만 반환하고 명사 확정 유형에 합치지 않는다."""
    sources = tuple(sources)
    if event is None and source_kind != "nominal":
        return False
    ownership = _QUOTE_OWNERSHIP.get()
    if ownership is not None:
        for source in sources:
            ownership.observe(target, ownership.mention_spans(source))
    unresolved_sources = [source for source in sources if source.noun_classes & {"unresolved_modifier", "unresolved_relation"}]
    if unresolved_sources:
        for source in unresolved_sources:
            facts = [fact for fact in source.facts if fact[0] in {"unresolved_modifier", "unresolved_relation"}]
            if facts:
                for value, relation, start, end in facts:
                    _emit(evidence, target, relation, start, end, value)
            else:
                _emit(evidence, target, "unresolved_long_negative_complex", source.start, source.end, "unresolved_relation")
        return False
    state = event.long_negative if event is not None else None
    nominal = source_kind == "nominal"
    original = tuple((row.token_index, row.canonical_index) for row in state.base_occurrences) if state is not None and not nominal else ()
    identity = (original, "" if nominal else event.predicate, "" if nominal else event.tag, role,
                tuple((item.token_index, item.start, item.end) for item in sources), tuple(sorted(observed_domains)))
    # 출처 신원은 공개 필드 추가 없이 관계 문자열에 들어간다. 같은 앵커의
    # 독립 출처를 합치거나 지지 앵커를 별도 강한 단정으로 세지 않는다.
    source_id = repr(identity).encode("utf-8").hex()
    kind = "nominal" if nominal else "relative" if relative else "argument"
    anchor_start, anchor_end = (target.start, target.end) if nominal else (event.start, event.end)
    relation = "lexical_domain_restriction/" + kind + "/" + source_id
    values = frozenset(_target_class_constraint(target, value) for value in domains)
    observations = frozenset(observed_domains)
    alternatives = {sense for sense in _SENSES_BY_SPELLING.get(target.form, ())
                    if SENSE_FEATURES[sense].semantic_classes & values}
    if observations or not alternatives:
        observation = "lexical_domain_observation/" + kind + "/" + source_id
        for value in sorted(observations or values):
            _emit(evidence, target, observation, anchor_start, anchor_end, value)
            for source in sources:
                _emit(evidence, target, observation, source.start, source.end, value)
        if not alternatives:
            return False
    for sense in sorted(alternatives):
        for value in sorted(SENSE_FEATURES[sense].semantic_classes & values):
            _emit(evidence, target, relation, anchor_start, anchor_end, value)
            for source in sources:
                _emit(evidence, target, relation, source.start, source.end, value)
    return True


def _long_negative_mentions(event):
    """실제 논항과 그 명시 소유ㆍ부착 성분만 순환 없이 펼친다."""
    pending = [member for argument in event.arguments for member in argument.members]
    seen = set()
    while pending:
        member = pending.pop()
        identity = (member.token_index, member.start, member.end)
        if identity in seen:
            continue
        seen.add(identity)
        yield member
        pending.extend(member.owners)
        pending.extend(item for argument in member.bound_arguments for item in argument.members)


def _long_negative_structure(evidence, event, head=None, unresolved=False):
    """실제 참여 대상의 구조 관찰과 필수 의존 미결을 별도로 기록한다."""
    state = event.long_negative
    if state is None:
        return head
    targets = (head,) if head is not None else tuple(_long_negative_mentions(event))
    needed = bool(state.unresolved_dependencies) if head is not None else False
    for target in targets:
        if state.licensed:
            _emit(evidence, target, "licensed_long_negative_complex", state.start, state.core_end,
                  "nonassertive_predicate_complex")
        if needed or unresolved:
            _relative_domain_dependency(evidence, event, target)
    return head


def _relative_domain_dependency(evidence, event, target):
    """관형 연결 C를 원래 명사 신원 C와 분리하여 실제 의존에만 쓴다."""
    state = event.long_negative
    ownership = _QUOTE_OWNERSHIP.get()
    if ownership is not None:
        ownership.domain_unresolved.add((target.start, target.end, state.start, state.end))
    _emit(evidence, target, "unresolved_long_negative_complex", state.start, state.end, "unresolved_relation")
    return target


def _long_negative_required_base(evidence, event, target, semantic_class):
    """실제 P 역할을 필요로 하는 해당 추론만 C로 남긴다."""
    state = event.long_negative
    if state is None or not state.base_unresolved or _independent_domain(target, semantic_class):
        return False
    _relative_domain_dependency(evidence, event, target)
    return True


def _long_negative_event_domains(evidence, event, quote_mode=False):
    """부정된 행동의 실현 없이 독립 가격ㆍ언어ㆍ소유 도메인을 유지한다."""
    if event.long_negative is None:
        return
    _long_negative_derivation_relations(evidence, event)
    _long_negative_structure(evidence, event)
    if quote_mode:
        return
    _long_negative_owned_domains(evidence, event)
    speech = _speech_ability_arguments(event)
    if speech:
        medium = _unique_argument(event, "via")
        for target in medium.members:
            if not _long_negative_required_base(evidence, event, target, "speech_ability"):
                _emit_domain_restriction(evidence, target, {"speech_ability"}, event, "linguistic_instrument", speech)
    _transaction_relations(evidence, event)
    if event.predicate in _PRICE_COMPARISONS and event.tag == "VA":
        subject = _role_or_topic(event, "subject", True)
        comparison = _unique_argument(event, "comparison")
        if subject is not None and comparison is not None and comparison.particle_form == "보다":
            for targets, sources in ((subject.members, comparison.members), (comparison.members, subject.members)):
                if sources and all(_independent_domain(source, "price") for source in sources):
                    for target in targets:
                        if _long_negative_required_base(evidence, event, target, "price"):
                            continue
                        _emit_group_type(evidence, target, sources, {"price": "price"}, "typed_price_comparison", event)
    if event.predicate in _HUMAN_PARTICIPANT_PREDICATES and event.tag in {"VV", "XSV"}:
        argument = _role_or_topic(event, "subject", True)
        if argument is None and not any(item.role in {"subject", "topic"} for item in event.arguments):
            argument = _unique_argument(event, "focus")
        if argument is not None:
            for target in argument.members:
                if "minority_quantity" in _possible_classes(target):
                    if _long_negative_required_base(evidence, event, target, "minority_quantity"):
                        continue
                    _emit_domain_restriction(evidence, target, {"minority_quantity"}, event, "human_participant")


def _long_negative_owned_domains(evidence, event):
    for argument in event.arguments:
        for source in argument.members:
            if source.noun_classes & {"unresolved_modifier", "unresolved_relation"}:
                continue
            domains = {_GENITIVE_EFFECTS[value] for value in source.noun_classes if value in _GENITIVE_EFFECTS}
            for owner in source.owners:
                if domains:
                    _emit_domain_restriction(evidence, owner, domains, event, "owned_nominal", (source,), source_kind="nominal")


def _long_negative_relative_domains(evidence, event, head):
    """이 연결이 필요한 근거만 처리하며 원래 소유는 별도 함수에서 읽는다."""
    _comparison_relative(evidence, event, head)
    population = _unique_argument(event, "population")
    if population is not None and not any(member.noun_classes & {"unresolved_modifier", "unresolved_relation"} for member in population.members):
        effects = _group_effects(population.members, _DIRECT_HEAD_EFFECTS)
        if head.noun_classes & {"part_head", "part_group", "group_head"} and effects:
            _emit_domain_restriction(evidence, head, effects, event, "population_domain", population.members, relative=True)
        if "number_head" in head.noun_classes and _valid_members(population, {"natural_number"}):
            _emit_domain_restriction(evidence, head, {"natural_number"}, event, "number_domain", population.members, relative=True)
    subject = _unique_argument(event, "subject")
    location = _unique_argument(event, "location")
    if "number_head" in head.noun_classes and _valid_members(subject, {"digit_head"}) and _valid_members(location, {"decimal_below_position"}) and location.particle_form == "에":
        _emit_domain_restriction(evidence, head, {"decimal_number"}, event, "digit_position_domain", subject.members + location.members, relative=True)


def _long_negative_original_head_domains(evidence, event, head):
    """관형 연결과 독립인 실제 원래 핵어/소유 출처만 먼저 유지한다."""
    if head.noun_classes & {"unresolved_modifier", "unresolved_relation"}:
        return
    if "population_part" not in head.noun_classes or not head.owners:
        return
    owners = head.owners
    if any(owner.noun_classes & {"unresolved_modifier", "unresolved_relation"} for owner in owners):
        return
    effects = _group_effects(owners, _DIRECT_HEAD_EFFECTS)
    if effects:
        _emit_domain_restriction(evidence, head, effects, event, "owned_population_domain", owners, source_kind="nominal")


def _long_negative_derivation_relations(evidence, event):
    """시도된 복합체에서 실제 등록 prefix 자체의 모순만 보존한다."""
    original = event.long_negative.base_occurrences
    if len(original) < 2:
        return
    roots, suffix = original[:-1], original[-1]
    declaration = _registered_nominal_declaration(roots, suffix, event.long_negative.nominal_source)
    if declaration is None or _registered_nominal_prefix_confirmed(roots, suffix, event.long_negative.nominal_source):
        return
    target = _Mention(roots[0].token_index, declaration.root, roots[0].start, roots[-1].end)
    for value in SENSE_FEATURES[declaration.sense_id].semantic_classes:
        independent = any(item.semantic_class == value for item in evidence.get(target.token_index, ()))
        if not independent:
            _emit(evidence, target, "unresolved_long_negative_complex", event.long_negative.start,
                  event.long_negative.end, "unresolved_relation")


def _long_negative_relative_roles(event, head):
    """기존 선언의 실제 빈 격과 직접 명사 소유 역할을 구별하여 읽는다."""
    roles = set()
    for frame in _FRAMES.get(event.predicate, ()):
        if frame.predicate_tag and frame.predicate_tag != event.tag:
            continue
        role = _long_negative_frame_role(frame)
        if role and role != "incorporated_object" and not any(argument.role == role for argument in event.arguments):
            if frame.required_adjuncts <= frozenset(event.adjuncts) and _support(event, frame) is not None:
                roles.add(role)
    for construction in _MEMBERSHIP_CONSTRUCTIONS:
        if event.predicate not in construction.predicates or event.tag not in {"VV", "XSV"}:
            continue
        if _unique_argument(event, construction.member_role) is not None and not any(argument.role == construction.target_role for argument in event.arguments):
            roles.add(construction.target_role)
        if _unique_argument(event, construction.target_role) is not None and not any(argument.role in {construction.member_role, "topic"} for argument in event.arguments):
            roles.add(construction.member_role)
    classification = _classification_parts(event)
    if classification is not None:
        frame, members, category = classification
        if members is None and not any(argument.role == frame.member_role or (frame.allow_topic and argument.role == "topic") for argument in event.arguments):
            roles.add(frame.member_role)
    definition = next((frame for frame in _DEFINITION_FRAMES if event.tag in {"VV", "XSV"}
                       and event.predicate in frame.predicates and not any(argument.role in frame.forbidden_roles for argument in event.arguments)), None)
    if definition is not None:
        subject = _role_or_topic(event, "subject", True)
        objects = _unique_argument(event, "object")
        if objects is not None and subject is None:
            roles.add("subject")
        if subject is not None and objects is None and definition.allow_inverse:
            roles.add("object")
    for construction in _PART_IDENTITY_FRAMES:
        if event.predicate in construction.predicates and _unique_argument(event, construction.role) is not None and not any(argument.role in {"subject", "topic"} for argument in event.arguments):
            roles.add("subject")
    if event.tag in {"VA", "XSA"} and not any(argument.role in {"subject", "topic"} for argument in event.arguments):
        roles.add("subject")
    if head.noun_classes & {"location_head"} and event.predicate in {"자", "눕", "쉬"} and event.tag == "VV" and not any(argument.role == "location" for argument in event.arguments):
        roles.add("location")
    return frozenset(roles)


def _long_negative_relative(evidence, event, head):
    """A/B의 차단을 실패 관형형으로 바꾸지 않고 실제 C만 남긴다."""
    state = event.long_negative
    _long_negative_original_head_domains(evidence, event, head)
    if state.relative_kind == "reported":
        # 인용 전달의 핵어는 본용언의 빠진 논항이 아니다.
        return head
    if state.relative_kind != "direct":
        return _relative_domain_dependency(evidence, event, head)
    if state.unresolved_dependencies:
        return _relative_domain_dependency(evidence, event, head)
    _long_negative_relative_domains(evidence, event, head)
    roles = _long_negative_relative_roles(event, head)
    if roles:
        if len(roles) != 1:
            # 실제 빈 역할이 정해지지 않은 핵어에 허가된 참여 표지를 붙이지 않는다.
            if _independent_nominal_identity(head):
                return head
            return _relative_domain_dependency(evidence, event, head)
        head = _long_negative_structure(evidence, event, head)
        for frame in _FRAMES.get(event.predicate, ()):
            role = _long_negative_frame_role(frame)
            if not role or role not in roles or any(argument.role == role for argument in event.arguments):
                continue
            if frame.predicate_tag and event.tag != frame.predicate_tag:
                continue
            relative_frame = frame if frame.role == "head" else replace(frame, role="head", head_role=role, relation="relative_modifier")
            before = tuple(evidence.get(head.token_index, ()))
            if role == "direct_part_owner":
                support = _support(event, relative_frame)
                if support and any(source.noun_classes & {"unresolved_modifier", "unresolved_relation"} for source in support):
                    # 이 명사 역할이 실제 필요로 하는 부분 출처 C만 원래
                    # 앵커로 보존한다. 미허가 P 효과/유형을 발행하지 않는다.
                    _emit_domain_restriction(evidence, head, (), event, role, support, relative=True)
            _apply_frame(evidence, event, relative_frame, (head,))
            for item in evidence.get(head.token_index, ()):
                if item not in before and not _is_domain_effect(item) and item.semantic_class not in {"nonassertive_predicate_complex", "unresolved_relation"}:
                    head = _derive(head, item.semantic_class, item.relation, item.anchor_start, item.anchor_end)
        return head
    if _neutral_relative(event, head, nonassertive=True) or _nondefining_head_modifier(event, head, nonassertive=True):
        _emit(evidence, head, "nondefining_nominal_modifier", state.start, state.end, "neutral_modifier")
        return _derive(head, "neutral_modifier", "nondefining_nominal_modifier", state.start, state.end)
    # 정의ㆍ결과에 의한 새 유형의 부재만으로 필수 구조 미결을 만들지 않는다.
    known_projection = any(event.predicate in frame.predicates for frame in _EVENT_NOMINAL_FRAMES)
    known_projection = known_projection or any(frame.role == "head" and not frame.head_role for frame in _FRAMES.get(event.predicate, ()))
    if known_projection and not state.unresolved_dependencies:
        return head
    return _relative_domain_dependency(evidence, event, head)


def _predicate_relations(evidence, event):
    """진단 틀이 없는 서술어도 논항을 소비한 뒤 관계 생성은 생략한다."""
    for frame in _FRAMES.get(event.predicate, ()):
        if frame.relation != "predicate_argument":
            continue
        if frame.predicate_tag and event.tag != frame.predicate_tag:
            continue
        argument = _unique_argument(event, frame.role)
        if argument is not None and (not frame.particle_forms or argument.particle_form in frame.particle_forms):
            _apply_frame(evidence, event, frame, argument.members)
    _typed_event_relations(evidence, event)
    _additional_event_relations(evidence, event)
    _classification_event_relations(evidence, event)


def _modifier_relations(evidence, events, head):
    """지원 관계와 문법적으로 확인한 중립 수식어를 각기 보존한다."""
    for event in events:
        ownership = _QUOTE_OWNERSHIP.get()
        if ownership is not None:
            ownership.remember_event(event)
            ownership.observe(head, ((event.start, event.end),))
        if event.long_negative is not None:
            price_bias = _price_bias_on_completed_nominal(event, head)
            if price_bias is not None:
                head = price_bias
                continue
            head = _long_negative_relative(evidence, event, head)
            continue
        negative_type = _relative_negative_type(evidence, event, head)
        if negative_type is not None:
            head = negative_type
            continue
        supported = _typed_relative_relations(evidence, event, head)
        if supported:
            head = supported
            continue
        for frame in _FRAMES.get(event.predicate, ()):
            if frame.role != "head":
                continue
            if frame.predicate_tag and event.tag != frame.predicate_tag:
                continue
            if frame.head_role and any(argument.role == frame.head_role for argument in event.arguments):
                continue
            supported = _apply_frame(evidence, event, frame, (head,)) or supported
        neutral = _neutral_relative(event, head)
        if not supported and neutral:
            _emit(evidence, head, "neutral_relative_" + neutral, event.start, event.end, "neutral_modifier")
            head = _derive(head, "neutral_modifier", "neutral_relative_" + neutral, event.start, event.end)
            for argument in event.arguments:
                for anchor in argument.members:
                    head = _derive(head, "neutral_modifier", "neutral_relative_" + neutral + "_argument", anchor.start, anchor.end)
                    _emit(evidence, head, "neutral_relative_" + neutral + "_argument", anchor.start, anchor.end, "neutral_modifier")
        if not supported and not neutral:
            neutral = _nondefining_head_modifier(event, head)
            if neutral:
                _emit(evidence, head, "nondefining_nominal_modifier", event.start, event.end, "neutral_modifier")
                head = _derive(head, "neutral_modifier", "nondefining_nominal_modifier", event.start, event.end)
                for argument in event.arguments:
                    for anchor in argument.members:
                        head = _derive(head, "neutral_modifier", "nondefining_modifier_argument", anchor.start, anchor.end)
        if not supported and not neutral:
            _emit(evidence, head, "unsupported_relative_modifier", event.start, event.end, "unresolved_modifier")
            head = _derive(head, "unresolved_modifier", "unsupported_relative_modifier", event.start, event.end)
    return _finalize_number_conditions(evidence, head)


def _genitive_relations(evidence, owners, head):
    """직접적인 소유ㆍ부분 관계만 적용하고 일반 속성은 강한 근거로 쓰지 않는다."""
    if len(owners) != 1:
        return
    _original_family_affiliation_relations(evidence, head)
    for noun_class in head.noun_classes:
        semantic_class = _GENITIVE_EFFECTS.get(noun_class)
        if semantic_class:
            for owner in owners:
                _emit(evidence, owner, "genitive_part", head.start, head.end, semantic_class)


# 아래 관계는 대상 철자가 아니라 실제 명사 분류와 문법 역할에만 의존한다.
_TYPE_EFFECTS = MappingProxyType({
    "writing_symbol": "writing_symbol",
    "message": "message",
    "classical_expression": "classical_expression",
    "learning": "learning",
    "physical_constituent": "substance",
    "literary_work": "literary_work",
    "animal": "animal", "insect": "insect",
    "bedding": "bedding", "sleeping_place": "sleeping_place",
    "substance": "substance", "activity": "activity", "sea_harvesting": "sea_harvesting",
    "location": "location", "riverbank": "riverbank", "marriage_event": "marriage_event",
    "dwelling_house": "dwelling_house",
    "elevated_structure": "elevated_structure",
    "assessment_head": "assessment",
    "private_law_branch": "private_law",
    "private_law": "private_law",
    "judicial_function": "judicial_function",
    "judicial_act": "judicial_function",
    "judicial_institution": "judicial_function",
    "price": "price",
    "ordinary_price": "ordinary_price",
    "literary_poetry": "literary_poetry",
    "poetry_member": "literary_poetry",
    "prime_number": "prime_number",
    "decimal_number": "decimal_number",
    "minority_quantity": "minority_quantity",
    "count_quantity": "count_quantity",
    "renovation": "renovation",
    "washing_water": "washing_water",
    "armour_sleeve": "armour_sleeve",
    "speech_ability": "speech_ability",
    "speech_skill": "speech_ability",
    "currency_value_basis_ratio": "monetary_parity",
    "equinus": "equinus",
})
_TYPE_REFINEMENTS = MappingProxyType({"ordinary_price": "price"})
_MEMBERSHIP_EFFECTS = MappingProxyType({
    "physical_constituent": "substance",
    "literary_work": "literary_work",
    "animal": "animal", "insect": "insect",
    "bedding": "bedding", "sleeping_place": "sleeping_place",
    "substance": "substance", "activity": "activity", "sea_harvesting": "sea_harvesting",
    "location": "location", "riverbank": "riverbank", "marriage_event": "marriage_event",
    "private_law_branch": "private_law",
    "poetry_member": "literary_poetry",
    "literary_poetry": "literary_poetry",
    "decimal_member": "decimal_number",
})
_DIRECT_HEAD_EFFECTS = MappingProxyType({
    "institution_head": "judicial_function",
    "counted_human": "minority_quantity",
    "counted_opinion": "minority_quantity",
})
_NEUTRAL_RELATIVES = frozenset({"오래되", "낡", "크", "작", "새롭", "유명하", "높", "비싸", "값비싸", "아름답"})
_TOPIC_PARTICLES = frozenset({"은", "는", "란", "이란"})
_PRE_NEGATIVES = frozenset({"안", "못"})
_APPROXIMATE_COUNTS = frozenset({"약", "대략", "거의", "적어도", "많아야", "최소", "최대"})
_TWO_NUMERALS = MappingProxyType({"두": "MM", "둘": "NR", "2": "SN"})


@dataclass(frozen=True)
class _MembershipConstruction:
    """소속 관계에서 어느 논항이 구성원이고 어느 논항이 분류인지 선언한다."""

    predicates: frozenset[str]
    target_role: str
    member_role: str
    target_particles: frozenset[str] = frozenset()
    topic_member: bool = False


_MEMBERSHIP_CONSTRUCTIONS = (
    _MembershipConstruction(frozenset({"속하", "해당하", "포함되"}), "location", "subject", frozenset({"에"}), True),
    _MembershipConstruction(frozenset({"포함하", "포괄하", "아우르"}), "subject", "object"),
)


def _derive(mention, semantic_class, relation, start, end):
    """한 출현에만 도출 분류와 원래 근거 좌표를 보관한다."""
    if relation.startswith(("lexical_domain_restriction/", "lexical_domain_observation/")):
        return mention
    ownership = _QUOTE_OWNERSHIP.get()
    if ownership is not None:
        ownership.observe(mention, ((start, end),))
    fact = (semantic_class, relation, start, end)
    facts = mention.facts if fact in mention.facts else mention.facts + (fact,)
    return _Mention(mention.token_index, mention.form, mention.start, mention.end,
                    mention.noun_classes | {semantic_class}, mention.owned, mention.owners, facts, mention.bound_arguments)


def _emit_type(evidence, target, source, effects, relation, event=None):
    """명시적으로 연결된 명사의 분류만 전달하고 실제 증거 사슬을 남긴다."""
    if event is not None and event.long_negative is not None:
        return _emit_domain_restriction(evidence, target, {effects[value] for value in source.noun_classes if value in effects},
                                        event, relation, (source,), relative=relation.startswith("relative"))
    ownership = _QUOTE_OWNERSHIP.get()
    if ownership is not None:
        ownership.observe(target, ownership.mention_spans(source))
    emitted = False
    for noun_class in sorted(source.noun_classes):
        source_class = effects.get(noun_class)
        if not source_class:
            continue
        semantic_class = _target_class_constraint(target, source_class)
        emitted = True
        _emit(evidence, target, relation, source.start, source.end, semantic_class)
        if event is not None:
            _emit(evidence, target, relation + "_predicate", event.start, event.end, semantic_class)
        for derived_class, derived_relation, start, end in source.facts:
            if derived_class == noun_class or effects.get(derived_class) == source_class or derived_class in {"unresolved_modifier", "unresolved_relation", "neutral_modifier"}:
                fact_class = _target_class_constraint(target, effects.get(derived_class, derived_class))
                _emit(evidence, target, derived_relation, start, end, fact_class)
    return emitted


def _role_or_topic(event, role, allow_topic=False):
    """화제는 선언된 구문 안에서만 생략 주어 후보로 취급한다."""
    argument = _unique_argument(event, role)
    if argument is not None:
        return argument
    if allow_topic and not any(item.role == role for item in event.arguments):
        return _unique_argument(event, "topic")
    return None


_REPORTING_PREDICATES = frozenset({"설명하", "말하", "전하", "보고하", "기술하", "서술하"})


def _resolve_copular_label_ownership(predicate, arguments):
    """보고 종속절일 때만 주어를 분리하고 다른 용언의 실제 명명 주체는 보존한다."""
    embedded = tuple(argument for argument in arguments if argument.role == "embedded_copular_subject")
    if not embedded:
        return arguments
    if predicate not in _REPORTING_PREDICATES:
        return tuple(argument for argument in arguments if argument.role != "embedded_copular_subject")
    return tuple(
        argument for argument in arguments
        if not (
            argument.role in {"subject", "topic"}
            and any(argument.members == local.members
                    and argument.particle_start == local.particle_start
                    and argument.particle_end == local.particle_end
                    for local in embedded)
        )
    )


def _reported_copular_relations(evidence, event):
    """실제 종속 계사 주어ㆍ보어만 연결하며 바깥 보고 행위자는 제외한다."""
    if event.negated or event.predicate not in _REPORTING_PREDICATES or event.tag not in {"VV", "XSV"}:
        return
    subject = _unique_argument(event, "embedded_copular_subject")
    complement = _unique_argument(event, "label")
    if subject is None or complement is None or complement.particle_form not in {"이라고", "이라"}:
        return
    embedded = _Event("이", complement.particle_start, complement.particle_end,
                      (_Argument("subject", subject.members, subject.particle_form, subject.particle_start, subject.particle_end),
                       _Argument("nominal_complement", complement.members)), "VCP")
    _typed_event_relations(evidence, embedded)


def _typed_event_relations(evidence, event):
    """긍정 계사와 소속 관계에서 완전한 공동 명사구의 유형만 전달한다."""
    if event.negated:
        return
    _reported_copular_relations(evidence, event)
    if event.tag == "VCP" and event.predicate == "이":
        subject = _role_or_topic(event, "subject", True)
        complement = _unique_argument(event, "nominal_complement")
        # 명시 주어ㆍ화제가 없으면 하나의 가산/한정 초점이 계사의 주어가 된다.
        if subject is None and not any(argument.role in {"subject", "topic"} for argument in event.arguments):
            subject = _unique_argument(event, "focus")
        if subject is not None and complement is not None:
            for left in subject.members:
                _emit_group_type(evidence, left, complement.members, _TYPE_EFFECTS, "copular_category", event)
            for right in complement.members:
                if "membership_head" in right.noun_classes and right.owners:
                    for owner in right.owners:
                        _emit_group_type(evidence, owner, subject.members, _MEMBERSHIP_EFFECTS, "copular_membership", event)
                else:
                    _emit_group_type(evidence, right, subject.members, _TYPE_EFFECTS, "copular_category", event)
    for construction in _MEMBERSHIP_CONSTRUCTIONS:
        if event.predicate not in construction.predicates or event.tag not in {"VV", "XSV"}:
            continue
        target = _unique_argument(event, construction.target_role)
        member = _role_or_topic(event, construction.member_role, construction.topic_member)
        if target is None or member is None:
            continue
        if construction.target_particles and target.particle_form not in construction.target_particles:
            continue
        for nominal in target.members:
            for container in _membership_containers(nominal):
                _emit_group_type(evidence, container, member.members, _MEMBERSHIP_EFFECTS, "typed_membership", event)



def _negative_type_source(source, argument, owner, tokens, clause_start):
    """원래 보통명사와 현재 핵어의 독립 유형만 부정 범주로 받는다."""
    excluded = {"unresolved_modifier", "unresolved_relation", "quoted_nominal",
                "designation_head", "designation_reference", "typed_head_reference", "self_reference"}
    if (source.owned or source.owners or source.bound_arguments
            or source.noun_classes & excluded
            or not source.start < source.end <= argument.particle_start
            or owner is not None and owner.particle_end > source.start):
        return frozenset()
    # 화제 뒤부터 실제 보격 조사 앞까지의 원래 범주 재료를 확인한다.
    material = [token for token in tokens
                if clause_start <= token.start and token.end <= argument.particle_start]
    if not material or material[-1].end != source.end:
        return frozenset()
    for token in material:
        parts = token.morphemes or ((token.form, token.tag),)
        if (tuple(_tag(tag) for _, tag in parts) != tuple(_tag(tag) for tag in token.tag.split("+"))
                or any(_tag(tag) not in {"NNG", "NNB", "XPN", "XSN", "JKG", "Z_SIOT"} for _, tag in parts)
                or ("".join(form for form, _ in parts) != token.form
                    and _render_nominal_constituents(parts) != token.form)):
            return frozenset()
    own = [token for token in material if source.start <= token.start and token.end <= source.end]
    if (not own or own[0].start != source.start or own[-1].end != source.end
            or "".join(token.form for token in own) != source.form
            or not _complete_common_nominal(tuple(_tag(token.tag) for token in own))):
        return frozenset()
    return frozenset(_TYPE_EFFECTS[value] for value, relation, start, end in source.facts
                     if relation in {"lexical_nominal_head", "composed_nominal_head_identity"}
                     and (start, end) == (source.start, source.end) and value in _TYPE_EFFECTS)


def _finite_negative_type(evidence, event, units, position, tokens, adnominal):
    """유일한 유한 부정 계사의 주어에만 방향 있는 유형 부정을 남긴다."""
    if event.tag != "VCN" or event.predicate != "아니" or adnominal:
        return
    endings = units[position].endings
    following = position + 1
    while not endings and following < len(units) and units[following].tag == "EP":
        following += 1
    if not endings and following < len(units):
        endings = (units[following].tag,)
    if endings != ("EF",):
        return
    owners = [argument for argument in event.arguments if argument.role in {"subject", "topic"}]
    complement = _unique_argument(event, "complement")
    subject = _unique_argument(event, "subject")
    topic = _unique_argument(event, "topic")
    inverse = (len(event.arguments) == 2 and subject is not None and topic is not None
               and len(subject.members) == len(topic.members) == 1
               and topic.particle_form in {"은", "는"})
    if inverse:
        owners, complement = [subject], topic
    targets = tuple(member for argument in owners for member in argument.members)
    unique = len(owners) == 1 and len(targets) == 1
    source = complement.members[0] if complement is not None and len(complement.members) == 1 else None
    types = frozenset()
    if (unique and source is not None and (inverse or complement.particle_form in {"이", "가"})
            and not event.negated and event.long_negative is None
            and not targets[0].owned and not targets[0].owners
            and not _explicit_referring_term(targets[0])
            and (targets[0].start, targets[0].end) != (source.start, source.end)
            and all(argument.role in {"subject", "topic", "complement"} for argument in event.arguments)):
        clause_start = max((unit.end for unit in units[:position]
                            if unit.end <= source.start and (unit.tag in {"EF", "EC"} or any(
                                ending in {"EF", "EC"} for ending in unit.endings))),
                           default=owners[0].particle_end)
        clause_start = max(clause_start, owners[0].particle_end)
        types = _negative_type_source(source, complement, owners[0], tokens, clause_start)
    if not types:
        # 명시 개체의 비동일성은 유형 부정의 경쟁 근거로 승격하지 않는다.
        clear_entity = unique and source is not None and _clear_negative_entity(source, tokens)
        if clear_entity:
            return
        for target in targets:
            _emit(evidence, target, "unresolved_negative_type", event.start, event.end, "unresolved_relation")
        return
    for semantic_class in sorted(types):
        _emit(evidence, targets[0], "negative_copular_category", source.start, source.end, semantic_class)
        _emit(evidence, targets[0], "negative_copular_category_predicate", event.start, event.end, semantic_class)


def _numeric_relative(event, head):
    """정확히 두 자연수 약수라는 제한된 수량 속성만 판정한다."""
    if event.negated or event.tag != "VCP" or event.predicate != "이":
        return ()
    subject = _unique_argument(event, "subject")
    complement = _unique_argument(event, "nominal_complement")
    if subject is None or complement is None or len(subject.members) != 1 or len(complement.members) != 1:
        return ()
    counted, count = subject.members[0], complement.members[0]
    if "exact_count_two" not in count.noun_classes or any("unresolved_modifier" in mention.noun_classes for mention in (counted, count)):
        return ()
    anchors = ()
    compatible_head = "natural_number" in head.noun_classes
    compatible_direct_target = "prime_number" in _possible_classes(head)
    if not compatible_head and not compatible_direct_target:
        return ()
    if any(value in _APPROXIMATE_COUNTS for value in event.adjuncts):
        return ()
    if not counted.owned and ("natural_divisor" in counted.noun_classes or (compatible_head and "divisor" in counted.noun_classes)):
        anchors = (counted,)
    elif counted.noun_classes & {"count_head", "number_head"} and len(counted.owners) == 1:
        owner = counted.owners[0]
        if not owner.owned and "unresolved_modifier" not in owner.noun_classes and ("natural_divisor" in owner.noun_classes or (compatible_head and "divisor" in owner.noun_classes)):
            anchors = (owner,)
    if not anchors:
        return ()
    return anchors + (count,)


def _predicate_relative_type(evidence, event, head):
    """관형절의 실제 빈 논항과 직접 핵어를 연결한다."""
    quantity = _low_count_relative(evidence, event, head)
    if quantity is not None:
        return quantity
    identity = _identity_relative(evidence, event, head)
    if identity is not None:
        return identity
    classified = _classification_relative(evidence, event, head)
    if classified is not None:
        return classified
    activity = _event_nominal_relative(evidence, event, head)
    if activity is not None:
        return activity
    if event.negated:
        return None
    counted = _counted_divisor_relative(evidence, event, head)
    if counted is not None:
        return counted
    comparison = _comparison_relative(evidence, event, head)
    if comparison is not None:
        return comparison
    number = _bounded_number_relative(evidence, event, head)
    if number is not None:
        return number
    numeric = _numeric_relative(event, head)
    if numeric:
        for anchor in numeric:
            _emit(evidence, head, "exact_natural_divisor_count", anchor.start, anchor.end, "prime_number")
            head = _derive(head, "prime_number", "exact_natural_divisor_count", anchor.start, anchor.end)
        return head
    defined = _definition_relative(evidence, event, head)
    if defined is not None:
        return defined
    for construction in _MEMBERSHIP_CONSTRUCTIONS:
        if event.predicate not in construction.predicates or event.tag not in {"VV", "XSV"}:
            continue
        target = _unique_argument(event, construction.target_role)
        member = _role_or_topic(event, construction.member_role, construction.topic_member)
        missing_category = target is None and not any(argument.role == construction.target_role for argument in event.arguments)
        # 명시 행위자는 범주 핵어의 소유자가 아니며 구성원 관계를 지우지도 않는다.
        overt_actor = target is not None and construction.target_role == "subject" and construction.member_role == "object" and all(argument.role in {"subject", "object"} for argument in event.arguments)
        if member is not None and (missing_category or overt_actor):
            if _mixed_group(member.members, _MEMBERSHIP_EFFECTS) and (_possible_classes(head) or head.noun_classes & {"legal_type_head", "form_head", "membership_head"}):
                return _derive_group_type(evidence, head, member.members, _MEMBERSHIP_EFFECTS, "relative_membership", event)
            effects = _group_effects(member.members, _MEMBERSHIP_EFFECTS)
            compatible = {value for value in effects if _membership_head_compatible(head, value)}
            if compatible:
                return _derive_group_type(evidence, head, member.members, _MEMBERSHIP_EFFECTS, "relative_membership", event, compatible)
        if target is not None and member is None and not any(argument.role in {construction.member_role, "topic"} for argument in event.arguments):
            if construction.target_particles and target.particle_form not in construction.target_particles:
                continue
            success = False
            for nominal in target.members:
                for container in _membership_containers(nominal):
                    success = _emit_group_type(evidence, container, (head,), _MEMBERSHIP_EFFECTS, "relative_membership_member", event) or success
            if success:
                return head
    # 법을 규율되는 대상과 혼동하지 않고, 법의 실제 목적어 영역을 요구한다.
    if event.predicate == "규율하" and event.tag in {"VV", "XSV"} and not any(argument.role in {"subject", "topic"} for argument in event.arguments):
        objects = _unique_argument(event, "object")
        if objects is not None and objects.members and all("private_relation" in member.noun_classes and "unresolved_modifier" not in member.noun_classes for member in objects.members):
            if "legal_type_head" in head.noun_classes or "private_law" in _possible_classes(head):
                _emit(evidence, head, "regulated_private_domain", event.start, event.end, "private_law")
                head = _derive(head, "private_law", "regulated_private_domain", event.start, event.end)
                for member in objects.members:
                    _emit(evidence, head, "regulated_private_domain_anchor", member.start, member.end, "private_law")
                    head = _derive(head, "private_law", "regulated_private_domain_anchor", member.start, member.end)
                return head
    if event.predicate in {"담당하", "관장하", "수행하"} and event.tag in {"VV", "XSV"} and "function_head" in head.noun_classes and not any(argument.role in {"subject", "topic"} for argument in event.arguments):
        objects = _unique_argument(event, "object")
        if objects is not None and objects.members and all("judicial_act" in member.noun_classes for member in objects.members):
            return _derive_group_type(evidence, head, objects.members, {"judicial_act": "judicial_function"}, "judicial_action_function", event)
    if event.tag != "VCP" or event.predicate != "이" or any(argument.role in {"subject", "topic"} for argument in event.arguments):
        return None
    complement = _unique_argument(event, "nominal_complement")
    if complement is None:
        return None
    result = _derive_group_type(evidence, head, complement.members, _TYPE_EFFECTS, "copular_relative", event)
    supported = result is not None
    if supported:
        head = result
    if len(complement.members) == 1 and "natural_number" in complement.members[0].noun_classes and "divisor" in head.noun_classes:
        head = _derive(head, "natural_divisor", "natural_divisor_category", complement.members[0].start, complement.members[0].end)
        supported = True
    for source in complement.members:
        supported = _emit_group_type(evidence, source, (head,), _TYPE_EFFECTS, "copular_relative_head", event) or supported
    return head if supported else None


def _direct_nominal_relations(evidence, modifiers, head):
    """띄어 쓴 직접 명사 수식 관계만 분류하고 연결되지 않은 명사를 버린다."""
    if len(modifiers) != 1:
        return head
    modifier = modifiers[0]
    for noun_class in head.noun_classes:
        semantic_class = _DIRECT_HEAD_EFFECTS.get(noun_class)
        if semantic_class:
            _emit(evidence, modifier, "direct_nominal_modifier", head.start, head.end, semantic_class)
    for head_class, semantic_class in _STRUCTURAL_HEAD_EFFECTS.items():
        if head_class in head.noun_classes and semantic_class in _possible_classes(modifier) and not head.owned:
            _emit(evidence, modifier, "structural_nominal_modifier", head.start, head.end, semantic_class)
            for fact_class, relation, start, end in head.facts:
                if fact_class in {"unresolved_modifier", "unresolved_relation", "neutral_modifier"}:
                    _emit(evidence, modifier, relation, start, end, fact_class)
    if "natural_number" in modifier.noun_classes and "divisor" in head.noun_classes:
        if "pairwise_distinct" in modifier.noun_classes:
            for value, relation, start, end in modifier.facts:
                if value == "pairwise_distinct":
                    head = _derive(head, value, relation, start, end)
        head = _derive(head, "natural_divisor", "natural_divisor_modifier", modifier.start, modifier.end)
        for semantic_class, relation, start, end in modifier.facts:
            if semantic_class == "unresolved_modifier":
                head = _derive(head, semantic_class, relation, start, end)
        if modifier.owned:
            head = _Mention(head.token_index, head.form, head.start, head.end, head.noun_classes, True, modifier.owners, head.facts, head.bound_arguments)
    return head


def _compose_counts(units):
    """표현된 수량 이외의 계산 없이 둘과 개의 제한된 계수 구문을 묶는다."""
    units = tuple(units)
    position = 0
    while position < len(units):
        unit = units[position]
        if unit.form not in _TWO_NUMERALS or unit.tag != _TWO_NUMERALS[unit.form]:
            yield unit
            position += 1
            continue
        stop = position + 1
        if unit.tag == "MM":
            if stop >= len(units) or units[stop].tag != "NNB" or units[stop].form != "개":
                yield unit
                position += 1
                continue
            stop += 1
        elif stop < len(units) and units[stop].tag == "NNB" and units[stop].form == "개":
            stop += 1
        if stop < len(units) and units[stop].tag == "JX" and units[stop].form in {"뿐", "만"}:
            stop += 1
        approximate = position > 0 and units[position - 1].tag == "MAG" and units[position - 1].form in _APPROXIMATE_COUNTS
        classes = frozenset() if approximate else frozenset({"exact_count_two"})
        yield _Unit(unit.form, "COUNT", unit.start, units[stop - 1].end, unit.token_index, noun_classes=classes)
        position = stop


def _following_negative(units, position):
    """정규형 지/EC 않/VX 부정 구성을 절 경계 이전에만 확인한다."""
    cursor = position + 1
    while cursor < len(units) and units[cursor].tag == "EP":
        cursor += 1
    if cursor >= len(units) or units[cursor].tag != "EC" or units[cursor].form != "지":
        return False
    cursor += 1
    return cursor < len(units) and units[cursor].tag == "VX" and units[cursor].form == "않"


def _adnominal_predicate(units, position):
    """속격 소유의 지연은 실제 관형 어미가 확인되는 용언에만 허용한다."""
    unit = units[position]
    if unit.endings:
        return unit.endings[0] == "ETM"
    cursor = position + 1
    while cursor < len(units) and units[cursor].tag == "EP":
        cursor += 1
    return cursor < len(units) and units[cursor].tag == "ETM"


# 독립 명사 조립과 관계 구문은 어휘 대상이 아닌 선언된 문법 역할에 의존한다.
_TRADE_PREDICATES = frozenset({"사", "팔", "구입하", "구매하", "매입하", "매각하", "거래하"})
_PRICE_CASES = MappingProxyType({"location": frozenset({"에"}), "via": frozenset({"로", "으로"})})
_NAMING_PREDICATES = frozenset({"하", "부르", "정의하", "칭하", "명명하", "일컫", "지칭하", "통칭하", "총칭하"})
_PRICE_COMPARISONS = frozenset({"높", "낮", "같", "비싸", "싸"})
_HUMAN_PARTICIPANT_PREDICATES = frozenset({"찬성하", "반대하", "지지하", "동의하", "참석하", "참여하"})
_BASIS_PARTICLES = frozenset({"로", "으로"})
_NOMINAL_CONTRAST_CONNECTORS = frozenset({"라", "고"})
_COPULAR_COORDINATORS = frozenset({"고", "면서", "며", "자"})
_CONTRAST_DOMAIN_EFFECTS = MappingProxyType({
    "price": "price", "quantity_group": "quantity", "minority_quantity": "quantity",
    "dwelling_house": "structure", "elevated_structure": "structure", "family_home": "family",
    "literary_poetry": "literature",
})
_CONTRAST_TARGET_EFFECTS = MappingProxyType({"high_price": "price", "minority_quantity": "minority_quantity"})
_CONTRAST_COMPATIBILITY = MappingProxyType({
    "low_price": frozenset({"high_price"}),
    "middle_price": frozenset({"high_price"}),
    "majority_quantity": frozenset({"minority_quantity"}),
})
_GENITIVE_TYPE_CONSTRUCTIONS = (
    ("positive_sign", "integer", "natural_number"),
    ("positive_sign", "divisor", "natural_divisor"),
    ("private_party", "legal_relation", "private_relation"),
    ("private_party_domain", "legal_relation", "private_relation"),
    ("private_party_domain", "relation_head", "private_relation"),
    ("armour", "sleeve_part", "armour_sleeve"),
    ("ordinary_price_modifier", "price", "ordinary_price"),
)


@dataclass(frozen=True)
class _DerivationConstruction:
    """정규 형태소의 명시적 결합만 정규 서술어로 조립한다."""

    base_form: str
    base_tag: str
    suffix_form: str
    suffix_tag: str
    result_tag: str


_DERIVATION_CONSTRUCTIONS = (
    _DerivationConstruction("오래", "MAG", "되", "XSV", "VV"),
    _DerivationConstruction("오래", "MAG", "되", "XSA", "VA"),
    _DerivationConstruction("유명", "NNG", "하", "XSA", "VA"),
    _DerivationConstruction("유명", "XR", "하", "XSA", "VA"),
)


def _complete_common_nominal(tags):
    """완전한 접두부ㆍ명사부ㆍ접미부 순서만 일반 명사 구성으로 인정한다."""
    if not tags or tags[0] not in {"NNG", "XPN"} or tags[-1] not in {"NNG", "XSN"}:
        return False
    position = 0
    while position < len(tags) and tags[position] == "XPN":
        position += 1
    while position < len(tags) and tags[position] == "NNG":
        position += 1
    if position == len(tags):
        return True
    return position == len(tags) - 1 and tags[position] == "XSN" and position > 0


def _compose_declared_derivations(units):
    """다른 부사나 의존 명사를 건너뛰지 않고 선언된 연속 형태소를 조립한다."""
    units = tuple(units)
    position = 0
    while position < len(units):
        unit = units[position]
        combined = None
        if position + 1 < len(units):
            suffix = units[position + 1]
            for construction in _DERIVATION_CONSTRUCTIONS:
                if (unit.form, unit.tag, suffix.form, suffix.tag) == (construction.base_form, construction.base_tag, construction.suffix_form, construction.suffix_tag):
                    if not unit.endings and _contiguous(unit, suffix):
                        combined = _Unit(unit.form + suffix.form, construction.result_tag, unit.start, suffix.end, unit.token_index, suffix.endings,
                                         occurrences=unit.occurrences + suffix.occurrences)
                        break
            if unit.tag == "VCP" and unit.form == "이" and not unit.endings and _contiguous(unit, suffix):
                if suffix.tag == "EC" and suffix.form in {"라고", "라"}:
                    combined = _Unit(unit.form + suffix.form, "LABEL", unit.start, suffix.end, unit.token_index, noun_classes=frozenset({"copular_report_label"}),
                                     occurrences=unit.occurrences + suffix.occurrences)
                elif suffix.tag == "ETM" and suffix.form in {"라는", "란"}:
                    combined = _Unit(unit.form + suffix.form, "ALIAS", unit.start, suffix.end, unit.token_index,
                                     occurrences=unit.occurrences + suffix.occurrences)
        if combined is not None:
            yield combined
            position += 2
        else:
            if unit.tag == "NNB" and unit.form == "간":
                unit = replace(unit, tag="NNG", noun_classes=frozenset({"between_head"}))
            yield unit
            position += 1


def _possible_classes(mention):
    """등록 뜻들의 가능한 분류를 조회하되 그 자체를 확정 근거로 쓰지 않는다."""
    return frozenset(semantic_class for sense in _SENSES_BY_SPELLING.get(mention.form, ()) for semantic_class in SENSE_FEATURES[sense].semantic_classes)


def _membership_head_compatible(head, semantic_class):
    """구성원을 담은 임의의 책ㆍ논의를 해당 법이나 수 자체로 바꾸지 않는다."""
    if semantic_class in _possible_classes(head) or semantic_class in head.noun_classes:
        return True
    if semantic_class == "literary_work" and "literary_poetry" in _possible_classes(head):
        return True
    if "form_head" in head.noun_classes:
        return semantic_class in {"literary_poetry", "literary_work"}
    if "membership_head" in head.noun_classes:
        return semantic_class in _DESIGNATION_ANCHORS
    return semantic_class == "private_law" and "legal_type_head" in head.noun_classes


def _coherent_price_argument(argument, lexical_domain=False):
    """실제 명사 모순과 어휘 대안을 구별하고 긍정 소비의 추가 검사는 남긴다."""
    for member in argument.members:
        if member.noun_classes & {"unresolved_modifier", "unresolved_relation"}:
            return False
        if member.noun_classes:
            if "price" not in member.noun_classes:
                return False
        else:
            possible = _possible_classes(member)
            # 미선택 후보는 실제 독립 명사 사실과 구별한다. 긍정ㆍ수량 소비의
            # 기존 더 강한 양립 조건은 기본 경로에 그대로 남긴다.
            if "price" not in possible or (not lexical_domain and possible & {"spouse_family", "family_home", "human"}):
                return False
    return bool(argument.members)


def _transaction_relations(evidence, event):
    """직접 거래 목적물과 실제 가격 조사를 요구하여 장소ㆍ수령인을 배제한다."""
    if event.predicate not in _TRADE_PREDICATES or event.tag not in {"VV", "XSV"}:
        return
    objects = _unique_argument(event, "object")
    if objects is None or not objects.members:
        return
    if any("trade_item" not in member.noun_classes or "unresolved_modifier" in member.noun_classes for member in objects.members):
        return
    for role, particles in _PRICE_CASES.items():
        argument = _unique_argument(event, role)
        if argument is None or argument.particle_form not in particles or not _coherent_price_argument(argument, lexical_domain=event.long_negative is not None):
            continue
        for target in argument.members:
            if "price" not in _possible_classes(target):
                continue
            if _long_negative_required_base(evidence, event, target, "price"):
                continue
            if event.long_negative is not None:
                _emit_domain_restriction(evidence, target, {"price"}, event, "transaction_price", objects.members)
                continue
            _emit(evidence, target, "transaction_price", event.start, event.end, "price")
            _emit(evidence, target, "transaction_price_case", argument.particle_start, argument.particle_end, "price")
            for anchor in objects.members:
                _emit(evidence, target, "transaction_price_object", anchor.start, anchor.end, "price")


def _membership_containers(mention):
    """명시적 분류ㆍ범주 핵어의 소유자만 실제 소속 대상으로 돌려준다."""
    if "membership_head" in mention.noun_classes and len(mention.owners) == 1:
        return mention.owners
    return (mention,)


def _additional_event_relations(evidence, event):
    """명명ㆍ의미ㆍ가격 비교를 명시적인 문법 역할에만 적용한다."""
    _transaction_relations(evidence, event)
    if event.negated:
        return
    if event.predicate in _NAMING_PREDICATES and event.tag in {"VV", "XSV"} and not (event.predicate == "하" and event.tag == "XSV"):
        labels = _naming_label(event)
        source = _role_or_topic(event, "object", True)
        if labels is not None and source is not None:
            for target in labels.members:
                _emit_group_type(evidence, target, source.members, _TYPE_EFFECTS, "nominal_naming", event)
            for anchor in source.members:
                _emit_group_type(evidence, anchor, labels.members, _TYPE_EFFECTS, "nominal_naming", event)
    _passive_naming_relations(evidence, event)
    _paraphrase_event_relations(evidence, event)
    _recorded_label_relations(evidence, event)
    _definition_event_relations(evidence, event)
    if event.predicate in _PRICE_COMPARISONS and event.tag == "VA":
        subject = _role_or_topic(event, "subject", True)
        comparison = _unique_argument(event, "comparison")
        if subject is not None and comparison is not None and comparison.particle_form == "보다":
            for targets, sources in ((subject.members, comparison.members), (comparison.members, subject.members)):
                if sources and all("price" in source.noun_classes and "unresolved_modifier" not in source.noun_classes for source in sources):
                    for target in targets:
                        _emit_group_type(evidence, target, sources, {"price": "price"}, "typed_price_comparison", event)
    if event.predicate in _HUMAN_PARTICIPANT_PREDICATES and event.tag in {"VV", "XSV"}:
        argument = _role_or_topic(event, "subject", True)
        if argument is None and not any(item.role in {"subject", "topic"} for item in event.arguments):
            argument = _unique_argument(event, "focus")
        if argument is not None:
            for target in argument.members:
                if "minority_quantity" in _possible_classes(target):
                    _emit(evidence, target, "quantified_human_participant", event.start, event.end, "minority_quantity")


def _comparison_relative(evidence, event, head):
    """가격이라는 완전한 후행 핵어가 직접 비교 논항을 분류한다."""
    if (event.negated and event.long_negative is None) or event.predicate not in _PRICE_COMPARISONS or event.tag != "VA" or "price" not in head.noun_classes:
        return None
    if any(argument.role in {"subject", "topic"} for argument in event.arguments):
        return None
    comparison = _unique_argument(event, "comparison")
    if comparison is None or comparison.particle_form != "보다":
        return None
    for target in comparison.members:
        _emit_type(evidence, target, head, {"price": "price"}, "relative_price_comparison", event)
    return head






def _contrast_relations(evidence, left, right, event):
    """긍정 동일시와 달리 바로 대비되는 두 명사구의 호환 분야만 기록한다."""
    for first in left:
        for second in right:
            for target, source in ((first, second), (second, first)):
                target_domains = {_CONTRAST_DOMAIN_EFFECTS[value] for value in target.noun_classes if value in _CONTRAST_DOMAIN_EFFECTS}
                for source_class in sorted(source.noun_classes):
                    for target_class in sorted(_CONTRAST_COMPATIBILITY.get(source_class, frozenset()) & _possible_classes(target)):
                        semantic_class = _CONTRAST_TARGET_EFFECTS[target_class]
                        domain = _CONTRAST_DOMAIN_EFFECTS[semantic_class]
                        if target_domains and domain not in target_domains:
                            _emit(evidence, target, "incompatible_nominal_contrast", source.start, source.end, "unresolved_relation")
                            continue
                        _emit(evidence, target, "nominal_contrast_domain", source.start, source.end, semantic_class)
                        _emit(evidence, target, "nominal_contrast_marker", event.start, event.end, semantic_class)


def _negative_nominal(event):
    """부정 계사가 부정하는 실제 보어만 대비의 왼쪽 항으로 돌려준다."""
    if event is None or event.tag != "VCN" or event.predicate != "아니":
        return ()
    for role in ("complement", "subject", "nominal_complement"):
        argument = _unique_argument(event, role)
        if argument is not None:
            return argument.members
    return ()


# SPDX-License-Identifier: MIT
# 아래 구현은 허용된 의미 명세로부터 새로 작성한 문법 관계다.
_MEANING_PREDICATES = frozenset({"의미하", "뜻하", "통칭하", "총칭하", "일컫", "지칭하"})


@dataclass(frozen=True)
class _DefinitionFrame:
    """정의 서술어의 방향과 동음 용법을 가르는 실제 격 제약을 선언한다."""

    predicates: frozenset[str]
    forbidden_roles: frozenset[str] = frozenset()
    allow_inverse: bool = True
    require_compatible_subject: bool = False
    designation_only: bool = False


_DEFINITION_FRAMES = (
    _DefinitionFrame(_MEANING_PREDICATES),
    # 물리적인 지목은 명시 지칭어가 실제 주어인 용법과 구별한다.
    _DefinitionFrame(frozenset({"가리키"}), frozenset({"location", "recipient", "source", "via", "comparison", "comitative", "basis"}), False, True, True),
    # 목적지에 도달하거나 수령인에게 알리는 이르다는 정의 틀이 아니다.
    _DefinitionFrame(frozenset({"이르"}), frozenset({"location", "recipient", "source", "via", "comparison", "comitative", "basis"}), False, True),
)
_DEFINITION_PREDICATES = frozenset(value for frame in _DEFINITION_FRAMES for value in frame.predicates)


def _definition_frame(event):
    """긍정 실제 용언과 금지 격 검사를 통과한 정의 틀만 반환한다."""
    if event.negated or event.tag not in {"VV", "XSV"}:
        return None
    for frame in _DEFINITION_FRAMES:
        if event.predicate in frame.predicates and not any(argument.role in frame.forbidden_roles for argument in event.arguments):
            return frame
    return None


def _compatible_designation_nominal(mention, effects):
    """분류 대상 또는 명시적인 지칭 명사에만 직접 정의를 허용한다."""
    return "designation_head" in mention.noun_classes or bool(effects & (_possible_classes(mention) | mention.noun_classes)) or ("literary_work" in effects and "literary_poetry" in _possible_classes(mention))


def _definition_event_relations(evidence, event):
    """뜻의 대상에서 지칭어로 향하는 실제 목적어ㆍ주어 관계를 연결한다."""
    frame = _definition_frame(event)
    if frame is None:
        return
    subject = _role_or_topic(event, "subject", True)
    objects = _unique_argument(event, "object")
    labels = _unique_argument(event, "label")
    if event.predicate == "이르" and labels is not None:
        if objects is not None:
            for target in labels.members:
                _emit_group_type(evidence, target, objects.members, _TYPE_EFFECTS, "explicit_designation_label", event)
            for target in objects.members:
                _emit_group_type(evidence, target, labels.members, _TYPE_EFFECTS, "explicit_designation_label", event)
        return
    if subject is None or objects is None:
        return
    effects = _group_effects(objects.members, _TYPE_EFFECTS)
    for target in subject.members:
        if frame.designation_only and not _explicit_referring_term(target):
            continue
        if not frame.require_compatible_subject or _compatible_designation_nominal(target, effects) or (_possible_classes(target) and _mixed_group(objects.members, _TYPE_EFFECTS)):
            _emit_group_type(evidence, target, objects.members, _TYPE_EFFECTS, "explicit_definition", event)
    if frame.allow_inverse:
        for target in objects.members:
            _emit_group_type(evidence, target, subject.members, _TYPE_EFFECTS, "explicit_definition", event)


def _group_effects(sources, effects):
    """모든 공동 항이 독립적으로 지지하는 분류만 교집합으로 남긴다."""
    groups = []
    for source in sources:
        group = {effects[value] for value in source.noun_classes if value in effects}
        for specific, general in _TYPE_REFINEMENTS.items():
            if specific in group:
                group.discard(general)
        groups.append(group)
    if not groups:
        return frozenset()
    return frozenset.intersection(*(frozenset(group) for group in groups))


def _mixed_group(sources, effects):
    """알려진 한 항과 미지ㆍ이질적인 다른 항이 섞인 경우를 보존한다."""
    return len(sources) > 1 and not _group_effects(sources, effects) and any(any(value in effects for value in source.noun_classes) for source in sources)


def _emit_coherent_group_type(evidence, target, sources, effects, relation, event=None, allowed=None):
    """공동 유형의 모든 실제 성분과 실제 서술어를 근거로 기록한다."""
    if "designation_reference" in target.noun_classes and target.owners:
        emitted = False
        for owner in target.owners:
            emitted = _emit_group_type(evidence, owner, sources, effects, relation, event, allowed) or emitted
            for semantic_class in _group_effects(sources, effects):
                _emit(evidence, owner, "designation_nominal_head", target.start, target.end, _target_class_constraint(owner, semantic_class))
        return emitted
    shared = _group_effects(sources, effects)
    for source in sources:
        for fact_class, fact_relation, start, end in source.facts:
            if fact_class in {"unresolved_modifier", "unresolved_relation"}:
                _emit(evidence, target, fact_relation, start, end, fact_class)
    if allowed is not None:
        shared &= frozenset(allowed)
    if not shared:
        if _mixed_group(sources, effects):
            for source in sources:
                _emit(evidence, target, "incoherent_coordinated_type", source.start, source.end, "unresolved_relation")
        return False
    filtered = {key: value for key, value in effects.items() if value in shared}
    for source in sources:
        _emit_type(evidence, target, source, filtered, relation, event)
    return True


def _derive_group_type(evidence, head, sources, effects, relation, event=None, allowed=None):
    """후행 핵어에 공동 유형과 각 성분의 별도 출처 사슬을 함께 보관한다."""
    shared = _group_effects(sources, effects)
    if allowed is not None:
        shared &= frozenset(allowed)
    if not shared:
        unresolved = [(fact_class, fact_relation, start, end) for source in sources for fact_class, fact_relation, start, end in source.facts if fact_class in {"unresolved_modifier", "unresolved_relation"}]
        if unresolved:
            for fact_class, fact_relation, start, end in unresolved:
                _emit(evidence, head, fact_relation, start, end, fact_class)
                head = _derive(head, fact_class, fact_relation, start, end)
            return head
        if not _mixed_group(sources, effects):
            return None
        for source in sources:
            _emit(evidence, head, "incoherent_coordinated_type", source.start, source.end, "unresolved_relation")
            head = _derive(head, "unresolved_relation", "incoherent_coordinated_type", source.start, source.end)
        return head
    _emit_group_type(evidence, head, sources, effects, relation, event, shared)
    for semantic_class in sorted(shared):
        for source in sources:
            head = _derive(head, semantic_class, relation, source.start, source.end)
            for fact_class, fact_relation, start, end in source.facts:
                if fact_class == semantic_class or effects.get(fact_class) == semantic_class or fact_class in {"unresolved_modifier", "unresolved_relation", "neutral_modifier"}:
                    head = _derive(head, fact_class, fact_relation, start, end)
        if event is not None:
            head = _derive(head, semantic_class, relation + "_predicate", event.start, event.end)
    return head


def _definition_relative(evidence, event, head):
    """뜻ㆍ총칭의 주어와 목적어 중 실제로 비어 있는 한 역할만 핵어로 채운다."""
    frame = _definition_frame(event)
    if frame is None:
        return None
    if event.predicate == "이르" and any(argument.role == "label" for argument in event.arguments):
        return None
    subject = _role_or_topic(event, "subject", True)
    objects = _unique_argument(event, "object")
    if subject is None and not any(argument.role in {"subject", "topic"} for argument in event.arguments) and objects is not None:
        effects = _group_effects(objects.members, _TYPE_EFFECTS)
        if (not frame.designation_only or _explicit_referring_term(head)) and _compatible_designation_nominal(head, effects):
            return _derive_group_type(evidence, head, objects.members, _TYPE_EFFECTS, "relative_definition", event)
        if (not frame.designation_only or _explicit_referring_term(head)) and _mixed_group(objects.members, _TYPE_EFFECTS) and _possible_classes(head):
            return _derive_group_type(evidence, head, objects.members, _TYPE_EFFECTS, "relative_definition", event)
    if frame.allow_inverse and subject is not None and objects is None and not any(argument.role == "object" for argument in event.arguments):
        supported = False
        for target in subject.members:
            supported = _emit_group_type(evidence, target, (head,), _TYPE_EFFECTS, "relative_defined_object", event) or supported
        if supported:
            return head
    return None


def _bounded_number_relative(evidence, event, head):
    """1보다 큼과 완전한 두 약수 집합을 분리하여 자연수에서만 합성한다."""
    if event.negated:
        return None
    if event.tag == "VA" and event.predicate == "다르" and "서로" in event.adjuncts and head.noun_classes & {"natural_number", "natural_divisor", "divisor"} and not any(argument.role in {"subject", "topic"} for argument in event.arguments):
        return _derive(head, "pairwise_distinct", "pairwise_distinct_divisors", event.start, event.end)
    if event.tag == "VA" and event.predicate == "크" and "natural_number" in head.noun_classes and not any(argument.role in {"subject", "topic"} for argument in event.arguments):
        comparison = _unique_argument(event, "comparison")
        if comparison is not None and comparison.particle_form == "보다" and len(comparison.members) == 1 and "number_one" in comparison.members[0].noun_classes:
            anchor = comparison.members[0]
            return _derive(head, "greater_than_one", "strict_number_lower_bound", anchor.start, anchor.end)
    if event.tag != "VCP" or event.predicate != "이":
        return None
    subject = _unique_argument(event, "subject")
    complement = _unique_argument(event, "nominal_complement")
    if subject is None or complement is None or len(subject.members) != 1 or len(complement.members) != 2:
        return None
    divisor = subject.members[0]
    if "natural_divisor" not in divisor.noun_classes or divisor.owned or "unresolved_modifier" in divisor.noun_classes:
        return None
    members = complement.members
    if not all("exclusive_set_member" in member.noun_classes for member in members):
        return None
    if not (sum("number_one" in member.noun_classes for member in members) == 1 and sum("self_reference" in member.noun_classes for member in members) == 1):
        return None
    for anchor in (divisor,) + members:
        head = _derive(head, "exhaustive_one_self_divisors", "exhaustive_natural_divisor_set", anchor.start, anchor.end)
    if "pairwise_distinct" in divisor.noun_classes:
        for value, relation, start, end in divisor.facts:
            if value == "pairwise_distinct":
                head = _derive(head, "greater_than_one", relation, start, end)
    return head


def _finalize_number_conditions(evidence, head):
    """서로 다른 두 약수가 보장되는 완전한 자연수 조건에서만 소수 분류를 낸다."""
    if {"natural_number", "greater_than_one", "exhaustive_one_self_divisors"} <= head.noun_classes and not (head.noun_classes & {"unresolved_modifier", "unresolved_relation"}):
        for fact_class, relation, start, end in head.facts:
            if fact_class in {"greater_than_one", "exhaustive_one_self_divisors"}:
                _emit(evidence, head, relation, start, end, "prime_number")
                head = _derive(head, "prime_number", relation, start, end)
    return head



def _is_nominal_unit(unit):
    """원래 명사 태그 또는 이미 인증된 전체 명사 출처를 같은 소비 권한으로 읽는다."""
    return (unit.tag in _NOUN_TAGS
            or unit.nominal_source is not None and _nominal_source_roles_confirmed(unit.nominal_source))


def _future_outer_clause(units, position):
    """관형절 뒤의 명사와 별도의 종결 서술어가 있는지 한정적으로 확인한다."""
    saw_nominal = False
    for cursor in range(position + 1, len(units)):
        unit = units[cursor]
        if _is_nominal_unit(unit) or unit.tag == "NNB" and unit.form == "것":
            saw_nominal = True
        if unit.tag in _PREDICATE_TAGS and not _adnominal_predicate(units, cursor):
            return saw_nominal
        if unit.tag in {"EC", "EF", "ETN"}:
            return False
    return False




def _exclusive_copular_set(units, position, members):
    """수량 집합의 배타 표지만 허용하고 일반 초점 조사를 계사 보어로 바꾸지 않는다."""
    if len(members) != 2 or not all(member.noun_classes & {"number_one", "self_reference"} for member in members):
        return False
    cursor = position + 1
    while cursor < len(units) and units[cursor].tag == "EP":
        cursor += 1
    return cursor < len(units) and units[cursor].tag == "VCP" and units[cursor].form == "이"



# SPDX-License-Identifier: MIT
def _scan_scope(tokens, indices, evidence, heads, skipped, supplied_units=None, quote_mode=False, event_sink=None):
    """실제 인용 원자의 내보낸 자리만 현재 재스캔의 소유 허가로 사용한다."""
    indices = tuple(indices)
    if supplied_units is None:
        _source_owned_derivation_relations(tokens, {0: indices}, heads, evidence)
    ownership = _QUOTE_OWNERSHIP.get()
    if ownership is None:
        return _scan_scope_impl(tokens, indices, evidence, heads, skipped, supplied_units, quote_mode, event_sink)
    if supplied_units is not None:
        supplied_units = tuple(supplied_units)
    previous = ownership.exports
    ownership.exports = ownership.exported_slots(supplied_units) if quote_mode else ()
    try:
        return _scan_scope_impl(tokens, indices, evidence, heads, skipped, supplied_units, quote_mode, event_sink)
    finally:
        ownership.exports = previous


def _scan_scope_impl(tokens, indices, evidence, heads, skipped, supplied_units=None, quote_mode=False, event_sink=None):
    """공동 명사구ㆍ지연 관형절ㆍ실제 격 논항을 각각 보관하며 절을 분석한다."""
    current_np = []
    coordinated = []
    genitive_owners = ()
    genitive_modifiers = ()
    arguments = []
    modifiers = []
    last_event = None
    previous = None
    pre_negative = False
    short_negative_occurrences = []
    contrast = None
    restored_arguments = ()
    adjuncts = []
    alias_owners = ()
    alias_marker = None
    event_history = []
    pending_coordinands = []
    carried_topics = ()
    count_criterion = None
    unmarked_classification = None
    price_coordinate_topics = ()
    raw_units = _units(tokens, indices, heads, skipped) if supplied_units is None else supplied_units
    units = tuple(_compose_counts(_compose_long_negative_complexes(_compose_verb_complexes(_compose_declared_derivations(raw_units)))))
    for position, unit in enumerate(units):
        price_side_head = (unit.tag == "NNB" and unit.form == "쪽" and modifiers
                           and all(event.tag == "VA" and event.predicate in {"싸", "비싸"}
                                   and not event.negated and not event.arguments for event in modifiers))
        if _is_nominal_unit(unit) or unit.tag == "NNB" and unit.form == "것" or price_side_head:
            head = _Mention(unit.token_index, unit.form, unit.start, unit.end, unit.noun_classes,
                            owners=unit.nominal_owners,
                            facts=tuple(("neutral_modifier", "quoted_nominal_component", start, end)
                                        for start, end in unit.nominal_components) + unit.nominal_facts)
            if price_side_head:
                head = _derive(head, "neutral_modifier", "bound_price_side_head", head.start, head.end)
            if unit.tag == "NNB" and unit.form == "것":
                head = _derive(head, "neutral_modifier", "bound_event_nominal_head", head.start, head.end)
            head = _shared_coordinate_domain(coordinated, current_np, head)
            # 실제 현재 핵어에서 온 유형과 다른 명사로부터 운반된 유형을 구별한다.
            lexical_types = frozenset(_CATEGORY_EFFECTS) | _INTRINSIC_NOUN_CLASSES
            for lexical_class in sorted(unit.noun_classes & lexical_types):
                head = _derive(head, lexical_class, "lexical_nominal_head", head.start, head.end)
            if alias_owners:
                if ("meaning_definition_head" in head.noun_classes and len(alias_owners) == 1
                        and {"currency_value_basis_ratio", "closed_currency_description", "quoted_nominal"}
                        <= alias_owners[0].noun_classes and alias_marker is not None):
                    head = _inherit_nominal(head, alias_owners,
                        {"currency_value_basis_ratio": "currency_value_basis_ratio"}, "closed_currency_meaning_definition")
                    head = _derive(head, "currency_value_basis_ratio", "closed_currency_meaning_alias", *alias_marker)
                if head.noun_classes & {"designation_head", "membership_head"}:
                    head = _Mention(head.token_index, head.form, head.start, head.end,
                                    head.noun_classes | {"designation_reference"}, False, alias_owners)
                alias_owners = ()
            # 파생 분류 용언의 명사 뿌리 앞에서만 실제 무표지 결과 명사구를 보존한다.
            if (count_criterion is not None and len(current_np) == 1 and not coordinated
                    and _classification_result_head(current_np[0])
                    and previous is not None and _is_nominal_unit(previous)
                    and (previous.start, previous.end) == (current_np[0].start, current_np[0].end)
                    and position + 1 < len(units) and units[position + 1].tag == "XSV"
                    and unit.form + units[position + 1].form in _CLASSIFICATION_PREDICATES
                    and _nominal_source_attached(unit, units[position + 1])):
                unmarked_classification = current_np[0]
            if genitive_owners:
                if any(noun_class in _ADNOMINAL_COMPATIBILITY for noun_class in head.noun_classes):
                    genitive_modifiers += (head,)
                else:
                    qualifier = False
                    if all(_modifier_compatible(modifier.noun_classes, head.noun_classes) for modifier in genitive_modifiers):
                        head, qualifier = _genitive_derived_type(genitive_owners, head)
                        _genitive_relations(evidence, genitive_owners, head)
                        if "unresolved_modifier" in head.noun_classes:
                            for owner in genitive_owners:
                                _emit(evidence, owner, "unsupported_relative_modifier", head.start, head.end, "unresolved_modifier")
                    head = _Mention(head.token_index, head.form, head.start, head.end, head.noun_classes, not qualifier, () if qualifier else genitive_owners, head.facts, head.bound_arguments)
                    genitive_owners = ()
                    genitive_modifiers = ()
            if "adverbial_basis_head" in head.noun_classes and previous is not None and previous.tag == "JKO":
                bound = [argument for argument in arguments if argument.role == "object" and argument.particle_start == previous.start and argument.particle_end == previous.end]
                if len(bound) == 1:
                    head = _Mention(head.token_index, head.form, head.start, head.end, head.noun_classes, head.owned, head.owners, head.facts, tuple(bound))
            current_np = _nominal_population_adjunct(current_np, arguments)
            coordinated, current_np, head = _shared_nominal_modifier_head(coordinated, current_np, head)
            ownership = _QUOTE_OWNERSHIP.get()
            if ownership is not None and ownership.separate_siblings(current_np, head):
                current_np = []
            if current_np:
                head = _composed_direct_nominal(evidence, current_np, head)
            if modifiers and not _internal_bound_argument(units, position, modifiers) and not _defer_nominal_modifier(units, position):
                head = _modifier_relations(evidence, modifiers, head)
                modifiers = []
            current_np = [head]
        elif unit.tag == "ALIAS":
            alias_owners = tuple(coordinated + current_np)
            alias_marker = (unit.start, unit.end)
            current_np = []
            coordinated = []
        elif unit.tag == "JKG":
            members = tuple(coordinated + current_np)
            # 앞 항이 실제 소유 구성을 마쳤으면 다음 항의 국소 속격은
            # 현재 항만 소비한다. 앞 항 객체와 그 원래 출처/C는 그대로 둔다.
            local_genitive = (bool(coordinated) and len(current_np) == 1
                              and all(member.owned or member.owners for member in coordinated))
            if local_genitive:
                genitive_owners = tuple(current_np)
            elif len(members) == 1 or (members and all(member.owned for member in members[:-1])):
                genitive_owners = members[-1:]
            else:
                genitive_owners = members if members and _group_effects(members, _TYPE_EFFECTS) else ()
            genitive_modifiers = ()
            current_np = []
            coordinated = coordinated if local_genitive else []
        elif unit.tag == "JC":
            if not current_np:
                # 경계에서 앞 항을 잃은 병렬을 남은 한 항의 확정 분류로 축소하지 않는다.
                fact = ("unresolved_relation", "incomplete_coordinate_group", unit.start, unit.end)
                coordinated.append(_Mention(-1, "", unit.start, unit.end, frozenset({"unresolved_relation"}), facts=(fact,)))
            coordinated.extend(current_np)
            current_np = []
        elif unit.tag in _CASE_ROLES:
            roles = _CASE_ROLES[unit.tag]
            role = roles.get(unit.form, roles.get("*"))
            members = tuple(coordinated + current_np)
            if role and members:
                if role in {"subject", "topic"} and carried_topics:
                    arguments = [argument for argument in arguments if all(argument is not carried for carried in carried_topics)]
                    carried_topics = ()
                if contrast is not None:
                    _contrast_relations(evidence, contrast[0], members, contrast[1])
                    contrast = None
                if role == "via" and unit.form in _BASIS_PARTICLES and len(members) == 1 and "adverbial_basis_head" in members[0].noun_classes:
                    for bound in members[0].bound_arguments:
                        if bound in arguments:
                            arguments.remove(bound)
                    role = "basis"
                if role == "label" and "copular_report_label" in unit.noun_classes and not pre_negative:
                    local_subjects = [argument for argument in arguments if argument.role in {"subject", "topic"}]
                    if len(local_subjects) == 1:
                        local = local_subjects[0]
                        # 상위 용언이 정해질 때까지 원래 명명 주체와 내포절 후보를 보존한다.
                        arguments.append(_Argument("embedded_copular_subject", local.members, local.particle_form, local.particle_start, local.particle_end))
                arguments.append(_Argument(role, members, unit.form, unit.start, unit.end))
            current_np = []
            coordinated = []
            genitive_owners = ()
            genitive_modifiers = ()
        elif unit.tag == "JX":
            members = tuple(coordinated + current_np)
            if unit.form in {"뿐", "만"} and _exclusive_copular_set(units, position, members):
                marked = [_derive(member, "exclusive_set_member", "exhaustive_set_marker", unit.start, unit.end) for member in members]
                coordinated = marked[:-1]
                current_np = marked[-1:]
            else:
                if members and (unit.form in _TOPIC_PARTICLES or unit.form in {"만", "도"}):
                    role = "topic" if unit.form in _TOPIC_PARTICLES else "focus"
                    if role == "topic" and carried_topics:
                        arguments = [argument for argument in arguments if all(argument is not carried for carried in carried_topics)]
                        carried_topics = ()
                    arguments.append(_Argument(role, members, unit.form, unit.start, unit.end))
                current_np = []
                coordinated = []
                genitive_owners = ()
                genitive_modifiers = ()
        elif unit.tag in _PREDICATE_TAGS:
            predicate, start = unit.form, unit.start
            incorporated = None
            if unit.tag == "XSV" and previous is not None and previous.tag in {"NNG", "XR"} and _nominal_source_attached(previous, unit):
                predicate, start = previous.form + unit.form, previous.start
                if previous.tag == "NNG":
                    incorporated = _Mention(previous.token_index, previous.form, previous.start, previous.end, previous.noun_classes)
            event_arguments = _resolve_copular_label_ownership(predicate, tuple(arguments))
            members = tuple(coordinated + current_np)
            if len(members) == 1 and "population_selector" in members[0].noun_classes:
                event_arguments += (_Argument("population", members, members[0].form, members[0].start, members[0].end),)
            if unit.tag in {"VCP", "VCN"} and members:
                event_arguments += (_Argument("nominal_complement", members),)
            elif predicate in {"있", "존재하"} and members and all("exact_count_two" in member.noun_classes for member in members):
                event_arguments += (_Argument("quantity_complement", members),)
            adnominal = _adnominal_predicate(units, position)
            restored_arguments = ()
            if adnominal:
                event_arguments, restored_arguments = _partition_relative_arguments(units, position, predicate, unit.tag, event_arguments)
            event_arguments, chain_outer = _connected_relative_arguments(units, position, predicate, unit.tag, event_arguments, event_history, adnominal)
            restored_arguments += chain_outer
            event_arguments, deferred_members = _independent_coordinate_arguments(units, position, predicate, event_arguments, adnominal)
            pending_coordinands.extend(deferred_members)
            price_coordinate_topics = ()
            if (_coordinates_price_side(units, position) and len(event_arguments) == 1
                    and event_arguments[0].role == "topic" and len(event_arguments[0].members) == 1):
                price_coordinate_topics = event_arguments
                event_arguments = ()
            long_negative = unit.long_negative
            if long_negative is not None and short_negative_occurrences:
                long_negative = replace(long_negative, short_negatives=tuple(short_negative_occurrences))
            negated = pre_negative or long_negative is not None
            last_event = _Event(predicate, start, unit.end, event_arguments, unit.tag, negated, tuple(adjuncts), long_negative,
                                tuple(tokens[index] for index in indices))
            unmarked = unmarked_classification if incorporated is not None else None
            if (incorporated is None and len(members) == 1 and previous is not None
                    and _is_nominal_unit(previous)
                    and (previous.start, previous.end) == (members[0].start, members[0].end)):
                unmarked = members[0]
            _finite_negative_type(evidence, last_event, units, position, tokens, adnominal)
            _quantity_criterion_relations(evidence, count_criterion, last_event, unmarked)
            count_criterion = None
            unmarked_classification = None
            ownership = _QUOTE_OWNERSHIP.get()
            if ownership is not None:
                ownership.remember_event(last_event)
            if event_sink is not None:
                event_sink(last_event, adnominal)
            _long_negative_event_domains(evidence, last_event, quote_mode)
            if contrast is not None:
                if unit.tag == "VCP" and unit.form == "이" and members and not negated:
                    _contrast_relations(evidence, contrast[0], members, contrast[1])
                contrast = None
            _local_participant_chain(evidence, event_history, last_event, adnominal)
            _owned_property_relations(evidence, last_event)
            _family_participant_relations(evidence, last_event)
            if quote_mode:
                _quotation_event_relations(evidence, last_event)
            else:
                _predicate_relations(evidence, last_event)
            if incorporated is not None:
                light_event = _Event(unit.form, start, unit.end, event_arguments + (_Argument("incorporated_object", (incorporated,)),), unit.tag, negated, tuple(adjuncts), long_negative)
                if ownership is not None:
                    ownership.remember_event(light_event)
                _long_negative_event_domains(evidence, light_event, quote_mode)
                if quote_mode:
                    _quotation_event_relations(evidence, light_event)
                else:
                    _predicate_relations(evidence, light_event)
            arguments = []
            carried_topics = ()
            current_np = []
            coordinated = []
            if not adnominal:
                genitive_owners = ()
                genitive_modifiers = ()
            pre_negative = False
            short_negative_occurrences = []
            adjuncts = []
        elif unit.tag == "MAG" and unit.form in _PRE_NEGATIVES:
            pre_negative = True
            short_negative_occurrences.extend(unit.occurrences)
        elif unit.tag == "MAG":
            adjuncts.append(unit.form)
        elif unit.tag not in {"EP", "MM", "MAG", "MAJ"} | _ENDINGS:
            current_np = []
            coordinated = []
            genitive_owners = ()
            genitive_modifiers = ()
            modifiers = []
            arguments = []
            carried_topics = ()
            pre_negative = False
            short_negative_occurrences = []
            contrast = None
            adjuncts = []
            count_criterion = None
            unmarked_classification = None

        endings = ((unit.tag,) if unit.tag in _ENDINGS else ()) + unit.endings
        for ending in endings:
            ending_form = unit.form
            if unit.long_negative is not None and unit.long_negative.final is not None:
                final_occurrence, final_tag = unit.long_negative.final
                ending_form = final_occurrence.form if _occurrence_tags(final_occurrence)[0] == final_tag else ""
            if ending == "EC":
                count_criterion = _owned_count_criterion(last_event, unit)
                unmarked_classification = None
            elif ending in {"EF", "ETN"}:
                count_criterion = None
                unmarked_classification = None
            if ending == "EF":
                event_history.clear()
            negative_nominal = _negative_nominal(last_event)
            continuing_contrast = ending == "EC" and ending_form in _NOMINAL_CONTRAST_CONNECTORS and negative_nominal
            carry_topics = [argument for argument in last_event.arguments if argument.role == "topic"] if continuing_contrast else []
            coordinated_copula = (
                ending == "EC" and ending_form in _COPULAR_COORDINATORS
                and last_event is not None and last_event.tag == "VCP" and last_event.predicate == "이"
                and not last_event.negated and _unique_argument(last_event, "nominal_complement") is not None
            )
            if coordinated_copula:
                owners = [argument for argument in last_event.arguments if argument.role in {"subject", "topic"}]
                carry_topics = owners if len(owners) == 1 else []
            coordinated_price_relative = (ending == "EC" and ending_form == "거나" and position > 0
                                          and _coordinates_price_side(units, position - 1))
            if coordinated_price_relative:
                carry_topics = list(price_coordinate_topics)
            if continuing_contrast:
                contrast = (negative_nominal, last_event)
            elif ending != "ETM":
                contrast = None
            if ending == "ETM" and last_event is not None:
                modifiers.append(last_event)
            elif coordinated_price_relative and last_event is not None:
                modifiers = [last_event]
            else:
                modifiers = []
                genitive_owners = ()
                genitive_modifiers = ()
            arguments = list(restored_arguments) if ending == "ETM" else carry_topics
            carried_topics = tuple(carry_topics) if coordinated_copula or coordinated_price_relative else ()
            current_np = []
            coordinated = list(pending_coordinands) if ending == "ETM" else []
            if ending == "ETM":
                pending_coordinands.clear()
            else:
                pending_coordinands = []
            last_event = None
            restored_arguments = ()
            pre_negative = False
            short_negative_occurrences = []
            adjuncts = []
            alias_owners = ()
        previous = unit
    return tuple(current_np)

# 아래 구성은 범주 운반 성분과 포장 핵어를 구분하여 선언한다.
_CATEGORY_EFFECTS = MappingProxyType({
    key: value for key, value in _TYPE_EFFECTS.items()
    if key not in {"judicial_act", "judicial_institution"}
})
_DESIGNATION_ANCHORS = frozenset({
    "animal", "insect", "bedding", "sleeping_place", "substance", "activity", "sea_harvesting",
    "location", "riverbank", "marriage_event",
    "dwelling_house", "elevated_structure",
    "price", "ordinary_price", "private_law", "private_law_branch", "judicial_function",
    "literary_poetry", "literary_work", "poetry_member", "prime_number", "decimal_number", "minority_quantity",
})
_STRUCTURAL_HEAD_EFFECTS = MappingProxyType({
    "road_structure_head": "elevated_structure",
    "literary_domain": "literary_poetry",
    "literary_work": "literary_poetry",
    "literary_verse": "literary_poetry",
})


@dataclass(frozen=True)
class _NominalPackaging:
    """운반 분류는 수식 성분에서 오고 후행 핵어는 포장만 제공한다."""

    head_class: str
    requires_category_anchor: bool = False
    allowed_classes: frozenset[str] = frozenset()


_NOMINAL_PACKAGINGS = (
    _NominalPackaging("membership_head"),
    _NominalPackaging("form_head", allowed_classes=frozenset({"literary_poetry", "literary_work"})),
    _NominalPackaging("designation_head", True),
    _NominalPackaging("range_head", allowed_classes=frozenset({"price"})),
)




def _inherit_nominal(head, sources, effects, relation):
    """분류와 모든 이전 유효 근거를 현재 출현까지 보존한다."""
    ownership = _QUOTE_OWNERSHIP.get()
    if ownership is not None:
        ownership.observe(head, tuple(span for source in sources for span in ownership.mention_spans(source)))
    shared = _group_effects(sources, effects)
    for source in sources:
        if "quoted_nominal" in source.noun_classes:
            head = _derive(head, "quoted_nominal", "quoted_category_origin", source.start, source.end)
    for semantic_class in sorted(shared):
        for source in sources:
            head = _derive(head, semantic_class, relation, source.start, source.end)
            for fact_class, old_relation, start, end in source.facts:
                if fact_class == semantic_class or effects.get(fact_class) == semantic_class or fact_class in {"unresolved_modifier", "unresolved_relation", "neutral_modifier"}:
                    head = _derive(head, fact_class, old_relation, start, end)
    return head




@dataclass(frozen=True)
class _NeutralFrame:
    """실제 생략 주어와 선택적인 위치ㆍ시점 논항을 요구하는 중립 관계다."""

    predicates: frozenset[str]
    tags: frozenset[str]
    allowed_roles: frozenset[str]
    relation: str
    property_subject_classes: frozenset[str] = frozenset()
    head_classes: frozenset[str] = frozenset()


_NEUTRAL_FRAMES = (
    _NeutralFrame(_NEUTRAL_RELATIVES | {"낮", "싸"}, frozenset({"VA", "VV"}), frozenset({"comparison"}), "attribute"),
    _NeutralFrame(frozenset({"남", "남아있", "남어있", "존재하", "유지되", "이어지", "계속되", "있", "전해지"}), frozenset({"VV", "VX"}), frozenset({"location", "source"}), "persistence_location"),
    _NeutralFrame(frozenset({"높", "낮", "비싸", "싸"}), frozenset({"VA"}), frozenset({"subject", "comparison"}), "owned_price_attribute", frozenset({"price"})),
)
_INHERENT_HEAD_NEUTRAL_FRAMES = (
    _NeutralFrame(frozenset({"뛰어나"}), frozenset({"VA"}), frozenset({"comparison"}), "inherent_type_qualitative_modifier", head_classes=frozenset({"human_ability"})),
    _NeutralFrame(frozenset({"않"}), frozenset({"VX"}), frozenset(), "inherent_type_negative_auxiliary", head_classes=frozenset({"human_ability"})),
    _NeutralFrame(frozenset({"되"}), frozenset({"VV"}), frozenset(), "inherent_type_degree_modifier", head_classes=frozenset({"human_ability"})),
)
_NEUTRAL_PREDICATES = frozenset(value for frame in _NEUTRAL_FRAMES for value in frame.predicates)




@dataclass(frozen=True)
class _ClassificationFrame:
    """능동 목적어와 피동 주어를 동일한 명시적 분류 보어에 연결한다."""

    predicates: frozenset[str]
    member_role: str
    allow_topic: bool = False


_CLASSIFICATION_FRAMES = (
    _ClassificationFrame(frozenset({"분류하", "구분하", "범주화하", "간주하", "규정하"}), "object"),
    _ClassificationFrame(frozenset({"분류되", "구분되", "범주화되", "간주되", "규정되"}), "subject", True),
)
_CLASSIFICATION_PREDICATES = frozenset(value for frame in _CLASSIFICATION_FRAMES for value in frame.predicates)


def _outer_predicate_accepts(units, position, role):
    """바깥 계사가 목적어를 가져갈 수 없는 경우 잘못된 복원을 막는다."""
    saw_nominal = False
    for cursor in range(position + 1, len(units)):
        unit = units[cursor]
        if _is_nominal_unit(unit):
            saw_nominal = True
        if unit.tag in _PREDICATE_TAGS and not _adnominal_predicate(units, cursor):
            if not saw_nominal:
                return False
            return unit.tag not in {"VCP", "VCN"} or role in {"subject", "topic", "complement", "nominal_complement"}
        if unit.tag in {"EC", "EF", "ETN"}:
            return False
    return False


def _classification_parts(event):
    """로/으로 분류 보어 하나와 선언된 구성원 논항만 반환한다."""
    if event.tag not in {"VV", "XSV"}:
        return None
    for frame in _CLASSIFICATION_FRAMES:
        if event.predicate not in frame.predicates:
            continue
        category = _unique_argument(event, "via")
        if category is None or category.particle_form not in {"로", "으로"}:
            return None
        member = _role_or_topic(event, frame.member_role, frame.allow_topic)
        return frame, member, category
    return None


def _classification_result_head(mention):
    """현재 실제 핵어에 선언된 분류ㆍ등급 역할만 인정한다."""
    return (bool(_NOUN_CLASSES.get(mention.form, frozenset()) & {"grade_head", "membership_head"})
            and not mention.noun_classes & {"unresolved_modifier", "unresolved_relation"}
            and not _contains_quoted_nominal(mention))


def _owned_count_criterion_argument(event):
    """독립 장소 논항과 구별하여 실제 에 표지의 소유 계수 기준 하나만 찾는다."""
    criteria = []
    for argument in event.arguments:
        if argument.role != "location" or argument.particle_form != "에" or len(argument.members) != 1:
            continue
        head = argument.members[0]
        if ("count_head" in _NOUN_CLASSES.get(head.form, frozenset())
                and head.owned and len(head.owners) == 1
                and not head.noun_classes & {"unresolved_modifier", "unresolved_relation"}
                and not head.owners[0].noun_classes & {"unresolved_modifier", "unresolved_relation"}
                and not _contains_quoted_nominal(head)):
            criteria.append(argument)
    return criteria[0] if len(criteria) == 1 else None


def _owned_count_criterion(event, connector):
    """소유된 계수 명사구와 실제 에-따르-연결 어미만 다음 사건까지 보관한다."""
    if (event is None or event.negated or event.predicate != "따르" or event.tag != "VV"
            or connector.tag != "EC" or connector.form not in {"아", "어"}
            or any(argument.role not in {"location", "subject", "topic"} for argument in event.arguments)):
        return None
    return event if _owned_count_criterion_argument(event) is not None else None


def _quantity_criterion_relations(evidence, criterion_event, event, unmarked):
    """소유 계수량의 기준 의존과 바로 뒤 실제 분류 결과 논항을 함께 소비한다."""
    if criterion_event is None or event.negated or event.tag not in {"VV", "XSV"}:
        return
    # 나누다의 분류 뜻은 이 소유 계수량ㆍ기준ㆍ결과 핵어 결합 안에서만 허가한다.
    native_classifier = event.predicate == "나누" and event.tag == "VV"
    if not native_classifier and not any(
            event.predicate in frame.predicates and frame.member_role == "object"
            for frame in _CLASSIFICATION_FRAMES):
        return
    objects = tuple(argument for argument in event.arguments if argument.role == "object")
    if objects:
        if len(objects) != 1 or len(objects[0].members) != 1 or unmarked is not None:
            return
        result = objects[0].members[0]
    elif unmarked is not None:
        result = unmarked
    else:
        return
    if not _classification_result_head(result):
        return
    criterion = _owned_count_criterion_argument(criterion_event)
    target = criterion.members[0]
    owner = target.owners[0]
    for relation, start, end in (
        ("owned_count_criterion_owner", owner.start, owner.end),
        ("owned_count_criterion_case", criterion.particle_start, criterion.particle_end),
        ("owned_count_criterion_dependency", criterion_event.start, criterion_event.end),
        ("owned_count_classification_result", result.start, result.end),
        ("owned_count_classification_predicate", event.start, event.end),
    ):
        _emit(evidence, target, relation, start, end, "count_quantity")


def _classify_nominal_complement(evidence, event):
    """행위자에게 범주를 전달하지 않고 실제 구성원만 분류한다."""
    if event.long_negative is not None:
        return
    parts = _classification_parts(event)
    if parts is None:
        return
    frame, members, category = parts
    if members is None:
        return
    for member in members.members:
        if event.negated:
            _emit(evidence, member, "negated_classification", event.start, event.end, "unresolved_relation")
        else:
            _emit_group_type(evidence, member, category.members, _CATEGORY_EFFECTS, "explicit_classification", event)
    # 분류 보어의 실제 유형 핵어 또는 명시적 범주의 소유자도 구성원 증명을 받는다.
    for nominal in category.members:
        for target in _membership_containers(nominal):
            if not _possible_classes(target):
                continue
            if event.negated:
                _emit(evidence, target, "negated_classification_category", event.start, event.end, "unresolved_relation")
            else:
                _emit_group_type(evidence, target, members.members, _MEMBERSHIP_EFFECTS, "classified_member_category", event)
                for semantic_class in _group_effects(members.members, _MEMBERSHIP_EFFECTS):
                    semantic_class = _target_class_constraint(target, semantic_class)
                    _emit(evidence, target, "classification_category_head", nominal.start, nominal.end, semantic_class)
                    _emit(evidence, target, "classification_category_case", category.particle_start, category.particle_end, semantic_class)
                for fact_class, fact_relation, start, end in nominal.facts:
                    if fact_class in {"unresolved_modifier", "unresolved_relation", "neutral_modifier"}:
                        _emit(evidence, target, fact_relation, start, end, fact_class)


def _classification_relative(evidence, event, head):
    """구성원 격이 실제 비어 있고 핵어가 분류와 양립할 때만 보충한다."""
    parts = _classification_parts(event)
    if parts is None:
        return None
    frame, members, category = parts
    if members is not None or any(argument.role == frame.member_role or (frame.allow_topic and argument.role == "topic") for argument in event.arguments):
        return None
    if event.negated:
        return None
    shared = _group_effects(category.members, _CATEGORY_EFFECTS)
    compatible = {value for value in shared if _membership_head_compatible(head, value)}
    if compatible:
        return _derive_group_type(evidence, head, category.members, _CATEGORY_EFFECTS, "relative_classification", event, compatible)
    if _mixed_group(category.members, _CATEGORY_EFFECTS) and _possible_classes(head):
        return _derive_group_type(evidence, head, category.members, _CATEGORY_EFFECTS, "relative_classification", event)
    return None



def _target_class_constraint(target, semantic_class):
    """문학작품이라는 상위 유형은 해당 출현의 가능한 문학 뜻만 제한한다."""
    if semantic_class == "literary_work" and "literary_poetry" in _possible_classes(target):
        return "literary_poetry"
    return semantic_class


@dataclass(frozen=True)
class _EventNominalFrame:
    """사건 핵어 유형과 실제 동작 목적어를 요구하는 명사화 관형절이다."""

    predicates: frozenset[str]
    head_class: str
    object_class: str
    derived_class: str


_EVENT_NOMINAL_FRAMES = (
    _EventNominalFrame(frozenset({"채취하", "캐", "채집하"}), "activity", "sea_product", "sea_harvesting"),
)


def _event_nominal_relative(evidence, event, head):
    """행위자를 사건으로 바꾸지 않고 명시 활동 핵어만 하위 유형화한다."""
    if event.negated or event.tag not in {"VV", "XSV"}:
        return None
    for frame in _EVENT_NOMINAL_FRAMES:
        if event.predicate not in frame.predicates or frame.head_class not in head.noun_classes:
            continue
        objects = _unique_argument(event, "object")
        if objects is None or not objects.members:
            continue
        if any(frame.object_class not in member.noun_classes or member.noun_classes & {"unresolved_modifier", "unresolved_relation"} for member in objects.members):
            continue
        _emit(evidence, head, "event_nominal_category", event.start, event.end, frame.derived_class)
        head = _derive(head, frame.derived_class, "event_nominal_category", event.start, event.end)
        for anchor in objects.members:
            _emit(evidence, head, "event_nominal_object", anchor.start, anchor.end, frame.derived_class)
            head = _derive(head, frame.derived_class, "event_nominal_object", anchor.start, anchor.end)
        return head
    return None




def _decide(token, items, unsupported):
    """서로 다른 의미의 강한 근거는 수량으로 해결하지 않고 유보한다."""
    if unsupported:
        return SenseSelection(token.start, token.end, token.form, None, (), "unsupported_analysis")
    senses = _SENSES_BY_SPELLING[token.form]
    matched = set()
    positive_types = set()
    negative_types = set()
    restrictions = {}
    scoped_unresolved = []
    ownership = _QUOTE_OWNERSHIP.get()
    incompatible = False
    for item in items:
        if item.relation in {"negative_copular_category", "negative_copular_category_predicate"}:
            negative_types.add(item.semantic_class)
            continue
        if _is_domain_observation(item) or item.semantic_class in {"neutral_modifier", "nonassertive_predicate_complex"}:
            continue
        compatible = {sense for sense in senses if item.semantic_class in SENSE_FEATURES[sense].semantic_classes}
        if _is_reading_restriction(item):
            restrictions.setdefault(item.relation, set()).update(compatible)
            continue
        if (item.relation == "unresolved_long_negative_complex" and ownership is not None
                and (item.target_start, item.target_end, item.anchor_start, item.anchor_end) in ownership.domain_unresolved):
            scoped_unresolved.append(item)
            continue
        if not compatible:
            incompatible = True
        else:
            positive_types.add(item.semantic_class)
        matched.update(compatible)
    # 명시 정제 관계의 긍정 함의만 펼치며, 다른 유형의 배타성은 추정하지 않는다.
    positive_types.update(_TYPE_REFINEMENTS[value] for value in tuple(positive_types) if value in _TYPE_REFINEMENTS)
    strong_conflict = len(matched) > 1 or bool(positive_types & negative_types)
    allowed = set.intersection(*(set(values) for values in restrictions.values())) if restrictions else set(senses)
    restriction_conflict = bool(restrictions) and (not allowed or bool(matched and not matched & allowed))
    independent = bool(matched) or bool(restrictions and allowed)
    incompatible = incompatible or bool(scoped_unresolved and not independent)
    selected = (matched & allowed) if matched else (allowed if restrictions else set())
    if strong_conflict or restriction_conflict:
        sense_id, reason = None, "conflicting_evidence"
    elif any(item.relation == "unresolved_quote_ownership" for item in items):
        sense_id, reason = None, "unresolved_quote_ownership"
    elif any(item.relation == "unsupported_relative_modifier" for item in items):
        sense_id, reason = None, "unsupported_modifier"
    elif incompatible:
        sense_id, reason = None, "unsupported_relation"
    elif len(selected) == 1:
        sense_id, reason = next(iter(selected)), "selected"
    else:
        sense_id, reason = None, "insufficient_evidence"
    return SenseSelection(token.start, token.end, token.form, sense_id, tuple(items), reason)


def _registered_nominal_declaration(roots, suffix, source=None):
    """새 파생을 만들지 않고 기존 등록 prefix의 실제 원형만 대조한다."""
    if not roots:
        return None
    root_form = "".join(root.form for root in roots)
    if not _nominal_source_correspondence(root_form, roots[0].start, roots[-1].end, roots, source, require_roles=False):
        return None
    original = roots + (suffix,)
    for left, right in zip(original, original[1:]):
        if left.token_index == right.token_index:
            if right.canonical_index != left.canonical_index + 1:
                return None
        elif left.end != right.start or left.token_index >= right.token_index:
            return None
    return next((item for item in SENSE_DERIVATIONS if item.root == root_form
                 and item.suffix == suffix.form and _occurrence_tags(suffix)[0] == item.suffix_tag), None)


def _registered_nominal_prefix_confirmed(roots, suffix, source=None):
    """prefix 앞의 원래 역할 대응과 실제 접미사 선행 역할만 필요로 한다."""
    direct = all(root.core_role_consistent and root.role_consistent
                 and (root.token_index == suffix.token_index or root.token_roles_consistent) for root in roots)
    confirmed = (isinstance(source, _NominalSource) and tuple(roots) == source.source_occurrences
                 and _nominal_source_roles_confirmed(source))
    return bool(roots) and (direct or confirmed) and suffix.core_role_consistent


def _source_owned_derivation_relations(tokens, scopes, heads, evidence):
    """등록 명사 원천은 선택적 기능 꼬리/긴 부정 인식과 독립해 소비한다."""
    for indices in scopes.values():
        indices = tuple(indices)
        for position, root_index in enumerate(indices):
            root = heads.get(root_index)
            if not isinstance(root, _NominalHead):
                continue
            roots = root.source_occurrences
            members = tuple(dict.fromkeys(item.token_index for item in roots))
            stop = position + len(members)
            if not members or stop >= len(indices) or tuple(indices[position:stop]) != members:
                continue
            suffixes = _original_occurrences(tokens, (indices[stop],))
            if not suffixes:
                continue
            suffix = suffixes[0]
            declaration = _registered_nominal_declaration(roots, suffix, root.nominal_source)
            if declaration is None or root.form != declaration.root or not _registered_nominal_prefix_confirmed(roots, suffix, root.nominal_source):
                continue
            target = _Mention(root_index, root.form, root.start, root.end)
            for value in SENSE_FEATURES[declaration.sense_id].semantic_classes:
                _emit(evidence, target, "source_owned_nominal_derivation", suffix.start, suffix.end, value)


def select_senses(text, tokens, hard_boundaries=frozenset()) -> tuple[SenseSelection, ...]:
    """완전한 토큰 경계에서 인식한 일반 명사마다 자동 선택 또는 유보한다."""
    tokens = tuple(tokens)
    scopes, unsupported = _scope_index(text, tokens, hard_boundaries)
    heads, skipped = _recognize_heads(text, tokens, scopes, unsupported)
    evidence = {index: [] for index in sorted(heads)}
    ownership = _QuoteOwnership(text, hard_boundaries)
    context = _QUOTE_OWNERSHIP.set(ownership)
    try:
        for indices in scopes.values():
            _scan_scope(tokens, indices, evidence, heads, skipped)
        _source_owned_derivation_relations(tokens, scopes, heads, evidence)
        _quotation_relations(text, tokens, hard_boundaries, heads, skipped, evidence)
        _contrast_composition_relations(text, tokens, hard_boundaries, heads, skipped, evidence)
        ownership.finish(heads, evidence)
        return tuple(_decide(heads[index], items, index in unsupported) for index, items in evidence.items())
    finally:
        _QUOTE_OWNERSHIP.reset(context)


# 인용 부호는 별도 명사 원자이며 일반 문장 범위를 변경하지 않는다.
_QUOTE_PAIRS = MappingProxyType({"'": "'", '"': '"', "‘": "’", "“": "”", "「": "」", "『": "』", "«": "»", "‹": "›", "〈": "〉", "《": "》"})
_PASSIVE_NAMING = frozenset({"불리", "명명되", "정의되", "지칭되", "통칭되", "총칭되"})
_QUOTE_RELATIONS = ("copular_category", "nominal_naming", "explicit_definition", "explicit_designation_label", "explicit_classification", "classified_member_category", "typed_membership", "relative_definition", "relative_defined_object", "relative_membership", "relative_classification", "passive_nominal_naming", "explicit_nominal_paraphrase", "explicit_recorded_label")
_RECORDING_PREDICATES = frozenset({"기록하", "기재하", "표기하"})


@dataclass(frozen=True)
class _QuotedNominal:
    """균형 부호의 전체 구간과 명사 내용의 실제 구간을 함께 보관한다."""

    opening: int
    closing: int
    unit: _Unit
    token_indices: tuple[int, ...]
    phrase_units: tuple[_Unit, ...] = ()
    modifier_predicates: tuple[tuple[int, int], ...] = ()


def _naming_label(event):
    """명명 용언에서만 인용격과 명명 결과격을 동일 역할로 읽는다."""
    label = _unique_argument(event, "label")
    via = _unique_argument(event, "via")
    if label is not None:
        return label if via is None else None
    return via if via is not None and via.particle_form in {"로", "으로"} else None


def _internal_bound_argument(units, position, pending):
    """후속 하한 관형절의 내부 비교항에 앞선 계수 관형절을 붙이지 않는다."""
    unit = units[position]
    if "number_one" not in unit.noun_classes or position + 2 >= len(units):
        return False
    particle, predicate = units[position + 1:position + 3]
    if particle.tag != "JKB" or particle.form != "보다" or predicate.tag != "VA" or predicate.form != "크" or not _adnominal_predicate(units, position + 2):
        return False
    natural_head = _Mention(unit.token_index, unit.form, unit.start, unit.end, frozenset({"natural_number"}))
    return any(_numeric_relative(event, natural_head) for event in pending)


def _paraphrase_event_relations(evidence, event):
    """풀이의 목적어와 실제 지정 핵어 결과격만 정의 관계로 연결한다."""
    if event.negated or event.predicate != "풀이하" or event.tag not in {"VV", "XSV"}:
        return
    target = _unique_argument(event, "object")
    definition = _unique_argument(event, "via")
    if target is None or definition is None or definition.particle_form not in {"로", "으로"}:
        return
    if not definition.members or any("designation_head" not in source.noun_classes or "category_package" not in source.noun_classes for source in definition.members):
        return
    for member in target.members:
        _emit_group_type(evidence, member, definition.members, _CATEGORY_EFFECTS, "explicit_nominal_paraphrase", event)


def _recorded_label_relations(evidence, event):
    """실제 기록 대상과 명시 인용 명칭만 연결하고 보고자의 유형은 쓰지 않는다."""
    if event.negated or event.predicate not in _RECORDING_PREDICATES or event.tag not in {"VV", "XSV"}:
        return
    source = _unique_argument(event, "object")
    label = _naming_label(event)
    if source is None or label is None:
        return
    for member in label.members:
        _emit_group_type(evidence, member, source.members, _TYPE_EFFECTS, "explicit_recorded_label", event)
    for member in source.members:
        _emit_group_type(evidence, member, label.members, _TYPE_EFFECTS, "explicit_recorded_label", event)


def _passive_naming_relations(evidence, event):
    """피동 명명의 실제 주어를 이름과 연결하고 보고자ㆍ수령인은 제외한다."""
    if event.negated or event.predicate not in _PASSIVE_NAMING or event.tag not in {"VV", "XSV"}:
        return
    source = _role_or_topic(event, "subject", True)
    label = _naming_label(event)
    if source is None or label is None:
        return
    for target in label.members:
        _emit_group_type(evidence, target, source.members, _TYPE_EFFECTS, "passive_nominal_naming", event)
    for target in source.members:
        _emit_group_type(evidence, target, label.members, _TYPE_EFFECTS, "passive_nominal_naming", event)


def _neutral_opinion_relative(event, nonassertive=False):
    """직접 의견 주어가 있는 차이ㆍ대립만 분류 중립 수식으로 보존한다."""
    if (event.negated and not nonassertive) or event.predicate not in {"다르", "같", "엇갈리", "대립하", "상반되"} or event.tag not in {"VA", "VV", "XSV"}:
        return False
    subject = _unique_argument(event, "subject")
    if subject is None or not subject.members or any("counted_opinion" not in member.noun_classes or member.owned or member.noun_classes & {"unresolved_modifier", "unresolved_relation"} for member in subject.members):
        return False
    return all(argument.role in {"subject", "comitative", "comparison"} for argument in event.arguments)


def _counted_divisor_relative(evidence, event, head):
    """소유ㆍ계수 논항이 실제 자연수의 약수일 때만 정확한 둘을 합성한다."""
    if event.negated or "natural_number" not in head.noun_classes or any(value in _APPROXIMATE_COUNTS for value in event.adjuncts):
        return None
    counted = None
    count = None
    if event.predicate in {"가지", "갖", "보유하"} and event.tag in {"VV", "XSV"} and not any(argument.role in {"subject", "topic"} for argument in event.arguments):
        objects = _unique_argument(event, "object")
        if objects is not None and len(objects.members) == 1:
            counted = objects.members[0]
            if "exactly_two_divisors" not in counted.noun_classes:
                return None
    elif event.predicate in {"있", "존재하"} and event.tag in {"VV", "VA", "VX", "XSV"}:
        subject = _unique_argument(event, "subject")
        quantity = _unique_argument(event, "quantity_complement")
        if subject is not None and len(subject.members) == 1 and quantity is not None and len(quantity.members) == 1:
            counted, count = subject.members[0], quantity.members[0]
            if "exact_count_two" not in count.noun_classes:
                return None
    if counted is None or counted.owned or not (counted.noun_classes & {"divisor", "natural_divisor"}) or counted.noun_classes & {"unresolved_modifier", "unresolved_relation"}:
        return None
    for anchor in (counted,) + ((count,) if count is not None else ()):
        _emit(evidence, head, "owned_exact_divisor_count", anchor.start, anchor.end, "prime_number")
        head = _derive(head, "prime_number", "owned_exact_divisor_count", anchor.start, anchor.end)
        for value, relation, start, end in anchor.facts:
            if value in {"exactly_two_divisors", "divisor", "natural_divisor"}:
                head = _derive(head, "prime_number", relation, start, end)
    return head


def _quote_topology(text, hard_boundaries=frozenset()):
    """열 쌍의 문자 스택에서 완결 뿌리와 미결 소유 구간을 함께 얻는다."""
    closes = frozenset(_QUOTE_PAIRS.values())
    cuts = sorted({0, len(text)} | {cut for cut in hard_boundaries if isinstance(cut, int) and 0 <= cut <= len(text)})
    ranges = []
    unresolved = []
    for left, right in zip(cuts, cuts[1:]):
        stack = []
        pending = []
        invalid = False
        root = None
        for position in range(left, right):
            char = text[position]
            if char not in _QUOTE_PAIRS and char not in closes:
                continue
            if stack and char == stack[-1][1]:
                opening, _ = stack.pop()
                pending.append((opening, position))
            elif stack and char in closes and any(expected == char for _, expected in stack):
                # 조상의 조기 닫힘은 다른 열림을 닫은 척하지 않는다.
                # 남은 실제 열림이 모두 끝나야 뒤를 독립 영역으로 볼 수 있다.
                invalid = True
                matching = max(index for index, (_, expected) in enumerate(stack) if expected == char)
                del stack[matching]
            elif char in _QUOTE_PAIRS:
                if not stack:
                    root = position
                stack.append((position, _QUOTE_PAIRS[char]))
            else:
                if stack:
                    invalid = True
                # 열린 뿌리가 없는 비대칭 닫힘은 단순 구두점으로 남긴다.
            if root is not None and not stack:
                if invalid:
                    unresolved.append((root, position + 1))
                else:
                    ranges.extend(pending)
                pending = []
                invalid = False
                root = None
        if root is not None:
            # 마침표와 줄바꿈은 닫힘의 대용물이 아니다.
            unresolved.append((root, right))
    return tuple(sorted(ranges)), tuple(unresolved)


class _QuoteOwnership:
    """기존 출현ㆍ근거 좌표에만 연결하는 호출 한정 인용 소유 상태다."""

    def __init__(self, text, hard_boundaries):
        self.text = text
        self.hard_boundaries = frozenset(hard_boundaries)
        self.ranges, self.unresolved = _quote_topology(text, hard_boundaries)
        self.dependencies = {}
        self.affected = {}
        self.atoms = ()
        self.exports = ()
        self.long_negative_unresolved = {}
        self.long_negative_links = {}
        self.domain_unresolved = set()

    def valid_span(self, span):
        start, end = span
        return (isinstance(start, int) and isinstance(end, int)
                and 0 <= start < end <= len(self.text))

    def mention_spans(self, mention, seen=None):
        """실제 명사ㆍ소유자ㆍ원래 도출 앵커만 순환 없이 펼친다."""
        seen = set() if seen is None else seen
        identity = id(mention)
        if identity in seen:
            return ()
        seen.add(identity)
        spans = [(mention.start, mention.end)]
        spans.extend((start, end) for _, _, start, end in mention.facts)
        for owner in mention.owners:
            spans.extend(self.mention_spans(owner, seen))
        for argument in mention.bound_arguments:
            spans.extend(self.argument_spans(argument, seen))
        return tuple(span for span in spans if self.valid_span(span))

    def argument_spans(self, argument, seen=None):
        spans = [(argument.particle_start, argument.particle_end)]
        for member in argument.members:
            spans.extend(self.mention_spans(member, seen))
        return tuple(span for span in spans if self.valid_span(span))

    def remember_event(self, event):
        """현재 사건의 실제 격ㆍ참여자ㆍ기존 출처를 서술어 좌표에 묶는다."""
        predicate = (event.start, event.end)
        if not self.valid_span(predicate):
            return
        dependencies = self.dependencies.setdefault(predicate, set())
        for argument in event.arguments:
            dependencies.update(self.argument_spans(argument))

    def expanded(self, spans, dependencies=None):
        dependencies = self.dependencies if dependencies is None else dependencies
        pending = list(spans)
        expanded = set()
        while pending:
            span = pending.pop()
            if not self.valid_span(span) or span in expanded:
                continue
            expanded.add(span)
            pending.extend(dependencies.get(span, ()))
        return expanded

    def chain(self, span):
        start, end = span
        chain = []
        for opening, closing in self.ranges:
            if opening < start and end <= closing:
                chain.append((opening, closing))
            elif start < closing + 1 and opening < end:
                # 부호를 걸치거나 서로 다른 소유를 한 구간으로 덮지 않는다.
                return None
        return tuple(chain)

    def exported_slots(self, units):
        if units is None:
            return ()
        actual = {(unit.token_index, unit.start, unit.end) for unit in units}
        exports = []
        for atom in self.atoms:
            slots = atom.phrase_units or (atom.unit,)
            for slot in slots:
                if (slot.token_index, slot.start, slot.end) not in actual:
                    continue
                spans = [(slot.start, slot.end), (atom.unit.start, atom.unit.end)]
                spans.extend(slot.nominal_components)
                spans.extend((start, end) for _, _, start, end in slot.nominal_facts)
                spans.extend(atom.modifier_predicates)
                for owner in slot.nominal_owners:
                    spans.extend(self.mention_spans(owner))
                exports.extend((span, (atom.opening, atom.closing)) for span in spans)
        return tuple(exports)

    def effective_chain(self, span):
        chain = self.chain(span)
        if chain is None:
            return None
        exported = {
            chain[:chain.index(pair)]
            for slot, pair in self.exports
            if slot == span and pair in chain
        }
        if len(exported) > 1:
            return None
        return next(iter(exported)) if exported else chain

    def separate_siblings(self, modifiers, head):
        """역할 연결 없는 형제 인용 원자 두 개를 한 명사 머리로 합치지 않는다."""
        right_span = (head.start, head.end)
        right = self.chain(right_span)
        if not right or not any(slot == right_span for slot, _ in self.exports):
            return False
        separated = False
        for modifier in modifiers:
            left_span = (modifier.start, modifier.end)
            left = self.chain(left_span)
            if not left or not any(slot == left_span for slot, _ in self.exports):
                continue
            common = 0
            while common < min(len(left), len(right)) and left[common] == right[common]:
                common += 1
            if common == min(len(left), len(right)):
                continue
            ranges = {(opening, closing + 1) for opening, closing in (left[common], right[common])}
            for mention in (modifier, head):
                self.affected.setdefault((mention.start, mention.end), set()).update(ranges)
            separated = True
        return separated

    def observe(self, mention, spans):
        """불확실한 필수 출처를 버리는 대신 해당 출현의 미결을 남긴다."""
        target = (mention.start, mention.end)
        if not self.valid_span(target):
            return
        source_spans = self.mention_spans(mention) + tuple(spans)
        self.dependencies.setdefault(target, set()).update(source_spans)
        # 긴 부정 C는 명사의 실제 사용 출처만 따른다. 인용 방어용 사건 전체
        # 논항 확장은 별도 독립 논항의 도메인에 C를 복제하는 허가가 아니다.
        self.long_negative_links.setdefault(target, set()).update(source_spans)
        expanded = self.expanded((target,))
        affected = set()
        for start, end in expanded:
            affected.update((left, right) for left, right in self.unresolved if start < right and left < end)
            affected.update(self.affected.get((start, end), ()))
        if not affected:
            # 별개의 이전 긍정 관계를 하나의 새 관계로 합쳐 소유 충돌을 만들지 않는다.
            # 누적 출처는 미결 전파에 쓰고, 완결 소유 비교는 현재 관계의 실제 앵커에 한한다.
            current = {span for span in source_spans if self.valid_span(span)}
            chains = {self.effective_chain(span) for span in current}
            if None in chains or len(chains) > 1:
                # 완결 부호도 실제 원자 치환 없이 소유 경계를 건너는 허가는 아니다.
                affected.update((opening, closing + 1) for opening, closing in self.ranges
                                if any(start < closing + 1 and opening < end for start, end in current))
        if affected:
            self.affected.setdefault(target, set()).update(affected)

    def finish(self, heads, evidence):
        """최종 병합 뒤에도 대상ㆍ필수 앵커의 미결 표지를 정확한 좌표로 보존한다."""
        for index, head in heads.items():
            target = (head.start, head.end)
            # 직접 파생 사실과 수동 병합 행도 마지막 닫힘 검사를 우회하지 않는다.
            spans = {target} | {(item.anchor_start, item.anchor_end) for item in evidence[index]}
            for start, end in self.expanded(spans, self.long_negative_links):
                for left, right in self.long_negative_unresolved.get((start, end), ()):
                    item = SenseEvidence("unresolved_long_negative_complex", head.start, head.end,
                                         left, right, "unresolved_relation")
                    if item not in evidence[index]:
                        evidence[index].append(item)
            for start, end in self.expanded(spans):
                for left, right in self.unresolved:
                    if start < right and left < end:
                        self.affected.setdefault(target, set()).add((left, right))
                self.affected.setdefault(target, set()).update(self.affected.get((start, end), ()))
            for start, end in sorted(self.affected.get(target, ())):
                item = SenseEvidence("unresolved_quote_ownership", head.start, head.end,
                                     start, end, "unresolved_relation")
                if item not in evidence[index]:
                    evidence[index].append(item)


def _balanced_quote_ranges(text, hard_boundaries=frozenset()):
    """같은 원문 소유 판단에서 완전히 유효한 뿌리의 짝만 반환한다."""
    ownership = _QUOTE_OWNERSHIP.get()
    if (ownership is not None and ownership.text == text
            and ownership.hard_boundaries == frozenset(hard_boundaries)):
        return ownership.ranges
    return _quote_topology(text, hard_boundaries)[0]


def _quoted_modifier_spine(text, tokens, inside, units, opening, closing):
    """소유가 완전한 관형절 뒤의 순수 명사 연쇄만 바깥 핵어로 삼는다."""
    # 표면 좌표와 보존된 품사열을 먼저 검사한다. 정규 기본형을 원문과
    # 문자열로 같다고 강제하지 않고, 활용은 공급된 형태소의 역할로 읽는다.
    previous_end = opening + 1
    for index in inside:
        token = tokens[index]
        if (not _valid_span(token, len(text)) or token.start < previous_end
                or text[previous_end:token.start].strip()
                or text[token.start:token.end] != token.form):
            return None
        raw_tags = tuple(_tag(tag) for tag in token.tag.split("+"))
        pairs = token.morphemes or ((token.form, token.tag),)
        pair_tags = tuple(_tag(tag) for _, raw in pairs for tag in raw.split("+"))
        if raw_tags != pair_tags or (len(raw_tags) > 1 and not token.morphemes):
            return None
        previous_end = token.end
    if text[previous_end:closing].strip():
        return None

    units = tuple(_compose_long_negative_complexes(_compose_verb_complexes(_compose_declared_derivations(units))))

    start = 0
    predicates = []
    while start < len(units):
        if all(_is_nominal_unit(unit) for unit in units[start:]):
            return tuple(units[start:]), tuple(predicates)
        # 선행 절은 실제 관형형으로 닫혀야 하며, 긴 부정도 같은 소유를 쓴다.
        cursor = start
        nominal = False
        last_nominal = None
        seen_roles = set()
        while cursor < len(units) and units[cursor].tag not in _PREDICATE_TAGS:
            unit = units[cursor]
            if unit.endings:
                return None
            if _is_nominal_unit(unit) or unit.tag == "XR":
                nominal = True
                last_nominal = cursor
            elif unit.tag == "MM":
                if nominal:
                    return None
            elif unit.tag == "MAG":
                if nominal or unit.form in _PRE_NEGATIVES:
                    return None
            elif unit.tag in {"JKS", "JKO", "JKB", "JKC", "JX"}:
                if not nominal:
                    return None
                role = "topic" if unit.tag == "JX" else _CASE_ROLES[unit.tag].get(unit.form, _CASE_ROLES[unit.tag].get("*"))
                if role is None or role in seen_roles:
                    return None
                seen_roles.add(role)
                nominal = False
                last_nominal = None
            else:
                return None
            cursor += 1
        if cursor == len(units):
            return None
        predicate = units[cursor]
        if predicate.tag not in {"VV", "VA", "XSV", "XSA"}:
            return None
        if predicate.long_negative is not None and (
            predicate.long_negative.relative_kind != "direct" or predicate.long_negative.unresolved_dependencies
        ):
            return None
        anchor_start = predicate.start
        if predicate.tag in {"XSV", "XSA"}:
            if not nominal or last_nominal != cursor - 1:
                return None
            root = units[last_nominal]
            # 파생 접미사 앞에 격 없는 별도 명사구를 남기지 않는다.
            if root.tag not in {"NNG", "XR"} or not _contiguous(root, predicate):
                return None
            if cursor - 1 > start and (_is_nominal_unit(units[cursor - 2]) or units[cursor - 2].tag in {"XR", "MM"}):
                return None
            if predicate.tag == "XSV":
                anchor_start = root.start
        elif nominal:
            return None
        cursor += 1
        if predicate.endings:
            if predicate.endings != ("ETM",):
                return None
        else:
            while cursor < len(units) and units[cursor].tag == "EP":
                if units[cursor].endings:
                    return None
                cursor += 1
            if cursor == len(units) or units[cursor].tag != "ETM" or units[cursor].endings:
                return None
            cursor += 1
        predicates.append((anchor_start, predicate.end))
        start = cursor
    return None


def _quote_atoms(text, tokens, hard_boundaries, heads, skipped):
    """완전한 명사구 성분을 보존하고 문장ㆍ제목의 내부 절은 남겨 둔다."""
    atoms = []
    for opening, closing in _balanced_quote_ranges(text, hard_boundaries):
        if any(opening < cut <= closing for cut in hard_boundaries):
            continue
        inside = tuple(index for index, token in enumerate(tokens) if token.start >= opening + 1 and token.end <= closing)
        if not inside:
            continue
        if any(token.start < opening + 1 < token.end or token.start < closing < token.end for token in tokens):
            continue
        units = tuple(_units(tokens, inside, heads, skipped))
        if not units:
            continue
        currency_description = _closed_currency_description_atom(text, tokens, inside, heads, skipped, opening, closing)
        if currency_description is not None:
            atoms.append(currency_description)
            continue
        modifier_predicates = ()
        if any(not _is_nominal_unit(unit) for unit in units):
            parsed = _quoted_modifier_spine(text, tokens, inside, units, opening, closing)
            if parsed is None:
                continue
            units, modifier_predicates = parsed
        if len(units) > 1:
            # 연속된 순수 명사 성분의 실제 표적과 마지막 호환 핵어를 연결한다.
            # 내부 명사의 개수는 제한하지 않으며 유형은 바깥의 명시 정의에서만 얻는다.
            head = units[-1]
            targets = tuple(unit for unit in units[:-1] if unit.token_index in heads)
            if not head.noun_classes & {"function_head", "procedure_head"} or len(targets) != 1:
                continue
            target = targets[0]
            owner = _Mention(target.token_index, target.form, target.start, target.end,
                             target.noun_classes | {"quoted_nominal"})
            if "judicial_function" not in _possible_classes(owner):
                continue
            if not all(text[left.end:right.start].isspace() for left, right in zip(units, units[1:])):
                continue
            if (not modifier_predicates and text[opening + 1:units[0].start].strip()) or text[units[-1].end:closing].strip():
                continue
            if any(text[unit.start:unit.end] != unit.form for unit in units):
                continue
            atom = _Unit(target.form, target.tag, target.start, target.end, target.token_index,
                         target.endings, target.noun_classes | {"quoted_nominal"})
            bound_head = _Unit(head.form, head.tag, head.start, head.end, head.token_index,
                               head.endings, head.noun_classes | {"typed_head_reference", "quoted_nominal"},
                               (owner,), tuple((unit.start, unit.end) for unit in units))
            atoms.append(_QuotedNominal(opening, closing, atom, inside, (bound_head,), modifier_predicates))
            continue
        if modifier_predicates:
            # 이 확장은 실제 표적 성분과 별도 호환 핵어의 소유만 다룬다.
            continue
        unit = units[0]
        if text[opening + 1:unit.start].strip() or text[unit.end:closing].strip():
            continue
        if text[unit.start:unit.end] != unit.form or any(unicodedata.category(char).startswith("P") for char in text[unit.start:unit.end]):
            continue
        atom = _Unit(unit.form, unit.tag, unit.start, unit.end, unit.token_index, unit.endings, unit.noun_classes | {"quoted_nominal"})
        atoms.append(_QuotedNominal(opening, closing, atom, inside))
    ownership = _QUOTE_OWNERSHIP.get()
    if ownership is not None:
        ownership.atoms = tuple(atoms)
    return tuple(atoms)


def _quotation_units(text, tokens, hard_boundaries, heads, skipped, atoms):
    """일반 절단은 유지하고 명시 인용 원자만 바깥 명사구의 자리에 놓는다."""
    delimiters = {position for atom in atoms for position in (atom.opening, atom.closing)}
    separators = [position for position, char in enumerate(text) if position not in delimiters and (char in "\r\n<>{}[]()`" or unicodedata.category(char).startswith("P"))]
    cuts = sorted(set(separators) | {position + 1 for position in separators} | set(hard_boundaries))
    atom_by_first = {atom.token_indices[0]: atom for atom in atoms}
    hidden = {index for atom in atoms for index in atom.token_indices}
    groups = {}
    ordinary = {}
    for index, token in enumerate(tokens):
        if index in atom_by_first:
            atom = atom_by_first[index]
            group = bisect_right(cuts, atom.unit.start)
            groups.setdefault(group, []).extend((unit.token_index, unit) for unit in (atom.phrase_units or (atom.unit,)))
        if index in hidden:
            continue
        if not _valid_span(token, len(text)) or any(token.start <= position < token.end for position in delimiters):
            continue
        group = bisect_right(cuts, token.start)
        if group < len(cuts) and cuts[group] < token.end:
            continue
        if any(token.start <= position < token.end for position in separators):
            continue
        ordinary.setdefault(group, []).append(index)
    for group, indices in ordinary.items():
        # 인용 원자를 사이에 둔 연속 명사 조각은 서로 합치지 않는다.
        blocks = []
        block = []
        atom_indices = tuple(index for index, _ in groups.get(group, ()))
        for index in indices:
            if block and any(block[-1] < atom_index < index for atom_index in atom_indices):
                blocks.append(block)
                block = []
            block.append(index)
        if block:
            blocks.append(block)
        for block in blocks:
            groups.setdefault(group, []).extend((unit.token_index, unit) for unit in _units(tokens, block, heads, skipped))
    for group in sorted(groups):
        units = tuple(unit for _, unit in sorted(groups[group], key=lambda item: item[0]))
        if any("quoted_nominal" in unit.noun_classes for unit in units):
            yield units


def _contains_quoted_nominal(mention):
    """투명 지정 핵어의 실제 소유자까지 인용 명사 참여를 확인한다."""
    return "quoted_nominal" in mention.noun_classes or any(_contains_quoted_nominal(owner) for owner in mention.owners)


def _quotation_event_relations(evidence, event):
    """인용 명사가 실제 참여한 긍정 정의 계열 관계만 별도로 계산한다."""
    if not any(_contains_quoted_nominal(member) for argument in event.arguments for member in argument.members):
        return
    _typed_event_relations(evidence, event)
    if not event.negated and event.predicate in _NAMING_PREDICATES and event.tag in {"VV", "XSV"} and not (event.predicate == "하" and event.tag == "XSV"):
        labels = _naming_label(event)
        source = _role_or_topic(event, "object", True)
        if labels is not None and source is not None:
            for target in labels.members:
                _emit_group_type(evidence, target, source.members, _TYPE_EFFECTS, "nominal_naming", event)
            for target in source.members:
                _emit_group_type(evidence, target, labels.members, _TYPE_EFFECTS, "nominal_naming", event)
    _passive_naming_relations(evidence, event)
    _paraphrase_event_relations(evidence, event)
    _recorded_label_relations(evidence, event)
    _definition_event_relations(evidence, event)
    _classification_event_relations(evidence, event)


def _guard_unclosed_modified_nominals(text, tokens, hard_boundaries, heads, skipped, evidence):
    """닫힘 없는 새 관형 명사구가 일반 절 경로로 외부 정의를 얻는 것을 막는다."""
    balanced = {opening for opening, _ in _balanced_quote_ranges(text, hard_boundaries)}
    for opening, char in enumerate(text):
        if char not in _QUOTE_PAIRS or opening in balanced:
            continue
        stop = next((position for position in range(opening + 1, len(text))
                     if position in hard_boundaries or text[position] in ".!?\r\n"
                     or unicodedata.category(text[position]).startswith("P")), len(text))
        inside = []
        for index, token in enumerate(tokens):
            if token.start < opening + 1 or token.end > stop:
                continue
            if _tag(token.tag) in {"JKS", "JKO", "JKB", "JKC", "JX"}:
                units = tuple(_units(tokens, tuple(inside), heads, skipped))
                parsed = _quoted_modifier_spine(text, tokens, tuple(inside), units, opening, token.start)
                if parsed is not None:
                    spine, predicates = parsed
                    targets = tuple(unit for unit in spine[:-1] if unit.token_index in heads)
                    if predicates and spine[-1].noun_classes & {"function_head", "procedure_head"} and len(targets) == 1:
                        target = targets[0]
                        if any(item.anchor_start >= token.start for item in evidence[target.token_index]):
                            owner = _Mention(target.token_index, target.form, target.start, target.end)
                            _emit(evidence, owner, "unclosed_attributive_nominal", opening, spine[-1].end, "unresolved_relation")
            inside.append(index)


def _quotation_relations(text, tokens, hard_boundaries, heads, skipped, evidence):
    """기존 내부 관계와 새 인용 명사 관계를 각 출현의 실제 좌표로 합친다."""
    _guard_unclosed_modified_nominals(text, tokens, hard_boundaries, heads, skipped, evidence)
    atoms = _quote_atoms(text, tokens, hard_boundaries, heads, skipped)
    if not atoms:
        return
    candidate = {index: [] for index in evidence}
    for units in _quotation_units(text, tokens, hard_boundaries, heads, skipped, atoms):
        _scan_scope(tokens, (), candidate, heads, skipped, supplied_units=units, quote_mode=True)
    quote_by_index = {atom.unit.token_index: atom for atom in atoms}
    for index, items in candidate.items():
        # 구조/C 관찰만 독립 보존한다. 이 행은 아래의 기존 의미 운반ㆍ경계
        # 유형ㆍ관형 중립화 허가를 대신하지 않는다.
        for item in items:
            observation = _is_domain_observation(item) or (item.relation, item.semantic_class) in {
                ("licensed_long_negative_complex", "nonassertive_predicate_complex"),
                ("unresolved_long_negative_complex", "unresolved_relation"),
            }
            if observation and item not in evidence[index]:
                evidence[index].append(item)
        if not any(item.relation.startswith(_QUOTE_RELATIONS) for item in items):
            continue
        atom = quote_by_index.get(index)
        if atom is not None and atom.modifier_predicates:
            # 실제 외부 정의가 성립한 동일 표적에서만, 이제 구조적으로 소유가
            # 확인된 선행 관형절의 미지원 표지를 중립 근거로 바꾼다. 다른 뜻의
            # 긍정ㆍ부정 근거와 다른 출현의 근거는 그대로 보존한다.
            predicates = frozenset(atom.modifier_predicates)
            retained = []
            for item in evidence[index]:
                if item.relation == "unsupported_relative_modifier" and (item.anchor_start, item.anchor_end) in predicates:
                    item = SenseEvidence("explicitly_owned_attributive_modifier", item.target_start,
                                         item.target_end, item.anchor_start, item.anchor_end, "neutral_modifier")
                if item not in retained:
                    retained.append(item)
            evidence[index][:] = retained
        for item in items:
            if item not in evidence[index]:
                evidence[index].append(item)
        if index in quote_by_index:
            atom = quote_by_index[index]
            for semantic_class in sorted({item.semantic_class for item in items if not _is_domain_effect(item) and item.semantic_class in _possible_classes(_Mention(index, heads[index].form, heads[index].start, heads[index].end))}):
                boundary = SenseEvidence("quoted_nominal_boundary", atom.unit.start, atom.unit.end, atom.opening, atom.closing + 1, semantic_class)
                if boundary not in evidence[index]:
                    evidence[index].append(boundary)
                for opening, closing in _balanced_quote_ranges(text, hard_boundaries):
                    if opening < atom.opening and atom.closing < closing:
                        container = SenseEvidence("quoted_containment_boundary", atom.unit.start, atom.unit.end, opening, closing + 1, semantic_class)
                        if container not in evidence[index]:
                            evidence[index].append(container)



# 아래 틀은 직접 핵어의 정체성과 수식절에서 언급한 대상을 별도로 보존한다.


@dataclass(frozen=True)
class _PartIdentityFrame:
    """부품 보유의 빈 논항과 후행 명사의 실제 유형을 함께 검사한다."""

    predicates: frozenset[str]
    role: str
    effects: Mapping[str, str]


_PART_IDENTITY_FRAMES = (
    _PartIdentityFrame(frozenset({"가지", "갖", "갖추", "지니", "보유하", "간직하", "보존하", "유지하"}), "object", MappingProxyType({
        "biological_part": "animal", "physical_constituent": "substance", "physical_content": "substance",
        "house_part": "dwelling_house", "elevated_structure_part": "elevated_structure",
        "poetry_part": "literary_poetry", "decimal_part": "decimal_number",
    })),
    _PartIdentityFrame(frozenset({"남", "남아있", "남어있", "보존되", "유지되", "있"}), "subject", MappingProxyType({
        "house_part": "dwelling_house", "elevated_structure_part": "elevated_structure",
        "biological_part": "animal", "physical_constituent": "substance", "poetry_part": "literary_poetry",
    })),
)
_PLACEMENT_PREDICATES = frozenset({"놓이", "설치되", "건설되", "있", "존재하", "자리하"})


def _explicit_referring_term(mention):
    """따옴표 또는 실제 지정 핵어가 지칭 용법을 허가한다."""
    return bool(mention.noun_classes & {"quoted_nominal", "designation_head", "designation_reference"})


def _identity_relative(evidence, event, head):
    """독립 유형을 요구하는 보유와 높은 위치의 구조 관계만 합성한다."""
    if event.negated:
        return None
    if event.predicate == "높" and event.tag == "VA" and "location_head" in head.noun_classes and not event.arguments:
        return _derive(head, "elevated_location", "elevated_location_attribute", event.start, event.end)
    if event.tag not in {"VV", "VX", "XSV"} and not (event.tag == "VA" and event.predicate in {"있", "존재하"}):
        return None
    if event.predicate in _PLACEMENT_PREDICATES and "road_structure_head" in head.noun_classes and not any(argument.role in {"subject", "topic"} for argument in event.arguments):
        location = _unique_argument(event, "location")
        if location is not None and location.particle_form == "에" and location.members and all("elevated_location" in member.noun_classes and not member.noun_classes & {"unresolved_modifier", "unresolved_relation"} for member in location.members):
            return _derive_group_type(evidence, head, location.members, {"elevated_location": "elevated_structure"}, "elevated_structural_location", event)
    for frame in _PART_IDENTITY_FRAMES:
        if event.predicate not in frame.predicates:
            continue
        anchors = _unique_argument(event, frame.role)
        if anchors is None or not anchors.members:
            continue
        permitted = {frame.role, "location"} if frame.role == "subject" else {frame.role}
        if any(argument.role not in permitted for argument in event.arguments):
            continue
        if any(member.owned or member.noun_classes & {"unresolved_modifier", "unresolved_relation"} for member in anchors.members):
            continue
        shared = _group_effects(anchors.members, frame.effects)
        compatible = {value for value in shared if _membership_head_compatible(head, value)}
        if compatible:
            return _derive_group_type(evidence, head, anchors.members, frame.effects, "retained_nominal_part", event, compatible)
    return None





def _independent_nominal_identity(head):
    """직접 유형 또는 출처가 확인된 범주 포장의 현재 핵어 정체성만 읽는다."""
    if head.noun_classes & {"unresolved_modifier", "unresolved_relation"}:
        return False
    return any(relation in {"lexical_nominal_head", "composed_nominal_head_identity"} and start == head.start and end == head.end for _, relation, start, end in head.facts)


def _low_count_relative(evidence, event, head):
    """긍정 적다의 빈 주어가 실제 계수 핵어일 때만 소량 유형을 합성한다."""
    if event.predicate != "적" or event.tag != "VA" or event.negated or event.arguments:
        return None
    if not head.noun_classes & {"counted_human", "counted_opinion"} or head.owned:
        return None
    if head.noun_classes & {"unresolved_modifier", "unresolved_relation"}:
        return None
    head = _derive(head, "minority_quantity", "low_count_nominal", event.start, event.end)
    head = _derive(head, "minority_quantity", "counted_nominal_head", head.start, head.end)
    _emit(evidence, head, "low_count_nominal", event.start, event.end, "minority_quantity")
    _emit(evidence, head, "counted_nominal_head", head.start, head.end, "minority_quantity")
    return head


__all__ = [
    "SemanticToken", "SenseFeatures", "SenseEvidence", "SenseSelection",
    "SENSE_FEATURES", "TARGET_SPELLINGS", "select_senses",
]


# 독립 합성 확장: 각 분류는 현재 핵어와 허용 관계를 함께 요구한다.
_NOUN_CLASSES = MappingProxyType(dict(_NOUN_CLASSES) | {
    "건물": frozenset({"trade_item", "building_head"}),
    "구조물": frozenset({"structure_head", "physical_thing"}),
    "물체": frozenset({"physical_thing"}),
    "물건": frozenset({"trade_item", "physical_thing"}),
    "본바탕": frozenset({"constitutive_basis_head"}),
    "바탕": _NOUN_CLASSES["바탕"] | {"constitutive_basis_head"},
    "기와": frozenset({"house_part"}), "대들보": frozenset({"house_part"}),
    "지면": frozenset({"ground_reference"}), "땅": frozenset({"ground_reference"}),
    "밤": frozenset({"night_time"}), "야간": frozenset({"night_time"}),
    "자리": frozenset({"location_head"}), "침상": frozenset({"sleeping_place", "bedding"}),
    "일부": frozenset({"part_head"}), "부분": frozenset({"part_head"}),
    "전체": frozenset({"total_modifier"}),
    "주민": frozenset({"human", "counted_human"}),
    "학생": frozenset({"human", "counted_human"}),
    "사람들": frozenset({"human", "counted_human"}),
    "아래": frozenset({"below_position_head"}), "밑": frozenset({"below_position_head"}),
    "숫자": frozenset({"digit_head"}), "자릿수": frozenset({"digit_count_head"}),
    "거래가": frozenset({"price"}), "값": frozenset({"price"}),
    "거래": frozenset({"transaction_modifier"}),
    "국가": frozenset({"state_modifier"}),
    "민사": frozenset({"legal_case_modifier"}), "형사": frozenset({"legal_case_modifier"}),
    "재산": frozenset({"legal_relation"}), "계약": frozenset({"legal_relation"}),
})
_CASE_ROLES = MappingProxyType(dict(_CASE_ROLES) | {
    "JKB": MappingProxyType(dict(_CASE_ROLES["JKB"]) | {"가운데": "population", "중": "population", "중에서": "population"}),
})
_VERB_COMPLEXES = _VERB_COMPLEXES + (
    _VerbComplex(frozenset({"VV"}), "EC", frozenset({"아", "어"}), "VX", frozenset({"주"}), "VV"),
)
_ADNOMINAL_COMPATIBILITY = MappingProxyType(dict(_ADNOMINAL_COMPATIBILITY) | {
    "state_modifier": frozenset({"function_head"}),
    "legal_case_modifier": frozenset({"judicial_act"}),
    "total_modifier": frozenset({"counted_human", "counted_opinion"}),
    "transaction_modifier": frozenset({"price"}),
    "value_modifier": frozenset({"assessment_head"}),
})
_COMPOSITION_PACKAGES = (
    ("building_head", frozenset({"dwelling_house"})),
    ("legal_type_head", frozenset({"private_law"})),
    ("structure_head", frozenset({"elevated_structure", "road_structure_head"})),
    ("literary_domain", frozenset({"literary_poetry", "literary_work"})),
)


def _package_nominal(sources, head, relation):
    """호환 실제 핵어에만 범주를 포장하고 미지ㆍ혼합 관계는 보존한다."""
    # 체계는 실제 법 유형 수식어가 있는 범주 핵어일 때만 소속 관계를 받는다.
    if "system_head" in head.noun_classes and len(sources) == 1 and "legal_type_head" in sources[0].noun_classes and not sources[0].noun_classes & {"unresolved_modifier", "unresolved_relation"}:
        return _Mention(head.token_index, head.form, head.start, head.end,
                        head.noun_classes | {"membership_head"}, False, sources, head.facts, head.bound_arguments)
    for head_class, permitted in _COMPOSITION_PACKAGES:
        if head_class not in head.noun_classes or not sources:
            continue
        effects = dict(_CATEGORY_EFFECTS)
        effects["road_structure_head"] = "road_structure_head"
        shared = _group_effects(sources, effects) & permitted
        if shared:
            head = _inherit_nominal(head, sources, {key: value for key, value in effects.items() if value in shared}, relation)
            head = _derive(head, "category_package", relation + "_packaging", head.start, head.end)
            for value in shared:
                if all(_independent_nominal_identity(source) for source in sources):
                    head = _derive(head, value, "composed_nominal_head_identity", head.start, head.end)
            return head
    if len(sources) == 1 and _modifier_compatible(sources[0].noun_classes, head.noun_classes):
        for value, old_relation, start, end in sources[0].facts:
            if value in {"unresolved_modifier", "unresolved_relation", "neutral_modifier"}:
                head = _derive(head, value, old_relation, start, end)
        return head

    for construction in _NOMINAL_PACKAGINGS:
        if construction.head_class not in head.noun_classes or not sources:
            continue
        if construction.requires_category_anchor and any(not ("category_package" in source.noun_classes or source.noun_classes & _DESIGNATION_ANCHORS) for source in sources):
            if len(sources) == 1 and "quoted_nominal" in sources[0].noun_classes and _possible_classes(sources[0]):
                return _Mention(head.token_index, head.form, head.start, head.end,
                                head.noun_classes | {"designation_reference"}, False, sources, head.facts, head.bound_arguments)
            continue
        shared = _group_effects(sources, _CATEGORY_EFFECTS)
        if construction.allowed_classes:
            shared &= construction.allowed_classes
        if not shared:
            if _mixed_group(sources, _CATEGORY_EFFECTS):
                for source in sources:
                    head = _derive(head, "unresolved_relation", "incoherent_category_composition", source.start, source.end)
                return head
            # 아직 뜻이 없는 수식어도 소속 구문의 실제 분류 대상 위치는 보존한다.
            if construction.head_class == "membership_head" and len(sources) == 1:
                return _Mention(head.token_index, head.form, head.start, head.end, head.noun_classes, False, sources, head.facts, head.bound_arguments)
            continue
        effects = {key: value for key, value in _CATEGORY_EFFECTS.items() if value in shared}
        head = _inherit_nominal(head, sources, effects, relation)
        head = _derive(head, "category_package", relation + "_packaging", head.start, head.end)
        if all(_independent_nominal_identity(source) for source in sources):
            for semantic_class in sorted(shared):
                head = _derive(head, semantic_class, "composed_nominal_head_identity", head.start, head.end)
        return head
    return None


def _compose_nominal_component_types(pairs):
    """정확한 명사 성분 순서에 동일한 호환 합성을 적용한다."""
    if len(pairs) < 2 or any(tag != "NNG" for _, tag in pairs):
        return frozenset()
    if (_NOUN_CLASSES.get(pairs[0][0], frozenset()) & {"metal_currency_basis", "foreign_currency_basis"}
            and pairs[1] == ("기준", "NNG")):
        if len(pairs) == 2:
            return frozenset({"currency_basis_head"})
        if len(pairs) == 3 and pairs[2] == ("비율", "NNG"):
            return frozenset({"currency_ratio_head", "currency_standard_basis_ratio"})
    first = _Mention(-1, pairs[0][0], 0, 1, _NOUN_CLASSES.get(pairs[0][0], frozenset()))
    for index, (form, _) in enumerate(pairs[1:], 1):
        head = _Mention(-1, form, index, index + 1, _NOUN_CLASSES.get(form, frozenset()))
        packaged = _package_nominal((first,), head, "fused_nominal_composition")
        if packaged is None:
            if "judicial_act" in first.noun_classes and "function_head" in head.noun_classes:
                packaged = _derive(head, "judicial_function", "judicial_action_nominal", first.start, first.end)
            elif "literary_domain" in first.noun_classes and "creative_work" in head.noun_classes:
                packaged = _derive(head, "literary_work", "literary_work_composition", first.start, first.end)
            else:
                for owner_class, head_class, result_class in _GENITIVE_TYPE_CONSTRUCTIONS:
                    if owner_class in first.noun_classes and head_class in head.noun_classes:
                        packaged = _derive(head, result_class, "declared_nominal_component_type", first.start, first.end)
                        break
                if packaged is None:
                    return frozenset()
        first = packaged
    return first.noun_classes






def _shared_coordinate_domain(coordinated, current, head):
    """개인 간 관계의 병렬 뒤 항에 동일한 명시 영역 출처만 공유한다."""
    if current or not coordinated or "legal_relation" not in head.noun_classes:
        return head
    source = coordinated[-1]
    if "private_relation" not in source.noun_classes or source.noun_classes & {"unresolved_modifier", "unresolved_relation"}:
        return head
    for value, relation, start, end in source.facts:
        if value == "private_relation":
            head = _derive(head, value, "coordinated_private_relation", start, end)
    return head


def _valid_members(argument, required):
    """실제 공동 논항의 모든 성분이 요구 유형이며 해결되지 않은 소유가 없음을 확인한다."""
    return argument is not None and bool(argument.members) and all(member.noun_classes & required and not member.noun_classes & {"unresolved_modifier", "unresolved_relation"} and not member.owned for member in argument.members)


def _derive_relation(evidence, head, value, relation, event, anchors):
    """현재 핵어에 관계ㆍ실제 논항ㆍ이전 출처를 함께 기록한다."""
    head = _derive(head, value, relation, event.start, event.end)
    _emit(evidence, head, relation, event.start, event.end, value)
    for anchor in anchors:
        head = _derive(head, value, relation + "_anchor", anchor.start, anchor.end)
        _emit(evidence, head, relation + "_anchor", anchor.start, anchor.end, value)
        for old_value, old_relation, start, end in anchor.facts:
            if old_value not in {"unresolved_modifier", "unresolved_relation"}:
                head = _derive(head, value, old_relation, start, end)
    return head




def _nondefining_head_modifier(event, head, nonassertive=False):
    """비본질적 수식은 독립 유형을 유지하고 정의 관계는 그대로 검사한다."""
    if not event.negated and event.predicate in {"채취하", "채집하", "캐"} and event.tag in {"VV", "XSV"} and not any(argument.role == "object" for argument in event.arguments) and all(argument.role in {"subject", "location"} for argument in event.arguments):
        subject = _unique_argument(event, "subject")
        if _valid_members(subject, {"human"}):
            return "collected_object_identity"

    explicit = _independent_nominal_identity(head)
    if not explicit or (event.negated and not nonassertive) or event.tag not in {"VV", "VA", "XSV", "XSA"}:
        return ""
    defining = _DEFINITION_PREDICATES | _CLASSIFICATION_PREDICATES | _NAMING_PREDICATES | _PASSIVE_NAMING | _RECORDING_PREDICATES | {"풀이하"}
    if event.predicate in defining or any(event.predicate in construction.predicates for construction in _MEMBERSHIP_CONSTRUCTIONS):
        return ""
    # 동형 서술어의 다른 품사 틀은 이미 소유한 유형 머리를 거부할 근거가 아니다.
    if any(frame.role == "head" and (not frame.predicate_tag or frame.predicate_tag == event.tag)
           for frame in _FRAMES.get(event.predicate, ())):
        return ""
    if any(event.predicate in frame.predicates for frame in _EVENT_NOMINAL_FRAMES + _PART_IDENTITY_FRAMES):
        return ""
    if any(member.noun_classes & {"unresolved_modifier", "unresolved_relation"} for argument in event.arguments for member in argument.members):
        return ""
    return "independent_head_identity"


def _owned_property_relations(evidence, event):
    """화제의 실제 물성 주어를 서술하는 국소 이중 주어 관계만 연결한다."""
    if (event.negated and event.long_negative is None) or event.tag != "VA" or event.predicate not in {"높", "낮", "크", "작", "같", "다르"}:
        return
    topic = _unique_argument(event, "topic")
    subject = _unique_argument(event, "subject")
    if topic is None or len(topic.members) != 1 or not _valid_members(subject, {"physical_property"}) or any(argument.role not in {"topic", "subject", "comparison"} for argument in event.arguments):
        return
    target = topic.members[0]
    if "substance" not in _possible_classes(target):
        return
    if _long_negative_required_base(evidence, event, target, "substance"):
        return
    if event.long_negative is not None:
        _emit_domain_restriction(evidence, target, {"substance"}, event, "owned_property_domain", subject.members)
        return
    _emit(evidence, target, "topic_owned_physical_property_predicate", event.start, event.end, "substance")
    for anchor in subject.members:
        _emit(evidence, target, "topic_owned_physical_property", anchor.start, anchor.end, "substance")


def _local_participant_chain(evidence, history, event, adnominal):
    """명시 허용된 포획ㆍ몸 부분 관찰ㆍ방출의 생략 참여자만 연결한다."""
    if adnominal or event.negated:
        history.clear()
        return
    if event.predicate in {"놓아주", "놓어주", "풀어주", "풀아주", "방생하", "방출하"} and event.tag in {"VV", "XSV"} and not any(argument.role == "object" for argument in event.arguments) and len(history) >= 2:
        captured, inspected = history[-2:]
        objects = _unique_argument(captured, "object")
        parts = _unique_argument(inspected, "object")
        if captured.predicate in {"붙잡", "잡", "포획하"} and captured.tag in {"VV", "XSV"} and inspected.predicate in {"살피", "관찰하", "검사하"} and inspected.tag in {"VV", "XSV"} and objects is not None and len(objects.members) == 1 and _valid_members(parts, {"biological_part"}) and all(argument.role == "object" for argument in inspected.arguments):
            target = objects.members[0]
            if not target.owned and "animal" in _possible_classes(target):
                for anchor in parts.members:
                    _emit(evidence, target, "captured_part_inspection_owner", anchor.start, anchor.end, "animal")
                _emit(evidence, target, "captured_participant", captured.start, captured.end, "animal")
                _emit(evidence, target, "continued_part_inspection", inspected.start, inspected.end, "animal")
                _emit(evidence, target, "same_participant_release", event.start, event.end, "animal")
    history.append(event)
    if len(history) > 3:
        del history[:-3]

_QUOTE_RELATIONS = _QUOTE_RELATIONS + ("genitive_part", "direct_nominal_modifier", "quantified_human_participant")


_NOUN_CLASSES = MappingProxyType(dict(_NOUN_CLASSES) | {
    "가운데": frozenset({"population_selector"}),
})
_MEMBERSHIP_CONSTRUCTIONS = _MEMBERSHIP_CONSTRUCTIONS + (
    _MembershipConstruction(frozenset({"묶", "통합하"}), "subject", "object"),
)




def _defer_nominal_modifier(units, position):
    """모집단 선택의 왼쪽 명사는 별도 실체이므로 먼저 수식을 적용한다."""
    if position + 1 >= len(units) or not _is_nominal_unit(units[position + 1]):
        return False
    return "population_selector" not in units[position + 1].noun_classes




def _nominal_component_classes(pairs):
    """완전한 융합 명사의 실제 호환 수식 구성을 병렬 연결 허가로 보존한다."""
    classes = _compose_nominal_component_types(pairs)
    if len(pairs) >= 2 and all(tag == "NNG" for _, tag in pairs):
        head_classes = _NOUN_CLASSES.get(pairs[-1][0], frozenset())
        modifiers = [_NOUN_CLASSES.get(form, frozenset()) for form, _ in pairs[:-1]]
        if modifiers and all(_modifier_compatible(modifier, head_classes) for modifier in modifiers):
            classes |= {"coordinated_adnominal_head"}
    return classes


def _shared_nominal_modifier_head(coordinated, current, head):
    """병렬 항 전체가 같은 실제 후행 핵어의 호환 수식어일 때만 합친다."""
    if not coordinated or (not current and "coordinated_adnominal_head" not in head.noun_classes):
        return coordinated, current, head
    sources = tuple(coordinated + current)
    if any(source.owned or source.noun_classes & {"unresolved_modifier", "unresolved_relation"} or not _modifier_compatible(source.noun_classes, head.noun_classes) for source in sources):
        return coordinated, current, head
    for semantic_class in head.noun_classes:
        if semantic_class not in _TYPE_EFFECTS and semantic_class not in _GENITIVE_EFFECTS:
            continue
        for source in sources:
            head = _derive(head, semantic_class, "shared_nominal_modifier_source", source.start, source.end)
            for value, relation, start, end in source.facts:
                if value in {"neutral_modifier", "unresolved_modifier", "unresolved_relation"}:
                    head = _derive(head, value, relation, start, end)
    return [], [], head


def _classification_event_relations(evidence, event):
    """로 분류 보어와 라고 명명 분류의 실제 격을 각각 보존한다."""
    if event.long_negative is not None:
        return
    _classify_nominal_complement(evidence, event)
    if event.tag not in {"VV", "XSV"}:
        return
    label = _naming_label(event)
    if label is None or label.particle_form not in {"라고", "이라고", "라"}:
        return
    for frame in _CLASSIFICATION_FRAMES:
        if event.predicate not in frame.predicates:
            continue
        members = _role_or_topic(event, frame.member_role, frame.allow_topic)
        if members is None:
            return
        for target in label.members:
            if event.negated:
                _emit(evidence, target, "negated_classification_label", event.start, event.end, "unresolved_relation")
            else:
                _emit_group_type(evidence, target, members.members, _CATEGORY_EFFECTS, "explicit_classification_label", event)
                for value in _group_effects(members.members, _CATEGORY_EFFECTS):
                    _emit(evidence, target, "classification_label_case", label.particle_start, label.particle_end, _target_class_constraint(target, value))
        return


_BOUND_NOMINAL_COMPOUND_LICENSES = MappingProxyType({
    "자": frozenset({"숫자"}),
})


def _render_nominal_constituents(pairs):
    """명사 성분과 실제 사이시옷 정규 표지의 합성 표면을 검사한다."""
    output = ""
    saw_noun = False
    for form, raw_tag in pairs:
        tag = _tag(raw_tag)
        if tag in {"NNG", "NNB"}:
            if not saw_noun and tag != "NNG":
                return None
            output += form
            saw_noun = True
        elif tag == "Z_SIOT" and form == "ᆺ" and output:
            value = ord(output[-1])
            if not 0xAC00 <= value <= 0xD7A3 or (value - 0xAC00) % 28:
                return None
            output = output[:-1] + chr(value + 19)
        else:
            return None
    return output if saw_noun else None


def _units(tokens, indices, heads, skipped):
    """원래 표면ㆍ성분ㆍ인접 경계가 모두 맞는 허가 복합 명사만 묶는다."""
    indices = tuple(indices)
    position = 0
    ordinary = []
    while position < len(indices):
        index = indices[position]
        stop = position
        pairs = []
        members = []
        while stop < len(indices):
            member = indices[stop]
            token = tokens[member]
            parts = token.morphemes or ((token.form, token.tag),)
            if any(_tag(tag) not in {"NNG", "NNB", "Z_SIOT"} for _, tag in parts):
                break
            if members and tokens[members[-1]].end != token.start:
                break
            pairs.extend(parts)
            members.append(member)
            stop += 1
        surface = "".join(tokens[member].form for member in members)
        bound = [form for form, tag in pairs if _tag(tag) == "NNB"]
        licensed = bool(bound) and all(surface in _BOUND_NOMINAL_COMPOUND_LICENSES.get(form, frozenset()) for form in bound)
        if licensed and surface in _NOUN_CLASSES and _render_nominal_constituents(pairs) == surface and not any(member in heads or member in skipped for member in members):
            if ordinary:
                yield from _morpheme_units(tokens, ordinary, heads, skipped)
                ordinary = []
            yield _Unit(surface, "NNG", tokens[index].start, tokens[members[-1]].end, index, noun_classes=_NOUN_CLASSES[surface])
            position = stop
        else:
            if members:
                ordinary.extend(members)
                position = stop
            else:
                ordinary.append(index)
                position += 1
    if ordinary:
        yield from _morpheme_units(tokens, ordinary, heads, skipped)


# 추가 명세도 명사 분류와 실제 역할로만 표현한다.
_NOUN_CLASSES = MappingProxyType(dict(_NOUN_CLASSES) | {
    "등급": frozenset({"grade_head"}), "기준액": frozenset({"price_benchmark"}),
    "응답자": frozenset({"human", "counted_human"}),
    "집단": frozenset({"group_head"}), "무리": frozenset({"group_head"}),
    "실체": frozenset({"entity_head"}),
    "식구": frozenset({"family_member_head", "human"}),
    "가족": frozenset({"family_member_head", "human"}),
    "위": frozenset({"above_position_head"}),
    "수량": frozenset({"count_quantity"}),
    "개숫물": frozenset({"washing_water"}),
    "첨족": frozenset({"equinus"}),
    "갑옷": frozenset({"armour"}),
    "소매": frozenset({"sleeve_part"}),
    "갑옷소매": frozenset({"armour_sleeve"}),
    "재치": frozenset({"human_ability"}),
    "언변": frozenset({"human_ability", "speech_skill"}),
    "말솜씨": frozenset({"human_ability", "speech_skill"}),
    "화술": frozenset({"human_ability", "speech_skill"}),
    "설득력": frozenset({"human_ability", "speech_skill"}),
    "달변": frozenset({"human_ability", "speech_skill"}),
    "유머감각": frozenset({"human_ability"}),
    "기량": frozenset({"human_ability"}),
    "재주": frozenset({"human_ability", "ability_head"}),
    "힘": frozenset({"ability_head"}),
    "능력": frozenset({"ability_head"}),
    "언어": frozenset({"speech_medium"}),
    "대화": frozenset({"speech_medium"}),
    "남": frozenset({"human"}),
    "말": frozenset({"designation_head", "speech_medium"}),
})
_COMPOSITION_PACKAGES += (("grade_head", frozenset({"price"})),)


def _family_member_nominal(sources, head, relation):
    """가족 구성원 핵어와 실제 귀속 명사를 함께 보관한다."""
    if len(sources) != 1 or "family_member_head" not in head.noun_classes:
        return None
    source = sources[0]
    if source.noun_classes & {"unresolved_modifier", "unresolved_relation"}:
        return None
    if "family_home" in source.noun_classes or "spouse_family" in _possible_classes(source):
        result = _Mention(head.token_index, head.form, head.start, head.end, head.noun_classes | {"family_affiliation"}, False, sources, head.facts, head.bound_arguments)
        return _derive(result, "family_affiliation", relation, source.start, source.end)
    return None


def _original_family_affiliation_relations(evidence, head):
    """기존 명사 구조의 넓은 소속만 원래 출처로 반환한다."""
    if "family_affiliation" not in head.noun_classes or not head.owners:
        return
    if head.noun_classes & {"unresolved_modifier", "unresolved_relation"}:
        return
    for owner in head.owners:
        if owner.noun_classes & {"unresolved_modifier", "unresolved_relation"}:
            continue
        _emit_domain_restriction(evidence, owner, {"family_affiliation"}, None,
                                 "original_family_affiliation", (head,), source_kind="nominal")


def _composed_direct_nominal(evidence, modifiers, head):
    """직접 명사구의 가족ㆍ부분ㆍ위치ㆍ모집단ㆍ유형 역할을 순서대로 합성한다."""
    currency = _currency_nominal_composition(modifiers, head)
    if currency is not None:
        return currency
    family = _family_member_nominal(modifiers, head, "direct_family_affiliation")
    if family is not None:
        _original_family_affiliation_relations(evidence, family)
        return family
    if len(modifiers) == 1:
        modifier = modifiers[0]
        clean = not modifier.noun_classes & {"unresolved_modifier", "unresolved_relation"}
        # 계수 해석은 뒤의 기준ㆍ분류 관계가 함께 있을 때만 발생한다.
        if (clean and "count_head" in _NOUN_CLASSES.get(head.form, frozenset())
                and not head.owned and not head.owners):
            head = _Mention(head.token_index, head.form, head.start, head.end,
                            head.noun_classes, True, (modifier,), head.facts, head.bound_arguments)
        if clean and "part_head" in modifier.noun_classes and "group_head" in head.noun_classes:
            return _derive(head, "part_group", "part_group_head", modifier.start, modifier.end)
        if clean and "decimal_below_position" in modifier.noun_classes and "location_head" in head.noun_classes:
            return _inherit_nominal(head, modifiers, {"decimal_below_position": "decimal_below_position"}, "decimal_position_place_scaffold")
        if clean and "population_selector" in head.noun_classes and "natural_number" in modifier.noun_classes and not modifier.owned:
            return _inherit_nominal(head, modifiers, {"natural_number": "natural_number"}, "nominal_number_domain_selection")
        if clean and head.noun_classes & {"function_head", "procedure_head"} and "judicial_function" in _possible_classes(modifier):
            return _Mention(head.token_index, head.form, head.start, head.end, head.noun_classes | {"typed_head_reference"}, False, modifiers, head.facts, head.bound_arguments)

    if len(modifiers) == 1 and "population_selector" in head.noun_classes:
        modifier = modifiers[0]
        if modifier.noun_classes & {"counted_human", "counted_opinion"} and not modifier.owned and not modifier.noun_classes & {"unresolved_modifier", "unresolved_relation"}:
            return _inherit_nominal(head, modifiers, {"counted_human": "counted_human", "counted_opinion": "counted_opinion"}, "nominal_population_selection")

    if len(modifiers) == 1:
        modifier = modifiers[0]
        if "below_position_head" in head.noun_classes and modifier.form == "소수점" and not modifier.owned:
            return _inherit_nominal(head, modifiers, {"decimal_part": "decimal_below_position"}, "decimal_position_owner")
        if "constitutive_basis_head" in head.noun_classes and "physical_thing" in modifier.noun_classes:
            return _inherit_nominal(head, modifiers, {"physical_thing": "substance"}, "physical_constitutive_basis")
        if "road_structure_head" in modifier.noun_classes and "structure_head" in head.noun_classes:
            return _inherit_nominal(head, modifiers, {"road_structure_head": "road_structure_head", "elevated_structure": "elevated_structure"}, "road_structure_composition")

    head = _direct_nominal_relations(evidence, modifiers, head)
    packaged = _package_nominal(modifiers, head, "direct_category")
    if packaged is not None:
        head = packaged
    if len(modifiers) != 1:
        return head
    modifier = modifiers[0]
    if head.noun_classes & {"count_head", "number_head"} and modifier.noun_classes & {"divisor", "natural_divisor"}:
        head = _Mention(head.token_index, head.form, head.start, head.end,
                        head.noun_classes, True, (modifier,), head.facts, head.bound_arguments)
    if "exact_count_two" in modifier.noun_classes and head.noun_classes & {"divisor", "natural_divisor"}:
        head = _derive(head, "exactly_two_divisors", "direct_divisor_count", modifier.start, modifier.end)
    if "exact_count_two" in head.noun_classes and modifier.noun_classes & {"divisor", "natural_divisor"}:
        head = _derive(head, "exactly_two_divisors", "direct_divisor_count", modifier.start, modifier.end)
        for value in modifier.noun_classes & {"divisor", "natural_divisor"}:
            head = _derive(head, value, "counted_nominal_head", modifier.start, modifier.end)
        if modifier.owned:
            head = _Mention(head.token_index, head.form, head.start, head.end, head.noun_classes, True, modifier.owners, head.facts)
    if "literary_domain" in modifier.noun_classes and "creative_work" in head.noun_classes:
        head = _inherit_nominal(head, (modifier,), {"literary_domain": "literary_work"}, "literary_work_composition")
    if "private_party" in modifier.noun_classes and "between_head" in head.noun_classes:
        head = _derive(head, "private_party_domain", "private_party_between", modifier.start, modifier.end)
    head, _ = _genitive_derived_type((modifier,), head)
    if "reflexive_modifier" in modifier.noun_classes and "self_reference" in head.noun_classes:
        head = _derive(head, "self_reference", "reflexive_nominal", modifier.start, modifier.end)
    if "judicial_act" in modifier.noun_classes and "function_head" in head.noun_classes:
        head = _derive(head, "judicial_function", "judicial_action_nominal", modifier.start, modifier.end)
    if "price" in modifier.noun_classes and "price_range" in head.noun_classes:
        for level in ("middle_price", "low_price"):
            if level in modifier.noun_classes:
                head = _derive(head, level, "scalar_price_nominal", modifier.start, modifier.end)
    return head


def _genitive_derived_type(owners, head):
    """역할이 확인된 속격만 유형을 운반하며 일반 소유는 보존한다."""
    if (len(owners) == 1 and "currency" in owners[0].noun_classes
            and not owners[0].noun_classes & {"unresolved_modifier", "unresolved_relation", "quoted_nominal"}
            and "currency_standard_basis_ratio" in head.noun_classes):
        return _derive(head, "currency_value_basis_ratio", "owned_currency_basis_ratio_nominal", owners[0].start, owners[0].end), False
    family = _family_member_nominal(owners, head, "genitive_family_affiliation")
    if family is not None:
        return family, False
    if len(owners) == 1 and "decimal_below_position" in owners[0].noun_classes and "location_head" in head.noun_classes and not owners[0].noun_classes & {"unresolved_modifier", "unresolved_relation"}:
        return _inherit_nominal(head, owners, {"decimal_below_position": "decimal_below_position"}, "genitive_decimal_place_scaffold"), True

    if len(owners) == 1:
        owner = owners[0]
        clean = not owner.noun_classes & {"unresolved_modifier", "unresolved_relation"}
        if clean and "part_head" in head.noun_classes and owner.noun_classes & {"counted_human", "counted_opinion"}:
            return _Mention(head.token_index, head.form, head.start, head.end, head.noun_classes | {"population_part"}, True, owners, head.facts, head.bound_arguments), False
        if clean and "below_position_head" in head.noun_classes and "decimal_part" in owner.noun_classes and owner.form == "소수점" and not owner.owned:
            result = _inherit_nominal(head, owners, {"decimal_part": "decimal_below_position"}, "decimal_position_owner")
            return result, True
        if clean and "constitutive_basis_head" in head.noun_classes and "physical_thing" in owner.noun_classes:
            result = _inherit_nominal(head, owners, {"physical_thing": "substance"}, "physical_constitutive_basis")
            return result, True

    packaged = _package_nominal(owners, head, "genitive_category")
    if packaged is not None:
        return packaged, bool(packaged.noun_classes & {"category_package", "unresolved_relation"})
    if len(owners) != 1:
        return head, False
    owner = owners[0]
    derived = False
    if "exact_count_two" in owner.noun_classes and head.noun_classes & {"divisor", "natural_divisor"}:
        head = _derive(head, "exactly_two_divisors", "genitive_divisor_count", owner.start, owner.end)
        derived = True
    for owner_class, head_class, semantic_class in _GENITIVE_TYPE_CONSTRUCTIONS:
        if owner_class in owner.noun_classes and head_class in head.noun_classes:
            head = _derive(head, semantic_class, "genitive_type_modifier", owner.start, owner.end)
            derived = True
            for fact_class, relation, start, end in owner.facts:
                if fact_class == "unresolved_modifier":
                    head = _derive(head, fact_class, relation, start, end)
    return head, derived


def _emit_group_type(evidence, target, sources, effects, relation, event=None, allowed=None):
    """기능 핵어의 대상 참조는 실제 명시 정의의 호환 기능 유형만 전달한다."""
    if event is not None and event.long_negative is not None:
        domains = _group_effects(sources, effects)
        if allowed is not None:
            domains &= frozenset(allowed)
        return _emit_domain_restriction(evidence, target, domains, event, relation, sources) if domains else False
    if "typed_head_reference" in target.noun_classes:
        shared = _group_effects(sources, effects) & {"judicial_function"}
        if allowed is not None:
            shared &= frozenset(allowed)
        if not shared:
            return False
        success = False
        for owner in target.owners:
            success = _emit_coherent_group_type(evidence, owner, sources, effects, relation, event, shared) or success
            for value in shared:
                _emit(evidence, owner, "explicit_typed_function_head", target.start, target.end, value)
        return success
    return _emit_coherent_group_type(evidence, target, sources, effects, relation, event, allowed)


def _nominal_population_adjunct(current, arguments):
    """가운데의 모집단을 뒤 명사의 수식어와 분리된 실제 국소 논항으로 닫는다."""
    if len(current) == 1 and "population_selector" in current[0].noun_classes:
        selector = current[0]
        arguments.append(_Argument("population", (selector,), selector.form, selector.start, selector.end))
        return []
    return current


def _partition_relative_arguments(units, position, predicate, tag, arguments):
    """실제 내부 논항과 바깥 화제ㆍ수 영역을 순서대로 분할한다."""
    outer = []
    inner = list(arguments)
    future = _future_outer_clause(units, position)
    # 같은 격의 두 독립 명사구 중 바로 앞 명사구가 내부 논항 후보다.
    for role in {argument.role for argument in arguments}:
        values = [argument for argument in inner if argument.role == role]
        if len(values) > 1:
            for argument in values[:-1]:
                inner.remove(argument)
                outer.append(argument)
    nominal = tag in {"VCP", "VCN"}
    neutral = predicate in (_NEUTRAL_PREDICATES | {"다르"}) and tag in {"VA", "VV", "VX"}
    if nominal or neutral:
        permitted = {"subject", "topic", "nominal_complement", "complement"}
        if predicate in {"있", "존재하"}:
            permitted.add("quantity_complement")
        if neutral:
            permitted.update({"comparison", "location", "source", "via"})
        for argument in tuple(inner):
            if argument.role not in permitted and (not neutral or _outer_predicate_accepts(units, position, argument.role)):
                inner.remove(argument)
                outer.append(argument)
    has_subject = any(argument.role == "subject" for argument in inner)
    has_object = any(argument.role == "object" for argument in inner)
    classification_gap = predicate in _CLASSIFICATION_PREDICATES and any(argument.role == "via" and argument.particle_form in {"로", "으로"} for argument in inner)
    # 선언된 소속 관계의 구성원 역할이 있고 범주 역할이 비어 있을 때만 복원한다.
    membership_gap = tag in {"VV", "XSV"} and any(
        predicate in construction.predicates
        and any(argument.role == construction.member_role for argument in inner)
        and not any(argument.role == construction.target_role for argument in inner)
        for construction in _MEMBERSHIP_CONSTRUCTIONS
    )
    subject_gap = predicate in {"적", "있", "존재하", "눕", "자", "높"} or (predicate in _DEFINITION_PREDICATES | {"규율하", "담당하", "관장하", "수행하", "맡"} and has_object) or classification_gap or membership_gap
    for argument in tuple(inner):
        if argument.role == "topic" and (has_subject or (future and (nominal or neutral or subject_gap))):
            inner.remove(argument)
            outer.append(argument)
    # 후행 능력 핵어와 계사가 있으면 같은 유형의 바깥 주격은 내부 행위자가 아니다.
    cursor = position + 1
    while cursor < len(units) and units[cursor].tag in {"EP", "ETM"}:
        cursor += 1
    relative_head = units[cursor] if cursor < len(units) else None
    judgment_objects = [argument for argument in inner if argument.role == "object"]
    judgment_gap = ((predicate == "판단하" and tag in {"VV", "XSV"}
                     or predicate == "헤아리" and tag == "VV") and relative_head is not None
                    and "assessment_head" in relative_head.noun_classes
                    and len(judgment_objects) == 1 and judgment_objects[0].members
                    and all(member.noun_classes & {"value_modifier", "appraised_level"}
                            and not member.noun_classes & {"unresolved_modifier", "unresolved_relation"}
                            for member in judgment_objects[0].members))
    if future and judgment_gap:
        for argument in tuple(inner):
            if argument.role == "topic":
                inner.remove(argument)
                outer.append(argument)
    if relative_head is not None:
        local = _Event(predicate, -1, -1, tuple(argument for argument in inner if argument.role not in {"topic", "focus", "object"}), tag)
        basis_gap = ("currency_ratio_head" in relative_head.noun_classes and _currency_basis_argument(local) is not None)
        operation_gap = (relative_head.tag == "NNB" and relative_head.form == "것"
                         and _currency_display_arguments(_Event(predicate, -1, -1,
                             tuple(argument for argument in inner if argument.role not in {"topic", "focus"}), tag)) is not None)
        if basis_gap or operation_gap:
            for argument in tuple(inner):
                if (argument.role in {"topic", "focus"}
                        or basis_gap and argument.role == "object" and len(argument.members) == 1
                        and _owned_currency_value(argument.members[0])):
                    inner.remove(argument)
                    outer.append(argument)
    side_gap = (predicate in {"싸", "비싸"} and tag == "VA" and relative_head is not None
                and relative_head.form == "쪽" and relative_head.tag == "NNB"
                and all(argument.role == "topic" for argument in inner))
    location = next((argument for argument in inner if argument.role == "location"), None)
    state = units[position].long_negative
    complete_price = (relative_head is not None and ("ordinary_price" in relative_head.noun_classes
                      or "ordinary_price_modifier" in relative_head.noun_classes and cursor + 1 < len(units)
                      and "price" in units[cursor + 1].noun_classes))
    bias_gap = (predicate == "치우치" and tag == "VV" and state is not None
                and state.relative_kind == "direct" and state.licensed and not state.unresolved_dependencies
                and complete_price and location is not None and location.particle_form == "에"
                and len(location.members) == 1 and "price_side" in location.members[0].noun_classes
                and all(argument.role in {"topic", "location"} for argument in inner))
    if side_gap or bias_gap:
        for argument in tuple(inner):
            if argument.role == "topic":
                inner.remove(argument)
                outer.append(argument)
    subjects = tuple(argument for argument in inner if argument.role == "subject")
    without_subject = tuple(argument for argument in inner if argument.role not in {"subject", "topic", "focus"})
    if future and relative_head is not None and "ability_head" in relative_head.noun_classes and len(subjects) == 1 and _speech_ability_arguments(_Event(predicate, -1, -1, without_subject, tag)):
        subject = subjects[0]
        if subject.members and all("speech_ability" in _possible_classes(member) and not member.noun_classes & {"human", "counted_human"} for member in subject.members):
            inner.remove(subject)
            outer.append(subject)
    # 완전한 언어 설득 논항이 내부 절을 이루면 후행 계사의 바깥 화제를 복원한다.
    local = tuple(argument for argument in inner if argument.role not in {"topic", "focus"})
    if future and _speech_ability_arguments(_Event(predicate, -1, -1, local, tag)):
        for argument in tuple(inner):
            if argument.role in {"topic", "focus"}:
                inner.remove(argument)
                outer.append(argument)
    inner, outer = tuple(inner), tuple(argument for argument in arguments if argument in outer)

    if predicate == "이" and tag == "VCP" and any(argument.role == "subject" and all("natural_divisor" in member.noun_classes for member in argument.members) for argument in inner):
        domains = tuple(argument for argument in outer if argument.role == "population" and all("natural_number" in member.noun_classes for member in argument.members))
        inner += domains
        outer = tuple(argument for argument in outer if argument not in domains)
    gap_predicates = {"넘", "이루", "맡", "적용하", "잠들", "날아다니", "날", "지나가"}
    if predicate in gap_predicates and _future_outer_clause(units, position):
        topics = tuple(argument for argument in inner if argument.role == "topic")
        inner = tuple(argument for argument in inner if argument not in topics)
        outer += topics
    return inner, outer




def _connector_between(units, position, previous):
    """직전 실제 서술어 뒤의 연결 어미 하나만 확인한다."""
    for cursor in range(position - 1, -1, -1):
        unit = units[cursor]
        if unit.start == previous.start and unit.end == previous.end and unit.form == previous.predicate:
            following = cursor + 1
            while following < position and units[following].tag == "EP":
                following += 1
            return units[following].form if following < position and units[following].tag == "EC" else ""
    return ""


def _connected_relative_arguments(units, position, predicate, tag, arguments, history, adnominal):
    """허용된 국소 연결 구성에서만 같은 주체와 장소 및 바깥 화제를 보존한다."""
    if not adnominal or not history or arguments:
        return arguments, ()
    previous = history[-1]
    if previous.negated:
        return arguments, ()
    connector = _connector_between(units, position, previous)
    topics = tuple(argument for argument in previous.arguments if argument.role == "topic")
    inner = tuple(argument for argument in previous.arguments if argument.role != "topic")
    if previous.predicate == "눕" and previous.tag == "VV" and predicate == "잠들" and tag == "VV" and connector in {"아", "어", "고"}:
        prior = _Argument("prior_reclining", (_Mention(-1, previous.predicate, previous.start, previous.end, frozenset({"reclining_event"})),))
        if all(argument.role in {"subject", "location"} for argument in inner):
            return inner + (prior,), topics
    if previous.predicate == "높" and previous.tag == "VA" and predicate in {"지나가", "지나", "통과하"} and tag in {"VV", "XSV"} and connector == "게" and all(argument.role in {"via", "location"} for argument in inner):
        return inner, topics
    return arguments, ()


def _compatible_copular_head(head, value):
    """동일시도 실제 핵어가 수용할 수 있는 유형에서만 통과시킨다."""
    return _membership_head_compatible(head, value) or any(head_class in head.noun_classes and value in permitted for head_class, permitted in _COMPOSITION_PACKAGES) or ("entity_head" in head.noun_classes and value == "substance") or ("group_head" in head.noun_classes and value == "minority_quantity")


def _speech_ability_arguments(event):
    """언어 수단과 사람 목적어가 실제 설득 사건에 결합했는지 확인한다."""
    if (event.negated and event.long_negative is None) or event.predicate not in {"설득하", "납득시키", "타이르"} or event.tag not in {"VV", "XSV"}:
        return ()
    if any(argument.role not in {"via", "object", "subject"} for argument in event.arguments):
        return ()
    medium = _unique_argument(event, "via")
    objects = _unique_argument(event, "object")
    if medium is None or not medium.members or medium.particle_form not in {"로", "으로"} or not _valid_members(objects, {"human"}):
        return ()
    if event.long_negative is None:
        if not _valid_members(medium, {"speech_medium"}):
            return ()
    elif any(member.owned or member.noun_classes & {"unresolved_modifier", "unresolved_relation"}
             or (member.noun_classes and "speech_medium" not in member.noun_classes) for member in medium.members):
        return ()
    subject = _unique_argument(event, "subject")
    if any(argument.role == "subject" for argument in event.arguments) and not _valid_members(subject, {"human"}):
        return ()
    members = medium.members + objects.members + (subject.members if subject is not None else ())
    if any(member.owned for member in members):
        return ()
    return members


def _derive_typed_relative_head(evidence, event, head):
    """실제 소유ㆍ논항ㆍ호환 핵어의 관형절 유형을 합성한다."""
    if event.negated:
        return _predicate_relative_type(evidence, event, head)
    speech_arguments = _speech_ability_arguments(event)
    if "ability_head" in head.noun_classes and speech_arguments:
        return _derive_relation(evidence, head, "speech_ability", "verbal_persuasion_ability_head", event, speech_arguments)
    subject = _unique_argument(event, "subject")
    objects = _unique_argument(event, "object")
    population = _unique_argument(event, "population")
    if event.predicate == "재판하" and event.tag in {"VV", "XSV"} and "procedure_head" in head.noun_classes and _valid_members(subject, {"judicial_institution"}) and _valid_members(objects, {"judicial_patient"}) and all(argument.role in {"subject", "object"} for argument in event.arguments):
        return _derive_relation(evidence, head, "judicial_function", "court_patient_adjudication_procedure", event, subject.members + objects.members)
    if event.predicate in {"맡", "담당하", "관장하", "수행하"} and event.tag in {"VV", "XSV"} and "function_head" in head.noun_classes and _valid_members(subject, {"judicial_institution"}) and _valid_members(objects, {"judicial_act"}):
        return _derive_relation(evidence, head, "judicial_function", "institution_trial_function_head", event, subject.members + objects.members)
    if event.predicate == "적용하" and event.tag in {"VV", "XSV"} and "function_head" in head.noun_classes:
        instrument = _unique_argument(event, "via")
        if _valid_members(subject, {"judicial_institution"}) and _valid_members(instrument, {"judicial_act"}) and _valid_members(objects, {"legal_type_head"}) and all(argument.role in {"subject", "via", "object"} for argument in event.arguments):
            return _derive_relation(evidence, head, "judicial_function", "institution_trial_law_application", event, subject.members + instrument.members + objects.members)
    if event.predicate == "적" and event.tag == "VA" and "part_group" in head.noun_classes and _valid_members(subject, {"counted_human"}) and all(member.form == "인원" for member in subject.members) and _valid_members(population, {"counted_human"}) and all(argument.role in {"subject", "population"} for argument in event.arguments):
        return _derive_relation(evidence, head, "minority_quantity", "subset_owned_low_member_count", event, subject.members + population.members)
    if "number_head" in head.noun_classes and _valid_members(population, {"natural_number"}):
        without_domain = _Event(event.predicate, event.start, event.end, tuple(argument for argument in event.arguments if argument.role != "population"), event.tag, event.negated, event.adjuncts)
        natural_head = _derive_relation(evidence, head, "natural_number", "explicit_natural_number_domain", event, population.members)
        numeric = _numeric_relative(without_domain, natural_head)
        if numeric:
            result = _derive_relation(evidence, natural_head, "prime_number", "natural_domain_exact_positive_divisors", event, numeric + population.members)
            return result
    if event.predicate == "이루" and event.tag == "VV" and "constitutive_basis_head" in head.noun_classes and not any(argument.role in {"subject", "topic"} for argument in event.arguments) and _valid_members(objects, {"physical_thing"}):
        return _derive_relation(evidence, head, "substance", "physical_entity_constitutive_basis", event, objects.members)
    if event.predicate == "잠들" and event.tag == "VV" and "location_head" in head.noun_classes:
        night = _unique_argument(event, "location")
        prior = _unique_argument(event, "prior_reclining")
        if _valid_members(subject, {"human", "counted_human"}) and _valid_members(night, {"night_time"}) and prior is not None and all(argument.role in {"subject", "location", "prior_reclining"} for argument in event.arguments):
            return _derive_relation(evidence, head, "sleeping_place", "connected_human_night_sleep_place", event, subject.members + night.members + prior.members)
    if event.predicate in {"날아다니", "날", "날아가"} and event.tag == "VV" and (head.noun_classes & {"animal", "insect"} or "animal" in _possible_classes(head)) and not any(argument.role in {"subject", "topic"} for argument in event.arguments):
        wings = _unique_argument(event, "via")
        if _valid_members(wings, {"biological_part"}) and all(argument.role == "via" for argument in event.arguments):
            return _derive_relation(evidence, head, "animal", "compatible_wing_flight_head", event, wings.members)
    if event.tag == "VCP" and event.predicate == "이" and not any(argument.role in {"subject", "topic"} for argument in event.arguments):
        complement = _unique_argument(event, "nominal_complement")
        if complement is not None:
            shared = _group_effects(complement.members, _TYPE_EFFECTS)
            if shared and any(not _compatible_copular_head(head, value) for value in shared):
                return _derive(head, "unresolved_relation", "incompatible_copular_relative_head", event.start, event.end)

    if event.negated:
        return _predicate_relative_type(evidence, event, head)
    subject = _unique_argument(event, "subject")
    missing_subject = not any(argument.role in {"subject", "topic"} for argument in event.arguments)
    if event.predicate == "적" and event.tag == "VA" and missing_subject and "part_head" in head.noun_classes:
        population = _unique_argument(event, "population")
        anchors = ()
        if _valid_members(population, {"counted_human", "counted_opinion"}) and all(argument.role == "population" for argument in event.arguments):
            anchors = population.members
        elif not event.arguments and "population_part" in head.noun_classes and len(head.owners) == 1:
            owner = head.owners[0]
            if owner.noun_classes & {"counted_human", "counted_opinion"} and not owner.owned:
                anchors = (owner,)
        if anchors:
            return _derive_relation(evidence, head, "minority_quantity", "locally_quantified_population_part", event, anchors)
    if event.predicate in {"있", "존재하"} and event.tag in {"VV", "VA", "VX", "XSV"} and "number_head" in head.noun_classes:
        location = _unique_argument(event, "location")
        if _valid_members(subject, {"digit_head"}) and _valid_members(location, {"decimal_below_position"}) and location.particle_form == "에" and all(argument.role in {"subject", "location"} for argument in event.arguments) and not any(value in _APPROXIMATE_COUNTS for value in event.adjuncts):
            return _derive_relation(evidence, head, "decimal_number", "owned_decimal_position_digits", event, subject.members + location.members)
    if event.predicate == "높" and event.tag == "VA" and "road_structure_head" in head.noun_classes and missing_subject:
        comparison = _unique_argument(event, "comparison")
        if _valid_members(comparison, {"ground_reference"}) and comparison.particle_form == "보다" and all(argument.role == "comparison" for argument in event.arguments):
            return _derive_relation(evidence, head, "elevated_structure", "ground_height_road_structure", event, comparison.members)
    if event.predicate in {"자", "눕", "쉬"} and event.tag == "VV" and "location_head" in head.noun_classes:
        time = _unique_argument(event, "location")
        if _valid_members(subject, {"human", "counted_human"}) and _valid_members(time, {"night_time"}) and time.particle_form == "에" and all(argument.role in {"subject", "location"} for argument in event.arguments):
            return _derive_relation(evidence, head, "sleeping_place", "night_human_reclining_place", event, subject.members + time.members)
    if event.predicate in {"담당하", "관장하", "수행하", "맡"} and event.tag in {"VV", "XSV"} and "function_head" in head.noun_classes and missing_subject:
        objects = _unique_argument(event, "object")
        if _valid_members(objects, {"judicial_act"}):
            return _derive_relation(evidence, head, "judicial_function", "compatible_judicial_state_function", event, objects.members)
    if event.predicate == "규율하" and event.tag in {"VV", "XSV"} and missing_subject and ("private_law" in _possible_classes(head) or head.noun_classes & {"legal_type_head", "membership_head"}):
        objects = _unique_argument(event, "object")
        comparison = _unique_argument(event, "comparison")
        if _valid_members(objects, {"private_relation"}) and (comparison is None or _valid_members(comparison, {"private_law_branch", "private_law"})):
            anchors = objects.members + (comparison.members if comparison is not None else ())
            return _derive_relation(evidence, head, "private_law", "regulated_private_relation_head", event, anchors)
    return _predicate_relative_type(evidence, event, head)


def _family_participant_relations(evidence, event):
    """실제 모임 주어의 가족 구성원 귀속을 각 표적 출현에 연결한다."""
    if (event.negated and event.long_negative is None) or event.predicate not in {"모이", "모여들", "만나"} or event.tag != "VV":
        return
    subject = _role_or_topic(event, "subject", True)
    if subject is None or len(subject.members) < 2 or any("family_member_head" not in member.noun_classes or "family_affiliation" not in member.noun_classes or len(member.owners) != 1 or member.noun_classes & {"unresolved_modifier", "unresolved_relation"} for member in subject.members):
        return
    if not any("family_home" in member.owners[0].noun_classes for member in subject.members):
        return
    for member in subject.members:
        target = member.owners[0]
        if "spouse_family" in _possible_classes(target):
            if event.long_negative is not None:
                # 실제 공동 명사와 독립 귀속 지지가 함께 필요한 출처다.
                sources = subject.members + tuple(item.owners[0] for item in subject.members)
                _emit_domain_restriction(evidence, target, {"spouse_family"}, event, "family_affiliation_domain", sources, source_kind="nominal")
                continue
            _emit(evidence, target, "coordinated_family_participant", event.start, event.end, "spouse_family")
            _emit(evidence, target, "actual_family_member_head", member.start, member.end, "spouse_family")
            for sibling in subject.members:
                _emit(evidence, target, "coordinated_family_affiliation", sibling.owners[0].start, sibling.owners[0].end, "spouse_family")


def _contrast_composition_relations(text, tokens, hard_boundaries, heads, skipped, evidence):
    """아니라 직후 쉼표만 같은 명시 대조 정의의 국소 연결로 처리한다."""
    softened = []
    for position, char in enumerate(text):
        if char not in {",", "，"} or position in hard_boundaries:
            continue
        left = max((index + 1 for index, value in enumerate(text[:position]) if value in ".!?\r\n,，"), default=0)
        indices = tuple(index for index, token in enumerate(tokens) if left <= token.start and token.end <= position and token.form not in _QUOTE_PAIRS and token.form not in _QUOTE_PAIRS.values())
        units = tuple(_compose_declared_derivations(_units(tokens, indices, heads, skipped)))
        if len(units) >= 2 and units[-2].tag == "VCN" and units[-2].form == "아니" and units[-1].tag == "EC" and units[-1].form in _NOMINAL_CONTRAST_CONNECTORS:
            softened.append(position)
    if not softened:
        return
    characters = list(text)
    for position in softened:
        characters[position] = " "
    local_text = "".join(characters)
    scopes, _ = _scope_index(local_text, tokens, hard_boundaries)
    candidate = {index: [] for index in evidence}
    for indices in scopes.values():
        retained = tuple(index for index in indices if tokens[index].start not in softened)
        _scan_scope(tokens, retained, candidate, heads, skipped)
    atoms = _quote_atoms(text, tokens, hard_boundaries, heads, skipped)
    for units in _quotation_units(local_text, tokens, hard_boundaries, heads, skipped, atoms):
        retained = tuple(unit for unit in units if unit.start not in softened)
        _scan_scope(tokens, (), candidate, heads, skipped, supplied_units=retained, quote_mode=True)
    for atom in atoms:
        index = atom.unit.token_index
        if index not in candidate or not any(item.relation.startswith(_QUOTE_RELATIONS) for item in candidate[index]):
            continue
        for value in {item.semantic_class for item in candidate[index] if not _is_domain_effect(item)} & _possible_classes(_Mention(index, atom.unit.form, atom.unit.start, atom.unit.end)):
            boundary = SenseEvidence("quoted_nominal_boundary", atom.unit.start, atom.unit.end, atom.opening, atom.closing + 1, value)
            if boundary not in candidate[index]:
                candidate[index].append(boundary)
            for opening, closing in _balanced_quote_ranges(text, hard_boundaries):
                if opening < atom.opening and atom.closing < closing:
                    container = SenseEvidence("quoted_containment_boundary", atom.unit.start, atom.unit.end, opening, closing + 1, value)
                    if container not in candidate[index]:
                        candidate[index].append(container)
    for index, items in candidate.items():
        for item in items:
            if item not in evidence[index]:
                evidence[index].append(item)


_QUOTE_RELATIONS += ("copular_relative",)


def _neutral_relative(event, head, nonassertive=False):
    """메타언어 차이와 선언된 중립 관형 관계를 구별한다."""
    if not event.negated and event.predicate == "다르" and event.tag == "VA" and "서로" in event.adjuncts and "designation_head" in head.noun_classes and not event.arguments:
        return "metalinguistic_difference"

    if event.negated and not nonassertive:
        return ""
    if _neutral_opinion_relative(event, nonassertive=nonassertive):
        return "opinion_relation"
    for frame in _NEUTRAL_FRAMES + _INHERENT_HEAD_NEUTRAL_FRAMES:
        if event.predicate not in frame.predicates or event.tag not in frame.tags:
            continue
        if frame.head_classes and not _has_inherent_type(head, frame.head_classes):
            continue
        if any(argument.role not in frame.allowed_roles for argument in event.arguments):
            continue
        subject = _unique_argument(event, "subject")
        if frame.property_subject_classes:
            if subject is None or not subject.members or any(not (member.noun_classes & frame.property_subject_classes) or member.noun_classes & {"unresolved_modifier", "unresolved_relation"} for member in subject.members):
                continue
        elif any(argument.role in {"subject", "topic"} for argument in event.arguments):
            continue
        if any(member.noun_classes & {"unresolved_modifier", "unresolved_relation"} for argument in event.arguments for member in argument.members):
            continue
        return frame.relation
    return ""




def _typed_relative_relations(evidence, event, head):
    """인용 명사에 붙은 실제 지정 핵어의 긍정 정의만 병렬 지칭어로 표시한다."""
    side = _price_side_modifier(event, head)
    if side is not None:
        return side
    currency = _currency_ratio_relative(evidence, event, head)
    if currency is not None:
        return currency
    judgment = _judgment_attribute_relative(evidence, event, head)
    if judgment is not None:
        return judgment
    result = _derive_typed_relative_head(evidence, event, head)
    if result is not None and not event.negated and event.tag == "VCP" and event.predicate == "이" and "quoted_nominal" in head.noun_classes and not any(argument.role in {"subject", "topic"} for argument in event.arguments):
        source = _unique_argument(event, "nominal_complement")
        if source is not None and source.members and all("designation_head" in member.noun_classes for member in source.members):
            result = _derive(result, "defined_designation_coordinand", "explicit_designation_copular_definition", event.start, event.end)
    return result


def _independent_coordinate_arguments(units, position, predicate, arguments, adnominal):
    """실제 지정어 정의ㆍ병렬ㆍ후행 인용 화제가 함께 있을 때만 바깥 항을 복원한다."""
    if not adnominal or predicate not in _DEFINITION_PREDICATES:
        return arguments, ()
    cursor = position + 1
    while cursor < len(units) and units[cursor].tag in {"EP", "ETM"}:
        cursor += 1
    if cursor + 1 >= len(units) or "quoted_nominal" not in units[cursor].noun_classes:
        return arguments, ()
    particle = units[cursor + 1]
    if not (particle.tag == "JKS" or (particle.tag == "JX" and particle.form in _TOPIC_PARTICLES)):
        return arguments, ()
    revised = []
    deferred = []
    for argument in arguments:
        members = list(argument.members)
        while len(members) > 1 and {"quoted_nominal", "defined_designation_coordinand"} <= members[0].noun_classes:
            deferred.append(members.pop(0))
        revised.append(_Argument(argument.role, tuple(members), argument.particle_form, argument.particle_start, argument.particle_end))
    return tuple(revised), tuple(deferred)


# 절차는 행위의 핵어이고 피고는 재판의 실제 대상이다. 단독 근거로 뜻을 정하지 않는다.
_NOUN_CLASSES = MappingProxyType(dict(_NOUN_CLASSES) | {
    "절차": frozenset({"procedure_head"}),
    "과정": frozenset({"procedure_head"}),
    "피고": frozenset({"judicial_patient", "human"}),
    "피고인": frozenset({"judicial_patient", "human"}),
    "인물": frozenset({"human"}),
    "인명": frozenset({"person_name_type"}),
    "고유명": frozenset({"proper_name_type"}),
    "지명": frozenset({"place_name_type"}),
    "이름": _NOUN_CLASSES["이름"] | {"name_slot"},
})



def _clear_negative_entity(source, tokens):
    """명시 개체의 비동일성을 유형 부정과 구별한다."""
    return (not source.noun_classes & {"unresolved_modifier", "unresolved_relation"}
            and (source.owned or source.owners or _explicit_referring_term(source)
                 or any(token.start == source.start and token.end == source.end
                        and _tag(token.tag) == "NNP" and _token_roles_consistent(token)
                        for token in tokens)))


def _relative_negative_type(evidence, event, head):
    """실제 VCNㆍETM 소비 지점의 유일한 주어 빈자리에만 부정 유형을 붙인다."""
    if (event.tag != "VCN" or event.predicate != "아니" or event.negated
            or event.long_negative is not None or not event.source_tokens
            or any(argument.role != "complement" for argument in event.arguments)
            or head.owned or head.owners
            or head.noun_classes & {"unresolved_modifier", "unresolved_relation", "quoted_nominal"}):
        return None
    complement = _unique_argument(event, "complement")
    if complement is None or complement.particle_form not in {"이", "가"} or len(complement.members) != 1:
        return None
    source = complement.members[0]
    if _clear_negative_entity(source, event.source_tokens):
        return head
    clause_start = max((token.end for token in event.source_tokens if token.end <= source.start
                        and (_tag(token.tag) in _CASE_ROLES or _tag(token.tag) in _ENDINGS)),
                       default=min(token.start for token in event.source_tokens))
    types = _negative_type_source(source, complement, None, event.source_tokens, clause_start)
    if not types:
        # 새 유형 부정을 인증하지 못하면 기존 관형 수식의 미지원 판정으로 넘긴다.
        return None
    for semantic_class in sorted(types):
        _emit(evidence, head, "negative_copular_category", source.start, source.end, semantic_class)
        _emit(evidence, head, "negative_copular_category_predicate", event.start, event.end, semantic_class)
    return head

_NOUN_CLASSES = MappingProxyType(dict(_NOUN_CLASSES) | {
    "수준": frozenset({"appraised_level"}),
})


def _judgment_attribute_relative(evidence, event, head):
    """가치ㆍ수준 판단 사건이 독립 판단 핵어를 수식하는 국소 관계만 받는다."""
    if (not ((event.predicate == "판단하" and event.tag in {"VV", "XSV"})
             or (event.predicate == "헤아리" and event.tag == "VV")) or event.negated
            or event.long_negative is not None or head.owned or head.owners
            or not _has_inherent_type(head, {"assessment_head"})
            or any(argument.role not in {"subject", "object"} for argument in event.arguments)):
        return None
    objects = _unique_argument(event, "object")
    if (objects is None or not objects.members
            or any(not member.noun_classes & {"value_modifier", "appraised_level"}
                   or member.noun_classes & {"unresolved_modifier", "unresolved_relation", "quoted_nominal"}
                   for member in objects.members)):
        return None
    return _derive_relation(evidence, head, "assessment", "judgment_of_value_or_level", event, objects.members)


# 통화 값ㆍ기준ㆍ비율의 실제 연산 또는 완전한 명사 구성을 위한 의미 사실이다.
_NOUN_CLASSES = MappingProxyType(dict(_NOUN_CLASSES) | {
    "자국": frozenset({"domestic_currency_modifier"}),
    "통화": frozenset({"currency"}),
    "자국통화": frozenset({"currency"}),
    "외화": frozenset({"currency", "foreign_currency_basis"}),
    "금": frozenset({"metal_currency_basis"}),
    "금속": frozenset({"metal_currency_basis"}),
    "값": _NOUN_CLASSES["값"] | {"currency_value_head"},
    "비율": frozenset({"currency_ratio_head"}),
})
_ADNOMINAL_COMPATIBILITY = MappingProxyType(dict(_ADNOMINAL_COMPATIBILITY) | {
    "domestic_currency_modifier": frozenset({"currency"}),
})


def _owned_currency_value(member):
    return ("currency_value_head" in member.noun_classes and len(member.owners) == 1
            and "currency" in member.owners[0].noun_classes
            and not (member.noun_classes | member.owners[0].noun_classes) & {
                "unresolved_modifier", "unresolved_relation", "quoted_nominal"})


def _currency_basis_argument(event):
    """금속ㆍ외화 목적어를 실제 기준으로 삼은 긍정 하다 관계만 인증한다."""
    if event.predicate != "하" or event.tag != "VV" or event.negated or event.long_negative is not None:
        return None
    basis = _unique_argument(event, "basis")
    if basis is None or len(basis.members) != 1 or basis.particle_form not in {"로", "으로"}:
        return None
    head = basis.members[0]
    if head.form != "기준" or len(head.bound_arguments) != 1:
        return None
    source = head.bound_arguments[0]
    if (source.role != "object" or len(source.members) != 1
            or not source.members[0].noun_classes & {"metal_currency_basis", "foreign_currency_basis"}
            or source.members[0].noun_classes & {"unresolved_modifier", "unresolved_relation", "quoted_nominal"}
            or any(argument.role != "basis" for argument in event.arguments)):
        return None
    return basis, source.members[0]


def _currency_display_arguments(event):
    if (not ((event.predicate == "표시하" and event.tag in {"VV", "XSV"})
             or (event.predicate == "적" and event.tag == "VV")) or event.negated or event.long_negative is not None):
        return None
    objects, via = _unique_argument(event, "object"), _unique_argument(event, "via")
    if (objects is None or len(objects.members) != 1 or not _owned_currency_value(objects.members[0])
            or via is None or len(via.members) != 1 or via.particle_form not in {"로", "으로"}
            or "currency_standard_basis_ratio" not in via.members[0].noun_classes
            or via.members[0].noun_classes & {"unresolved_modifier", "unresolved_relation", "quoted_nominal"}
            or any(argument.role not in {"object", "via"} for argument in event.arguments)):
        return None
    return objects.members[0], via.members[0]


def _currency_ratio_relative(evidence, event, head):
    basis = _currency_basis_argument(event)
    if basis is not None and "currency_ratio_head" in head.noun_classes and not head.owned and not head.owners:
        argument, metal = basis
        return _derive_relation(evidence, head, "currency_standard_basis_ratio", "currency_ratio_basis_operation", event, argument.members + (metal,))
    display = _currency_display_arguments(event)
    if (display is None or head.form != "것" or not any(
            relation == "bound_event_nominal_head" and (start, end) == (head.start, head.end)
            for _, relation, start, end in head.facts)):
        return None
    value, ratio = display
    return _derive_relation(evidence, head, "currency_value_basis_ratio", "currency_value_basis_ratio_operation", event,
                            (value, ratio, value.owners[0]))


def _currency_nominal_composition(modifiers, head):
    if len(modifiers) != 1:
        return None
    source = modifiers[0]
    if "foreign_currency_modifier" in source.noun_classes and "currency" in head.noun_classes:
        return _derive(head, "foreign_currency_basis", "foreign_currency_nominal", source.start, source.end)
    if (source.noun_classes | head.noun_classes) & {"unresolved_modifier", "unresolved_relation", "quoted_nominal"}:
        return None
    if source.noun_classes & {"metal_currency_basis", "foreign_currency_basis"} and head.form == "기준":
        head = replace(head, owned=source.owned, owners=source.owners)
        return _derive(head, "currency_basis_head", "currency_nominal_basis", source.start, source.end)
    if "currency_basis_head" in source.noun_classes and "currency_ratio_head" in head.noun_classes:
        head = replace(head, owned=source.owned, owners=source.owners)
        head = _derive(head, "currency_standard_basis_ratio", "currency_nominal_ratio", source.start, source.end)
        if len(source.owners) == 1 and "currency" in source.owners[0].noun_classes:
            head = _derive(head, "currency_value_basis_ratio", "owned_currency_basis_ratio_nominal", source.owners[0].start, source.owners[0].end)
        return head
    return None


_NOUN_CLASSES = MappingProxyType(dict(_NOUN_CLASSES) | {
    "뜻": frozenset({"meaning_definition_head"}),
    "타국": frozenset({"foreign_currency_modifier"}),
    "돈": frozenset({"currency"}),
    "타국돈": frozenset({"currency", "foreign_currency_basis"}),
    "비": frozenset({"currency_ratio_head"}),
})
_ADNOMINAL_COMPATIBILITY = MappingProxyType(dict(_ADNOMINAL_COMPATIBILITY) | {
    "foreign_currency_modifier": frozenset({"currency"}),
})


def _closed_currency_description_atom(text, tokens, inside, heads, skipped, opening, closing):
    """내부 통화 관계를 먼저 완성한 닫힌 설명만 실제 뜻 포장의 원자로 내보낸다."""
    if not inside or (tokens[inside[-1]].form, _tag(tokens[inside[-1]].tag)) != ("것", "NNB"):
        return None
    if any(unicodedata.category(char).startswith("P") or char in "\r\n" for char in text[opening + 1:closing]):
        return None
    if any(text[tokens[index].start:tokens[index].end] != tokens[index].form for index in inside):
        return None
    following = tuple(index for index, token in enumerate(tokens) if token.start >= closing + 1)
    wrapper = tuple(_units(tokens, following, heads, skipped))
    if (len(wrapper) < 3 or (wrapper[0].form, wrapper[0].tag) != ("이", "VCP")
            or (wrapper[1].form, wrapper[1].tag) != ("라는", "ETM")
            or wrapper[2].form != "뜻" or "meaning_definition_head" not in wrapper[2].noun_classes):
        return None
    nominal = _scan_scope(tokens, inside, {}, heads, skipped)
    if (not nominal or len(nominal) != 1 or "currency_value_basis_ratio" not in nominal[0].noun_classes
            or nominal[0].noun_classes & {"unresolved_modifier", "unresolved_relation", "quoted_nominal"}):
        return None
    head = nominal[0]
    start, end = tokens[inside[0]].start, head.end
    if text[opening + 1:start].strip() or text[end:closing].strip():
        return None
    facts = head.facts + (("currency_value_basis_ratio", "closed_currency_description", head.start, head.end),)
    atom = _Unit(text[start:end], "NNG", start, end, head.token_index,
                 noun_classes=frozenset({"currency_value_basis_ratio", "closed_currency_description", "quoted_nominal"}),
                 nominal_facts=facts)
    return _QuotedNominal(opening, closing, atom, inside)



def _coordinates_price_side(units, position):
    """같은 가격 차원의 두 실제 서술어가 한 쪽 핵어를 수식하는 국소 병렬만 받는다."""
    return (position + 4 < len(units) and units[position].tag == "VA"
            and units[position].form in {"싸", "비싸"}
            and (units[position + 1].form, units[position + 1].tag) == ("거나", "EC")
            and units[position + 2].tag == "VA" and units[position + 2].form in {"싸", "비싸"}
            and units[position + 3].tag == "ETM"
            and (units[position + 4].form, units[position + 4].tag) == ("쪽", "NNB"))


def _price_side_modifier(event, head):
    if (event.predicate not in {"싸", "비싸"} or event.tag != "VA" or event.negated or event.arguments
            or not any(relation == "bound_price_side_head" for _, relation, _, _ in head.facts)):
        return None
    return _derive(head, "price_side", "price_side_scalar_modifier", event.start, event.end)


def _price_bias_on_completed_nominal(event, head):
    """완성된 독립 보통 가격과 실제 가격 쪽 논항의 편향 수식만 보존한다."""
    state = event.long_negative
    location = _unique_argument(event, "location")
    if (event.predicate != "치우치" or event.tag != "VV" or state is None
            or state.relative_kind != "direct" or state.unresolved_dependencies or not state.licensed
            or head.owned or head.owners or "ordinary_price" not in head.noun_classes
            or not _has_inherent_type(head, {"price"}) or location is None
            or location.particle_form != "에" or len(location.members) != 1
            or "price_side" not in location.members[0].noun_classes
            or any(argument.role != "location" for argument in event.arguments)):
        return None
    return _derive(head, "neutral_modifier", "ordinary_price_bias_modifier", state.start, state.end)
