"""한국어 음운 규칙과 종성 전이를 선언형 자료구조로 정의한다."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NucleusTransfer:
    """모음이 바뀌어도 같은 원문 핵을 소유하는 성분 대응 선언이다."""

    vowels: tuple[tuple[str, str], ...]
    onsets: frozenset[str]


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    """하나의 음운 규칙을 설명한다."""

    id: str
    article: str
    title: str
    requires_morphology: bool = False
    nucleus_transfer: NucleusTransfer | None = None


@dataclass(frozen=True, slots=True)
class CodaTransition:
    """종성 하나를 대표음으로 바꾸는 문맥 독립 전이다."""

    source: str
    target: str
    rule_id: str


# 모음 핵의 전이 선언과 실제 음운 규칙은 같은 성분 자료를 공유한다.
PALATAL_J_VOWELS = {"ㅑ": "ㅏ", "ㅒ": "ㅐ", "ㅕ": "ㅓ", "ㅖ": "ㅔ", "ㅛ": "ㅗ", "ㅠ": "ㅜ"}
PALATAL_J_ONSETS = frozenset({"ㅈ", "ㅉ", "ㅊ"})
_PALATAL_J_NUCLEUS = NucleusTransfer(tuple(PALATAL_J_VOWELS.items()), PALATAL_J_ONSETS)


RULES = {
    "ko.semantic.context": RuleDefinition("ko.semantic.context", "어휘·문맥", "문맥 관계로 선택한 어휘 의미", True),
    "ko.saisiot.30": RuleDefinition("ko.saisiot.30", "30.3", "사이시옷 뒤 ㄴ 첨가", True),
    "ko.n_insertion.compound": RuleDefinition("ko.n_insertion.compound", "29", "복합어·접미사 경계의 ㄴ 첨가", True),
    "ko.n_insertion.reduplication": RuleDefinition("ko.n_insertion.reduplication", "29.1", "반복 부사 내부의 ㄴ 첨가", True),
    "ko.sino.tensing.26": RuleDefinition("ko.sino.tensing.26", "26", "확인한 한자어 내부 ㄹ 뒤 된소리", True),
    "ko.lexical.tensing": RuleDefinition("ko.lexical.tensing", "28·어휘", "어휘별 경음화 경계", True),
    "ko.liquid.suffix.20": RuleDefinition("ko.liquid.suffix.20", "20.단서", "명사·ㄹ 계열 접미사 경계의 비음화", True),
    "ko.cluster.tensing": RuleDefinition("ko.cluster.tensing", "23·25", "ㄾ 단순화에 앞선 된소리되기"),
    "ko.letter_name.16": RuleDefinition("ko.letter_name.16", "16", "한글 자모 이름과 모음 조사의 연음", True),
    "ko.n_insertion.word": RuleDefinition("ko.n_insertion.word", "29.2", "두 단어를 이어 읽을 때의 ㄴ 첨가", True),
    "ko.ending.tensing.27": RuleDefinition("ko.ending.tensing.27", "27", "ㄹ로 시작하는 어미 내부의 된소리", True),
    "ko.lexical.verified": RuleDefinition("ko.lexical.verified", "15·17·29", "공식 사전과 상담으로 확인한 어휘 발음"),
    "ko.official.morpheme": RuleDefinition("ko.official.morpheme", "15-30", "형태소로 확인한 어휘 발음 보완", True),
    # 이전 기록을 읽을 때의 호환용 ID이며 일반 규칙 실행에서는 더 이상 쓰지 않는다.
    "ko.official.enumerated": RuleDefinition(
        "ko.official.enumerated",
        "10·11·15·16·20·24-30",
        "공식 고시의 안전한 열거 발음",
    ),
    "ko.vowel.jyeo": RuleDefinition("ko.vowel.jyeo", "5.1", "져·쪄·쳐의 ㅕ 약화",
                                   nucleus_transfer=NucleusTransfer((("ㅕ", "ㅓ"),), PALATAL_J_ONSETS)),
    "ko.vowel.palatal_j_canonical": RuleDefinition(
        "ko.vowel.palatal_j_canonical", "5.1·해설", "경구개음 뒤 j계 모음의 정규 발음 표기",
        nucleus_transfer=_PALATAL_J_NUCLEUS,
    ),
    "ko.vowel.consonant_ui": RuleDefinition("ko.vowel.consonant_ui", "5.3", "자음 뒤 ㅢ의 ㅣ 발음"),
    "ko.hieuh.consonant": RuleDefinition("ko.hieuh.consonant", "12", "ㅎ 탈락과 거센소리되기"),
    "ko.palatalization": RuleDefinition("ko.palatalization", "17", "구개음화", True),
    "ko.hieuh.vowel": RuleDefinition("ko.hieuh.vowel", "12.4", "ㅎ 탈락 뒤 모음 연결"),
    "ko.liaison.single": RuleDefinition("ko.liaison.single", "13", "홑받침 연음"),
    "ko.liaison.cluster": RuleDefinition("ko.liaison.cluster", "14", "겹받침 연음"),
    "ko.n_insertion.numeral": RuleDefinition(
        "ko.n_insertion.numeral", "29", "수사 합성어의 ㄴ 첨가"
    ),
    "ko.coda.9": RuleDefinition("ko.coda.9", "9", "받침 대표음"),
    "ko.coda.10": RuleDefinition("ko.coda.10", "10", "겹받침 대표음"),
    "ko.coda.11": RuleDefinition("ko.coda.11", "11", "겹받침 대표음"),
    "ko.nasalization": RuleDefinition("ko.nasalization", "18", "비음화"),
    "ko.liquid.19": RuleDefinition("ko.liquid.19", "19", "ㄹ의 비음화"),
    "ko.liquid.20": RuleDefinition("ko.liquid.20", "20", "ㄴ·ㄹ 유음화"),
    "ko.tensification": RuleDefinition("ko.tensification", "23", "받침 뒤 된소리되기"),
    "ko.ui.particle": RuleDefinition("ko.ui.particle", "5.4.2", "조사 의 발음", True),
    "ko.stem.rieul_giyeok": RuleDefinition("ko.stem.rieul_giyeok", "11.1", "용언 ㄺ 어간", True),
    "ko.stem.tensing.24": RuleDefinition("ko.stem.tensing.24", "24", "용언 ㄴ·ㅁ 계열 어간 뒤 된소리", True),
    "ko.stem.tensing.25": RuleDefinition("ko.stem.tensing.25", "25", "용언 ㄼ·ㄾ 어간 뒤 된소리", True),
    "ko.lexical.balb_neolb": RuleDefinition(
        "ko.lexical.balb_neolb", "10.1", "밟·넓 어휘 예외"
    ),
    "ko.modifier.tensing.27": RuleDefinition("ko.modifier.tensing.27", "27", "관형형 ㄹ 뒤 된소리", True),
    "ko.liaison.lexical": RuleDefinition("ko.liaison.lexical", "15", "실질 형태소 연음", True),
}

# ㅒ·ㅖ는 j계 구성과 경구개음 뒤 제약에서 도출한 표기 대응이다.
# w계 모음이나 ㅐ/ㅔ 구별은 이 대응에 포함하지 않는다.
CODA_TRANSITIONS = {
    "ㄲ": CodaTransition("ㄲ", "ㄱ", "ko.coda.9"),
    "ㅋ": CodaTransition("ㅋ", "ㄱ", "ko.coda.9"),
    "ㅅ": CodaTransition("ㅅ", "ㄷ", "ko.coda.9"),
    "ㅆ": CodaTransition("ㅆ", "ㄷ", "ko.coda.9"),
    "ㅈ": CodaTransition("ㅈ", "ㄷ", "ko.coda.9"),
    "ㅊ": CodaTransition("ㅊ", "ㄷ", "ko.coda.9"),
    "ㅌ": CodaTransition("ㅌ", "ㄷ", "ko.coda.9"),
    "ㅎ": CodaTransition("ㅎ", "ㄷ", "ko.coda.9"),
    "ㅍ": CodaTransition("ㅍ", "ㅂ", "ko.coda.9"),
    "ㄳ": CodaTransition("ㄳ", "ㄱ", "ko.coda.10"),
    "ㄵ": CodaTransition("ㄵ", "ㄴ", "ko.coda.10"),
    "ㄶ": CodaTransition("ㄶ", "ㄴ", "ko.coda.10"),
    "ㄼ": CodaTransition("ㄼ", "ㄹ", "ko.coda.10"),
    "ㄽ": CodaTransition("ㄽ", "ㄹ", "ko.coda.10"),
    "ㄾ": CodaTransition("ㄾ", "ㄹ", "ko.coda.10"),
    "ㅄ": CodaTransition("ㅄ", "ㅂ", "ko.coda.10"),
    "ㄺ": CodaTransition("ㄺ", "ㄱ", "ko.coda.11"),
    "ㄻ": CodaTransition("ㄻ", "ㅁ", "ko.coda.11"),
    "ㄿ": CodaTransition("ㄿ", "ㅂ", "ko.coda.11"),
    "ㅀ": CodaTransition("ㅀ", "ㄹ", "ko.coda.11"),
}


LIAISON_CLUSTER = {
    "ㄳ": ("ㄱ", "ㅆ"),
    "ㄵ": ("ㄴ", "ㅈ"),
    "ㄶ": ("ㄴ", "ㅎ"),
    "ㄺ": ("ㄹ", "ㄱ"),
    "ㄻ": ("ㄹ", "ㅁ"),
    "ㄼ": ("ㄹ", "ㅂ"),
    "ㄽ": ("ㄹ", "ㅆ"),
    "ㄾ": ("ㄹ", "ㅌ"),
    "ㄿ": ("ㄹ", "ㅍ"),
    "ㅀ": ("ㄹ", "ㅎ"),
    "ㅄ": ("ㅂ", "ㅆ"),
}

HIEUH_FINALS = frozenset({"ㅎ", "ㄶ", "ㅀ"})
HIEUH_REMAINDER = {"ㅎ": None, "ㄶ": "ㄴ", "ㅀ": "ㄹ"}

# 받침과 초성 ㅎ이 합쳐질 때 남는 종성과 새 초성이다.
HIEUH_ASSIMILATION = {
    "ㄱ": (None, "ㅋ"),
    "ㄲ": (None, "ㅋ"),
    "ㅋ": (None, "ㅋ"),
    "ㄳ": (None, "ㅋ"),
    "ㄺ": ("ㄹ", "ㅋ"),
    "ㄷ": (None, "ㅌ"),
    "ㅅ": (None, "ㅌ"),
    "ㅆ": (None, "ㅌ"),
    "ㅈ": (None, "ㅊ"),
    "ㅊ": (None, "ㅌ"),
    "ㅌ": (None, "ㅌ"),
    "ㄵ": ("ㄴ", "ㅊ"),
    "ㅂ": (None, "ㅍ"),
    "ㅍ": (None, "ㅍ"),
    "ㄼ": ("ㄹ", "ㅍ"),
    "ㄿ": ("ㄹ", "ㅍ"),
    "ㅄ": (None, "ㅍ"),
}

TENSE_ONSET = {"ㄱ": "ㄲ", "ㄷ": "ㄸ", "ㅂ": "ㅃ", "ㅅ": "ㅆ", "ㅈ": "ㅉ"}
NASAL_CODA = {"ㄱ": "ㅇ", "ㄷ": "ㄴ", "ㅂ": "ㅁ"}
