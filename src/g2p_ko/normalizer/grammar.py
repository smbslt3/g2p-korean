"""정규화 토큰 우선순위와 문법 정규식을 정의한다."""

from __future__ import annotations

import re

from .units import (
    _ACRONYM_PATTERN,
    _ALL_UNITS,
    _CURRENCY_UNIT_WORDS,
    _DECIMAL_PATTERN,
    _HANGUL_UNIT_PATTERN,
    _ISO_CURRENCIES,
    _NUMBER_PATTERN,
    _STANDALONE_UNIT_SYMBOL_PATTERN,
    _UNIT_PATTERN,
    _UNSIGNED_NUMBER_PATTERN,
    _WRITTEN_UNIT_INITIAL_PATTERN,
    _WRITTEN_UNIT_PATTERN,
)

# 역사 날짜는 날짜와 사건 이름의 조합 자체가 어휘화된 경우에만 낱자리로 읽는다.
# 날짜와 접미사를 따로 나열하면 실제 사건이 아닌 교차 조합까지 허용하게 된다.
_HISTORY_EVENTS = (
    ("3.1", "절"),
    ("3.1", "운동"),
    ("4.3", "사건"),
    ("4.3", "항쟁"),
    ("4.19", "혁명"),
    ("5.18", "민주화운동"),
    ("6.25", "전쟁"),
    ("8.15", "광복절"),
    ("10.26", "사건"),
)
_HISTORY_PATTERN = (
    "(?:"
    + "|".join(
        date_surface.replace(".", "[.·]") + r"[ \t]*" + re.escape(event)
        for date_surface, event in _HISTORY_EVENTS
    )
    + ")"
)
_IDENTIFIER_NUMBER_PREFIXES = (
    "휴대폰",
    "시리얼",
    "전화",
    "비밀",
    "제품",
    "카드",
    "차량",
    "인증",
    "계좌",
    "주문",
    "식별",
    "우편",
    "팩스",
)
_STANDALONE_IDENTIFIER_LABELS = (
    "연락처",
    "PIN",
    "계좌",
    "버스",
    "번호",
    "좌석",
    "코드",
    "호실",
)
_IDENTIFIER_LABEL_PATTERN = (
    "(?:"
    + "|".join(
        re.escape(item) + r"[ \t]*번호"
        for item in sorted(_IDENTIFIER_NUMBER_PREFIXES, key=lambda item: (-len(item), item))
    )
    + "|"
    + "|".join(
        re.escape(item)
        for item in sorted(_STANDALONE_IDENTIFIER_LABELS, key=lambda item: (-len(item), item))
    )
    + ")"
)
_IDENTIFIER_BODY_PATTERN = (
    r"(?:[0-9]{2,4}[가-힣][0-9]{4}|[0-9]+[A-Za-z]|[0-9]+(?:[ \t-][0-9]+)*)"
)
_KNOWN_EXTENSIONS = "(?:json|ya?ml|toml|csv|tsv|txt|md|py|js|ts|wav|mp3|flac)"
# 숫자 뒤에 붙어도 읽기를 바꾸지 않는 조사·서술격 어미의 닫힌 목록이다.
# 여기 없는 꼬리는 더 긴 낱말일 수 있어 토큰 전체를 보존한다.
_KOREAN_SUFFIXES = frozenset(
    {
        "가",
        "간",
        "과",
        "까지",
        "까지는",
        "께",
        "다",
        "도",
        "라고",
        "라도",
        "로",
        "를",
        "마다",
        "만",
        "밖에",
        "보다",
        "부터",
        "부터는",
        "당",
        "에",
        "에는",
        "에게",
        "에서",
        "와",
        "은",
        "을",
        "으로",
        "의",
        "이",
        "이다",
        "이었다",
        "이라",
        "이라고",
        "이라도",
        "이나",
        "이고",
        "인데",
        "이며",
        "이면",
        "이지만",
        "입니다",
        "였다",
        "처럼",
        "는",
        "쯤",
        "씩",
        "야",
        "이야",
        "랑",
        "이랑",
        "한테",
        "한테서",
        "조차",
        "마저",
        "뿐",
        "로서",
        "으로서",
        "로써",
        "으로써",
        "라서",
        "이라서",
        "짜리",
        "가량",
    }
)
_SORTED_KOREAN_SUFFIXES = tuple(
    sorted(_KOREAN_SUFFIXES, key=lambda item: (-len(item), item))
)

_KOREAN_SUFFIX_PATTERN = "(?:" + "|".join(
    re.escape(item) for item in _SORTED_KOREAN_SUFFIXES
) + ")"
_HSPACE = r"[ \t]*"
_ASCII_IDENTIFIER_LEFT_BOUNDARY = r"(?<![A-Za-z0-9_])(?<![A-Za-z0-9_]\.)"
_ASCII_IDENTIFIER_RIGHT_BOUNDARY = r"(?![A-Za-z0-9_])(?!\.[A-Za-z0-9_])"
_DOTTED_IDENTIFIER_RIGHT_GUARD = r"(?!\.[A-Za-z0-9_])"
_RANGE_SEPARATOR = r"[~〜～∼–—]"
_RANGE_UNIT_PATTERN = rf"(?:{_UNIT_PATTERN}|%[pP]|%|％|만원|억원|조원)"
# 구조화 날짜·시간 패턴을 구성하는 단위가 범위 양쪽에 서면 `3월 1일~3월 5일`의
# 가운데를 잘라 갈 수 있으므로 양쪽 단위 범위에서는 제외한다.
_RANGE_BOTH_EXCLUDED_UNITS = frozenset({"년", "월", "일", "시", "분", "초"})
_RANGE_BOTH_UNIT_PATTERN = (
    "(?:"
    + "|".join(
        re.escape(item)
        for item in sorted(
            set(_ALL_UNITS) - _RANGE_BOTH_EXCLUDED_UNITS,
            key=lambda item: (-len(item), item),
        )
    )
    + "|%[pP]|%|％|만원|억원|조원)"
)
_ISO_CURRENCY_PATTERN = "(?:" + "|".join(_ISO_CURRENCIES) + ")"

# 대표번호는 구분자 표기만 전화로 읽는다. 무구분 8자리는 1,500만 같은
# 일반 수와 구별할 수 없어 일반 숫자 규칙에 맡긴다.
_PHONE_PATTERN = (
    r"(?:\+82[-. ]?10[-. ]?[0-9]{3,4}[-. ][0-9]{4}"
    r"|0[0-9]{1,3}[-. ][0-9]{3,4}[-. ][0-9]{4}"
    r"|1[568][0-9]{2}[- ][0-9]{4})"
)
# 전화 뒤에 네 자리 묶음이 하나 더 이어지면 카드번호류 사슬의 앞부분일 수
# 있으므로 전화로 잘라 읽지 않고 malformed_phone 보존 경로로 넘긴다.
_CARD_CHAIN_GUARD = r"(?![-. ][0-9]{4}(?![0-9]))"
_PHONE_EXPRESSION = rf"{_PHONE_PATTERN}{_CARD_CHAIN_GUARD}(?:{_KOREAN_SUFFIX_PATTERN})?"
_DATE_SUFFIX_PATTERN = rf"(?:\.?{_KOREAN_SUFFIX_PATTERN})?"
_DATE_PATTERN = rf"""
    [0-9]{{4}}(?:
        {_HSPACE}-{_HSPACE}[0-9]{{1,2}}{_HSPACE}-{_HSPACE}[0-9]{{1,2}}
      | {_HSPACE}/{_HSPACE}[0-9]{{1,2}}{_HSPACE}/{_HSPACE}[0-9]{{1,2}}
      | {_HSPACE}\.{_HSPACE}[0-9]{{1,2}}{_HSPACE}\.{_HSPACE}[0-9]{{1,2}}
    ){_DATE_SUFFIX_PATTERN}
"""
_KOREAN_DATE_PATTERN = rf"""
    [0-9]{{4}}{_HSPACE}년{_HSPACE}[0-9]{{1,2}}{_HSPACE}월
    {_HSPACE}[0-9]{{1,2}}{_HSPACE}일(?:{_KOREAN_SUFFIX_PATTERN})?
"""
_MONTH_DAY_PATTERN = rf"""
    [0-9]{{1,2}}{_HSPACE}월{_HSPACE}[0-9]{{1,2}}{_HSPACE}일
    (?:{_KOREAN_SUFFIX_PATTERN})?
"""
_YEAR_MONTH_PATTERN = rf"""
    [0-9]{{4}}{_HSPACE}년(?:{_HSPACE}[0-9]{{1,2}}{_HSPACE}월)?
    (?:{_KOREAN_SUFFIX_PATTERN})?
"""
# 날짜 범위 읽기는 아직 지원하지 않으므로 공백을 포함한 사슬 전체를 한 토큰으로
# 보존한다. 그렇지 않으면 malformed_structured가 공백에서 끊겨 뒤쪽 날짜가
# 부분 변환된다.
_DATE_RANGE_OPERAND_PATTERN = rf"""
    (?:{_KOREAN_DATE_PATTERN}|{_MONTH_DAY_PATTERN}|{_YEAR_MONTH_PATTERN})
"""
_COLON_TIME_PATTERN = rf"""
    (?:(?:오전|오후){_HSPACE})?[0-9]{{1,2}}:[0-9]{{2}}(?::[0-9]{{2}})?
    (?:{_KOREAN_SUFFIX_PATTERN})?
"""
_KOREAN_TIME_PATTERN = rf"""
    (?:(?:오전|오후){_HSPACE})?[0-9]{{1,2}}{_HSPACE}시
    (?:{_HSPACE}[0-9]{{1,2}}{_HSPACE}분(?:{_HSPACE}[0-9]{{1,2}}{_HSPACE}초)?)?
    (?:{_KOREAN_SUFFIX_PATTERN})?
"""
_TIME_RANGE_OPERAND_PATTERN = rf"""
    (?!(?:(?:오전|오후){_HSPACE})?[0-9]{{1,2}}{_HSPACE}시간)
    (?:{_COLON_TIME_PATTERN}|{_KOREAN_TIME_PATTERN})
"""
_TIME_RANGE_PATTERN = rf"""
    (?=(?:(?:오전|오후){_HSPACE})?[0-9]{{1,2}}(?:{_HSPACE}시|:))
    (?P<left>{_TIME_RANGE_OPERAND_PATTERN}){_HSPACE}{_RANGE_SEPARATOR}{_HSPACE}
    (?P<right>{_TIME_RANGE_OPERAND_PATTERN})
"""
# 단일 패스 스캐너에서는 거대한 조사 목록을 매 위치마다 대조하지 않는다.
# 여기서는 범위 전체만 잡고, 정확한 조사·시각 유효성은 렌더러가 위 문법으로 검증한다.
_TIME_RANGE_SCAN_OPERAND_PATTERN = rf"""
    (?:(?:오전|오후){_HSPACE})?[0-9]{{1,2}}
    (?: :[0-9]{{2}}(?::[0-9]{{2}})?
      | {_HSPACE}시(?:{_HSPACE}[0-9]{{1,2}}{_HSPACE}분
        (?:{_HSPACE}[0-9]{{1,2}}{_HSPACE}초)?)?)
    [가-힣]*
"""
_TIME_RANGE_SCAN_PATTERN = rf"""
    {_TIME_RANGE_SCAN_OPERAND_PATTERN}{_HSPACE}{_RANGE_SEPARATOR}{_HSPACE}
    {_TIME_RANGE_SCAN_OPERAND_PATTERN}
"""
_MONTH_PATTERN = rf"[0-9]{{1,2}}{_HSPACE}월(?:{_KOREAN_SUFFIX_PATTERN})?"
_MIXED_FRACTION_PATTERN = rf"""
    {_UNSIGNED_NUMBER_PATTERN}[ \t]+{_UNSIGNED_NUMBER_PATTERN}/{_UNSIGNED_NUMBER_PATTERN}
    (?:{_HSPACE}{_WRITTEN_UNIT_PATTERN})?(?:{_KOREAN_SUFFIX_PATTERN})?
"""
_CURRENCY_WORD_PATTERN = "(?:" + "|".join(sorted(_CURRENCY_UNIT_WORDS, key=len, reverse=True)) + ")"
_CURRENCY_PATTERN = rf"[\$₩€£¥]{_HSPACE}{_NUMBER_PATTERN}(?:{_HSPACE}{_CURRENCY_WORD_PATTERN})?"
_ISO_CURRENCY_EXPRESSION = rf"""
    (?:{_ISO_CURRENCY_PATTERN}{_HSPACE}{_NUMBER_PATTERN}
      | {_NUMBER_PATTERN}{_HSPACE}{_ISO_CURRENCY_PATTERN})
    (?:{_HSPACE}{_CURRENCY_WORD_PATTERN})?
"""
_SCALE_POWERS = {"십": 1, "백": 2, "천": 3, "만": 4, "억": 8, "조": 12}
_SCALE_PATTERN = "(?:" + "|".join(_SCALE_POWERS) + ")"
_SCALED_CURRENCY_PATTERN = rf"{_NUMBER_PATTERN}{_HSPACE}{_SCALE_PATTERN}{_HSPACE}원"
# 명시된 단위가 있을 때만 배율 사슬을 수량으로 읽는다. 넓게 잡은 사슬의
# 배율 순서·내부 부호·조사 꼬리는 렌더러가 토큰 전체를 검증한다.
_HIERARCHICAL_SCALE_PATTERN = rf"(?:[십백천]{_HSPACE}[만억조]|{_SCALE_PATTERN})"
_SCALED_NUMBER_PATTERN = (
    rf"{_NUMBER_PATTERN}{_HSPACE}{_HIERARCHICAL_SCALE_PATTERN}"
    rf"(?:{_HSPACE}{_NUMBER_PATTERN}{_HSPACE}{_HIERARCHICAL_SCALE_PATTERN})*"
    rf"(?:{_HSPACE}{_NUMBER_PATTERN})?"
)
_SCALED_QUANTITY_PATTERN = (
    rf"{_SCALED_NUMBER_PATTERN}{_HSPACE}(?:여{_HSPACE})?"
    rf"{_UNIT_PATTERN}[가-힣]*"
)
_NIGHTS_DAYS_PATTERN = (
    rf"{_NUMBER_PATTERN}{_HSPACE}박{_HSPACE}{_NUMBER_PATTERN}{_HSPACE}일[가-힣]*"
)
_MATH_OPERATOR_PATTERN = r"(?:/|\*|\+|<|>|≤|≥|÷|=)"
_NON_ASCII_NUMERIC_RANGES = (
    r"\u00BC-\u00BE\u2070-\u209F\u2150-\u218F\u2460-\u24FF"
    r"\uFF10-\uFF19\U0001D7CE-\U0001D7FF"
)
_NUMERIC_GUARD_CHARACTERS = (
    rf"0-9A-Za-z_.,:/+−^~～∼–—×±÷=*<>≤≥%％²³$₩€£¥°℃㎡㎥μµ{_NON_ASCII_NUMERIC_RANGES}\-"
)
_NUMERIC_GUARD_SIGNAL = (
    rf"A-Za-z_.,:/+−^~～∼–—×±÷=*<>≤≥%％²³$₩€£¥°℃㎡㎥μµ{_NON_ASCII_NUMERIC_RANGES}\-"
)
_NUMERIC_SINGLE_PREFIX = r".,:/+\-"
_NUMERIC_STRONG_PREFIX = (
    rf"−^~～∼–—×±÷=*<>≤≥%％²³$₩€£¥°℃㎡㎥μµ{_NON_ASCII_NUMERIC_RANGES}"
)
_STRUCTURED_TOKEN_CONTINUATION = (
    rf"A-Za-z0-9_가-힣:/+−^~～∼–—×±÷=*<>≤≥%％²³$₩€£¥°℃㎡㎥μµ"
    rf"{_NON_ASCII_NUMERIC_RANGES}\-"
)
# 수량 뒤의 조사·어미는 허용하되 식별자·수식 사슬은 기존 보존 규칙에
# 넘긴다. 구조화 토큰 경계와 같은 집합을 쓰고 한글 범위만 제외한다.
_QUANTITY_CONTINUATION = _STRUCTURED_TOKEN_CONTINUATION.replace("가-힣", "")
_FRACTION_UNIT_PATTERN = rf"""
    (?=[0-9][0-9,.]*/[0-9])
    {_UNSIGNED_NUMBER_PATTERN}/{_UNSIGNED_NUMBER_PATTERN}
    {_HSPACE}(?={_WRITTEN_UNIT_INITIAL_PATTERN}){_WRITTEN_UNIT_PATTERN}
"""
_NUMBER_UNIT_PATTERN = rf"""
    (?=[+\-−]?[0-9][0-9,.]*{_HSPACE}
        (?:{_SCALE_PATTERN}{_HSPACE})?(?:여{_HSPACE})?
        {_WRITTEN_UNIT_INITIAL_PATTERN})
    {_NUMBER_PATTERN}(?:{_HSPACE}{_SCALE_PATTERN})?
    {_HSPACE}(?:여{_HSPACE})?
    (?={_WRITTEN_UNIT_INITIAL_PATTERN}){_WRITTEN_UNIT_PATTERN}
"""
_QUANTITY_UNIT_PATTERN = rf"(?:{_FRACTION_UNIT_PATTERN}|{_NUMBER_UNIT_PATTERN})"
_INDEFINITE_UNIT_PATTERN = rf"(?:몇|수){_HSPACE}{_WRITTEN_UNIT_PATTERN}"
_UNIT_PER_PATTERN = rf"{_WRITTEN_UNIT_PATTERN}당(?:{_KOREAN_SUFFIX_PATTERN})?"
_STANDALONE_UNIT_SYMBOL_EXPRESSION = (
    rf"{_STANDALONE_UNIT_SYMBOL_PATTERN}(?:{_KOREAN_SUFFIX_PATTERN})?"
)
_SEMANTIC_CLUSTER_PATTERN = rf"""
    (?:[+\-]{{2,}}(?:[{_NUMERIC_GUARD_CHARACTERS}]|[^\x00-\x7F\s])*
      | [{_NUMERIC_SINGLE_PREFIX}][{_NUMERIC_STRONG_PREFIX}]
        (?:[{_NUMERIC_GUARD_CHARACTERS}]|[^\x00-\x7F\s])*
      | [{_NUMERIC_SINGLE_PREFIX}][0-9](?:[{_NUMERIC_GUARD_CHARACTERS}]|[^\x00-\x7F\s])*
      | [{_NUMERIC_STRONG_PREFIX}](?:[{_NUMERIC_GUARD_CHARACTERS}]|[^\x00-\x7F\s])*
      | [0-9]+(?:[{_NUMERIC_GUARD_SIGNAL}가-힣]|[^\x00-\x7F\s])
        (?:[{_NUMERIC_GUARD_CHARACTERS}]|[^\x00-\x7F\s])*)
"""
_MIXED_SUFFIX_PATTERN = rf"""
    (?:[\$₩€£¥]{_HSPACE})?[0-9][{_NUMERIC_GUARD_CHARACTERS}가-힣]*
    [가-힣]+[A-Za-z][{_NUMERIC_GUARD_CHARACTERS}가-힣]*
"""
_MIXED_CURRENCY_PATTERN = rf"""
    (?:
        [+\-−]?[$₩€£¥]{_HSPACE}{_NUMBER_PATTERN}{_HSPACE}{_ISO_CURRENCY_PATTERN}
      | {_ISO_CURRENCY_PATTERN}{_HSPACE}[$₩€£¥]{_HSPACE}{_NUMBER_PATTERN}
      | [+\-−][$₩€£¥]{_HSPACE}{_NUMBER_PATTERN}
    )
"""
_SEMANTIC_OPERAND_PATTERN = rf"""
    (?:{_DATE_PATTERN}|{_COLON_TIME_PATTERN}|{_CURRENCY_PATTERN}
      | {_NUMBER_PATTERN}{_HSPACE}(?:{_UNIT_PATTERN}|%[pP]|%|％))
"""
_SEMANTIC_PAIR_PATTERN = rf"""
    {_SEMANTIC_OPERAND_PATTERN}{_HSPACE}[-−–—~～∼/+*=<>≤≥±÷×]{_HSPACE}
    {_SEMANTIC_OPERAND_PATTERN}
"""
_MALFORMED_PHONE_PATTERN = rf"""
    (?:\+[0-9]{{1,3}}|0[0-9]{{1,3}})(?:[-. ][0-9]+){{2,}}
"""
# 긴급 번호는 조사가 바로 붙거나(112에) 뒤에 다른 낱말이 이어지지 않을 때만
# 낱자리로 읽는다. `112 페이지` 같은 수량 문맥은 일반 숫자 규칙에 맡긴다.
_EMERGENCY_PATTERN = rf"(?:112|119)(?:{_KOREAN_SUFFIX_PATTERN}|(?![ \t]+[가-힣A-Za-z]))"
_CONTEXTUAL_SHORT_DATE_PATTERN = rf"""
    (?:날짜|생일)(?:은|는)?{_HSPACE}[0-9]{{1,2}}[./][0-9]{{1,2}}
    (?:{_KOREAN_SUFFIX_PATTERN})?
"""
_MALFORMED_STRUCTURED_PATTERN = rf"""
    (?:{_PHONE_EXPRESSION}|{_COLON_TIME_PATTERN}|{_KOREAN_TIME_PATTERN}
      | {_DATE_PATTERN}|{_KOREAN_DATE_PATTERN}|{_MONTH_DAY_PATTERN})
    (?:[{_STRUCTURED_TOKEN_CONTINUATION}]+
      | \.[0-9](?:[{_NUMERIC_GUARD_CHARACTERS}]|[^\x00-\x7F\s])*)
"""
_UNSUPPORTED_RANGE_PATTERN = rf"""
    {_NUMBER_PATTERN}{_HSPACE}{_RANGE_SEPARATOR}{_HSPACE}{_NUMBER_PATTERN}
    {_HSPACE}[A-Za-z%％°℃㎡㎥μµ가-힣²³]+
"""
_UNSUPPORTED_COMPARISON_PATTERN = rf"""
    /?[A-Za-z][A-Za-z0-9_.-]*{_HSPACE}[<>≤≥=]{_HSPACE}{_NUMBER_PATTERN}
    (?:{_HSPACE}(?:{_UNIT_PATTERN}|%[pP]|%|％))?
"""
_NON_ASCII_NUMERIC_CLUSTER_PATTERN = rf"""
    (?:[0-9]+[^\x00-\x7F\s]
      | [^\x00-\x7F\s][0-9])
    (?:[{_NUMERIC_GUARD_CHARACTERS}]|[^\x00-\x7F\s])*
"""
_MIXED_ACRONYM_NUMERIC_CONTEXT_PATTERN = rf"""
    (?:{_ACRONYM_PATTERN}[가-힣]+[0-9]
        (?:[{_NUMERIC_GUARD_CHARACTERS}]|[^\x00-\x7F\s])*
      | {_ACRONYM_PATTERN}[{_NUMERIC_SINGLE_PREFIX}{_NUMERIC_STRONG_PREFIX}]+[0-9]
        [{_NUMERIC_GUARD_CHARACTERS}]*[ㄱ-ㅎㅏ-ㅣ])
"""

# 기본 스캐너와 공백 없는 결합 토큰 재분류기가 공유하는 실제 문법이다.
# 삽입 순서가 더 구체적인 형식에서 일반 숫자 순서로 이어지는 우선순위다.
_SEMANTIC_TOKEN_PATTERNS = {
    "phone": _PHONE_EXPRESSION,
    "time": rf"(?:{_COLON_TIME_PATTERN}|{_KOREAN_TIME_PATTERN})",
    "korean_date": _KOREAN_DATE_PATTERN,
    "date": _DATE_PATTERN,
    "history": _HISTORY_PATTERN,
    "currency": _CURRENCY_PATTERN,
    "scaled_currency": _SCALED_CURRENCY_PATTERN,
    "scaled_quantity": _SCALED_QUANTITY_PATTERN,
    "nights_days": _NIGHTS_DAYS_PATTERN,
    "range": (
        rf"{_NUMBER_PATTERN}{_HSPACE}{_RANGE_SEPARATOR}{_HSPACE}{_NUMBER_PATTERN}"
        rf"(?:{_HSPACE}{_RANGE_UNIT_PATTERN}(?:{_KOREAN_SUFFIX_PATTERN})?)?"
    ),
    "ambiguous_hyphen": (
        rf"{_UNSIGNED_NUMBER_PATTERN}{_HSPACE}-{_HSPACE}{_UNSIGNED_NUMBER_PATTERN}"
        rf"(?:{_HSPACE}{_UNIT_PATTERN})?"
    ),
    "exponent": rf"{_UNSIGNED_NUMBER_PATTERN}\^(?:[-−])?[0-9]+",
    "fraction_unit": _FRACTION_UNIT_PATTERN,
    "fraction": rf"{_UNSIGNED_NUMBER_PATTERN}/{_UNSIGNED_NUMBER_PATTERN}",
    "percentage": rf"{_NUMBER_PATTERN}{_HSPACE}(?:%[pP]|%|％)",
    "month": _MONTH_PATTERN,
    "number_hangul_unit": (
        rf"{_NUMBER_PATTERN}{_HSPACE}{_HANGUL_UNIT_PATTERN}[가-힣]*"
    ),
    "number_unit": _NUMBER_UNIT_PATTERN,
    "decimal": _DECIMAL_PATTERN,
    "number": _NUMBER_PATTERN,
}

_BASE_TOKEN_PATTERN = rf"""
    (?P<contextual_short_date>(?<![A-Za-z0-9가-힣]){_CONTEXTUAL_SHORT_DATE_PATTERN}(?![A-Za-z0-9가-힣/]|\.[0-9]))
  | (?P<contextual_identifier>(?<![A-Za-z0-9가-힣]){_IDENTIFIER_LABEL_PATTERN}{_HSPACE}(?:[:#]{_HSPACE})?{_IDENTIFIER_BODY_PATTERN}(?![A-Za-z0-9]))
  | (?P<unsupported_comparison>(?<![A-Za-z0-9]){_UNSUPPORTED_COMPARISON_PATTERN}(?![{_STRUCTURED_TOKEN_CONTINUATION}]|[.,][0-9]))
  | (?P<date_range>(?<![A-Za-z0-9가-힣]){_DATE_RANGE_OPERAND_PATTERN}{_HSPACE}{_RANGE_SEPARATOR}{_HSPACE}{_DATE_RANGE_OPERAND_PATTERN}(?![{_STRUCTURED_TOKEN_CONTINUATION}]))
  | (?P<mixed_fraction>(?<![A-Za-z0-9]){_MIXED_FRACTION_PATTERN}(?![{_STRUCTURED_TOKEN_CONTINUATION}]))
  | (?P<range_both>{_ASCII_IDENTIFIER_LEFT_BOUNDARY}{_NUMBER_PATTERN}{_HSPACE}{_RANGE_BOTH_UNIT_PATTERN}{_HSPACE}{_RANGE_SEPARATOR}{_HSPACE}{_NUMBER_PATTERN}{_HSPACE}{_RANGE_BOTH_UNIT_PATTERN}(?:{_KOREAN_SUFFIX_PATTERN})?(?![{_STRUCTURED_TOKEN_CONTINUATION}]|\.[0-9]){_DOTTED_IDENTIFIER_RIGHT_GUARD})
  | (?P<time_range>(?<![A-Za-z0-9가-힣]){_TIME_RANGE_SCAN_PATTERN}(?![{_STRUCTURED_TOKEN_CONTINUATION}]))
  | (?P<unsupported_semantic_pair>(?<![A-Za-z0-9]){_SEMANTIC_PAIR_PATTERN}(?![A-Za-z0-9가-힣._/+−-]))
  | (?P<mixed_currency>(?<![A-Za-z0-9]){_MIXED_CURRENCY_PATTERN}(?![{_STRUCTURED_TOKEN_CONTINUATION}]|[.,][0-9]))
  | (?P<mixed_numeric_context>{_ASCII_IDENTIFIER_LEFT_BOUNDARY}{_MIXED_ACRONYM_NUMERIC_CONTEXT_PATTERN}(?![A-Za-z0-9_가-힣]){_DOTTED_IDENTIFIER_RIGHT_GUARD})
  | (?P<version>(?<![A-Za-z0-9])[vV][0-9]+(?:\.[0-9]+){{1,}}(?![A-Za-z0-9]))
  | (?P<filename>(?<![A-Za-z0-9_.-])[A-Za-z0-9_-]+\.{_KNOWN_EXTENSIONS}(?![A-Za-z0-9_.-]))
  | (?P<phone>(?<![A-Za-z0-9._/+\-]){_SEMANTIC_TOKEN_PATTERNS["phone"]}(?![{_STRUCTURED_TOKEN_CONTINUATION}]|\.[0-9]))
  | (?P<malformed_phone>(?<![A-Za-z0-9._/+\-]){_MALFORMED_PHONE_PATTERN}[가-힣]*(?![{_STRUCTURED_TOKEN_CONTINUATION}]|\.[0-9]))
  | (?P<emergency>(?<![A-Za-z0-9]){_EMERGENCY_PATTERN}(?![{_STRUCTURED_TOKEN_CONTINUATION}]))
  | (?P<ipv4>(?<![0-9._/-])(?:[0-9]{{1,3}}\.){{3}}[0-9]{{1,3}}(?![{_STRUCTURED_TOKEN_CONTINUATION}]|\.[0-9]))
  | (?P<time>(?<![A-Za-z0-9가-힣]){_SEMANTIC_TOKEN_PATTERNS["time"]}(?![{_STRUCTURED_TOKEN_CONTINUATION}]|\.[0-9]))
  | (?P<korean_date>(?<![A-Za-z0-9가-힣]){_SEMANTIC_TOKEN_PATTERNS["korean_date"]}(?![{_STRUCTURED_TOKEN_CONTINUATION}]))
  | (?P<date>(?<![A-Za-z0-9]){_SEMANTIC_TOKEN_PATTERNS["date"]}(?![{_STRUCTURED_TOKEN_CONTINUATION}]|\.[0-9]))
  | (?P<month_day>(?<![A-Za-z0-9가-힣]){_MONTH_DAY_PATTERN}(?![{_STRUCTURED_TOKEN_CONTINUATION}]))
  | (?P<year_month>(?<![A-Za-z0-9가-힣]){_YEAR_MONTH_PATTERN}(?![{_STRUCTURED_TOKEN_CONTINUATION}]))
  | (?P<malformed_structured>(?<![A-Za-z0-9]){_MALFORMED_STRUCTURED_PATTERN}(?![{_STRUCTURED_TOKEN_CONTINUATION}.]))
  | (?P<ordinal>(?<![A-Za-z0-9가-힣])제{_HSPACE}{_NUMBER_PATTERN}{_HSPACE}{_HANGUL_UNIT_PATTERN}[가-힣]*)
  | (?P<numbered_item>(?<![A-Za-z0-9]){_NUMBER_PATTERN}{_HSPACE}번(?=[ \t]+(?:출구|버스|문제|문항|노선|좌석|채널)))
  | (?P<history>(?<![0-9]){_SEMANTIC_TOKEN_PATTERNS["history"]})
  | (?P<nights_days>{_ASCII_IDENTIFIER_LEFT_BOUNDARY}{_NIGHTS_DAYS_PATTERN}(?![{_QUANTITY_CONTINUATION}]|[.,][0-9]){_DOTTED_IDENTIFIER_RIGHT_GUARD})
  | (?P<currency>(?<![A-Za-z0-9]){_SEMANTIC_TOKEN_PATTERNS["currency"]}(?![{_NUMERIC_GUARD_CHARACTERS}가-힣]))
  | (?P<iso_currency>(?<![A-Za-z0-9]){_ISO_CURRENCY_EXPRESSION}(?![{_NUMERIC_GUARD_CHARACTERS}가-힣]))
  | (?P<scaled_currency>(?<![A-Za-z0-9]){_SEMANTIC_TOKEN_PATTERNS["scaled_currency"]}(?:{_KOREAN_SUFFIX_PATTERN})?(?![{_NUMERIC_GUARD_CHARACTERS}가-힣]))
  | (?P<scaled_quantity>{_ASCII_IDENTIFIER_LEFT_BOUNDARY}{_SCALED_QUANTITY_PATTERN}(?![{_QUANTITY_CONTINUATION}]|[.,][0-9]){_DOTTED_IDENTIFIER_RIGHT_GUARD})
  | (?P<unsupported_math>(?<![A-Za-z0-9]){_NUMBER_PATTERN}(?:(?:[ \t]+{_MATH_OPERATOR_PATTERN}{_HSPACE}|{_HSPACE}{_MATH_OPERATOR_PATTERN}[ \t]+)|[ \t]+[-−][ \t]+){_NUMBER_PATTERN}(?![A-Za-z0-9._/+−-]))
  | (?P<scaled_range>(?<![A-Za-z0-9]){_NUMBER_PATTERN}{_HSPACE}{_SCALE_PATTERN}{_HSPACE}{_RANGE_SEPARATOR}{_HSPACE}{_NUMBER_PATTERN}{_HSPACE}{_SCALE_PATTERN}{_HSPACE}원(?:{_KOREAN_SUFFIX_PATTERN})?(?![A-Za-z0-9가-힣]))
  | (?P<range>{_ASCII_IDENTIFIER_LEFT_BOUNDARY}{_SEMANTIC_TOKEN_PATTERNS["range"]}(?![{_STRUCTURED_TOKEN_CONTINUATION}]|\.[0-9]){_DOTTED_IDENTIFIER_RIGHT_GUARD})
  | (?P<unsupported_range>(?<![A-Za-z0-9]){_UNSUPPORTED_RANGE_PATTERN}(?![{_STRUCTURED_TOKEN_CONTINUATION}]|[.,][0-9]))
  | (?P<standalone_unit_symbol>{_ASCII_IDENTIFIER_LEFT_BOUNDARY}{_STANDALONE_UNIT_SYMBOL_EXPRESSION}(?![A-Za-z0-9_가-힣]){_DOTTED_IDENTIFIER_RIGHT_GUARD})
  | (?P<quantity_unit>{_ASCII_IDENTIFIER_LEFT_BOUNDARY}{_QUANTITY_UNIT_PATTERN}(?![{_QUANTITY_CONTINUATION}]|[.,][0-9]){_DOTTED_IDENTIFIER_RIGHT_GUARD})
  | (?P<mixed_numeric_suffix>(?<![A-Za-z0-9]){_MIXED_SUFFIX_PATTERN}(?![A-Za-z0-9가-힣]))
  | (?P<semantic_cluster>(?<![A-Za-z0-9]){_SEMANTIC_CLUSTER_PATTERN}(?![A-Za-z0-9가-힣]))
  | (?P<non_ascii_decimal>(?<![0-9])(?=[^0-9])\d+(?:{_HSPACE}{_UNIT_PATTERN})?(?![0-9]))
  | (?P<exponent>(?<![A-Za-z0-9]){_SEMANTIC_TOKEN_PATTERNS["exponent"]}(?![A-Za-z0-9가-힣]))
  | (?P<fraction>(?<![A-Za-z0-9]){_SEMANTIC_TOKEN_PATTERNS["fraction"]}(?![A-Za-z0-9./]))
  | (?P<percentage>(?<![A-Za-z0-9]){_SEMANTIC_TOKEN_PATTERNS["percentage"]}(?![A-Za-z0-9%]))
  | (?P<number_hangul_unit>{_ASCII_IDENTIFIER_LEFT_BOUNDARY}{_SEMANTIC_TOKEN_PATTERNS["number_hangul_unit"]}(?![A-Za-z0-9_]){_DOTTED_IDENTIFIER_RIGHT_GUARD})
  | (?P<number_suffix>(?<![A-Za-z0-9]){_NUMBER_PATTERN}{_KOREAN_SUFFIX_PATTERN}(?![A-Za-z0-9가-힣]))
  | (?P<decimal>(?<![A-Za-z0-9]){_SEMANTIC_TOKEN_PATTERNS["decimal"]}(?![A-Za-z0-9.,:/+^~～∼–—×±÷=*<>≤≥%％²³\-]))
  | (?P<unsupported_prefixed_numeric>(?<![A-Za-z0-9])[\$₩€£¥]{_HSPACE}[0-9][{_NUMERIC_GUARD_CHARACTERS}]*[가-힣]*)
  | (?P<unsupported_numeric>(?<![A-Za-z0-9])(?:
        [+\-−]?\.[0-9]+
      | {_NUMBER_PATTERN}[eE][+\-]?[0-9]+
      | {_NUMBER_PATTERN}{_HSPACE}[\$₩€£¥]
      | [-−]{_UNSIGNED_NUMBER_PATTERN}/{_UNSIGNED_NUMBER_PATTERN}
      | {_UNSIGNED_NUMBER_PATTERN}\^(?:[-−])?[0-9]+{_HSPACE}{_UNIT_PATTERN}
      | {_NUMBER_PATTERN}{_HSPACE}{_UNIT_PATTERN}/[A-Za-z]+
      | {_NUMBER_PATTERN}{_HSPACE}{_UNIT_PATTERN}[²³]
      | {_NUMBER_PATTERN}{_HSPACE}[×±]{_HSPACE}{_NUMBER_PATTERN}(?:{_HSPACE}{_UNIT_PATTERN})?
    )(?![A-Za-z0-9]))
  | (?P<ambiguous_hyphen>(?<![0-9]){_SEMANTIC_TOKEN_PATTERNS["ambiguous_hyphen"]}(?![A-Za-z0-9._/+−-]))
  | (?P<number_punctuation>(?<![A-Za-z0-9]){_NUMBER_PATTERN}[.,](?![0-9.,]))
  | (?P<numeric_guard>(?<![A-Za-z0-9])(?=[0-9][{_NUMERIC_GUARD_CHARACTERS}]*[{_NUMERIC_GUARD_SIGNAL}])[0-9][{_NUMERIC_GUARD_CHARACTERS}]*[가-힣]*)
  | (?P<non_ascii_numeric_cluster>(?<![A-Za-z0-9]){_NON_ASCII_NUMERIC_CLUSTER_PATTERN}(?![A-Za-z0-9]))
  | (?P<ambiguous_numeric>(?<![A-Za-z0-9])[0-9]{{11,}}(?![0-9]))
  | (?P<ambiguous_number_word>(?<![A-Za-z0-9]){_NUMBER_PATTERN}[가-힣]+(?![A-Za-z0-9가-힣]))
  | (?P<ambiguous_latin_hyphen>(?<![A-Za-z])[A-Za-z]+[-‑][A-Za-z]+(?![A-Za-z]))
  | (?P<ambiguous_identifier>(?<![A-Za-z0-9])(?:[A-Za-z][A-Za-z0-9_.-]*[0-9][A-Za-z0-9_.-]*|[+\-.]?[0-9]+[A-Za-z][A-Za-z0-9_.-]*)(?![A-Za-z0-9]))
  | (?P<number>(?<![A-Za-z0-9]){_SEMANTIC_TOKEN_PATTERNS["number"]}(?![A-Za-z0-9가-힣]))
  | (?P<indefinite_unit>(?<![A-Za-z0-9_가-힣])(?<![A-Za-z0-9_]\.){_INDEFINITE_UNIT_PATTERN}(?![A-Za-z0-9_]){_DOTTED_IDENTIFIER_RIGHT_GUARD})
  | (?P<unit_per>{_ASCII_IDENTIFIER_LEFT_BOUNDARY}{_UNIT_PER_PATTERN}(?![A-Za-z0-9_가-힣]){_DOTTED_IDENTIFIER_RIGHT_GUARD})
  | (?P<acronym>{_ASCII_IDENTIFIER_LEFT_BOUNDARY}{_ACRONYM_PATTERN}{_ASCII_IDENTIFIER_RIGHT_BOUNDARY})
  | (?P<jamo_cluster>[ㄱ-ㅎ]{{2,}}[A-Za-z0-9]*)
  | (?P<jamo>[ㄱ-ㅎ])
  | (?P<han>[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]+)
  | (?P<latin>(?<![A-Za-z])[A-Za-z]+(?:['’][A-Za-z]+)?(?![A-Za-z]))
  | (?P<unsupported_symbol>[\$₩€£¥%％×±²³⁴=÷^≤≥*<>∼])
"""
_BASE_TOKEN_RE = re.compile(_BASE_TOKEN_PATTERN, re.VERBOSE)

# 공백 없는 숫자 결합 토큰도 위와 같은 문법과 우선순위를 사용한다.
_SEMANTIC_TOKEN_RE = re.compile(
    "(?:"
    + "|".join(
        rf"(?P<{kind}>{pattern})"
        for kind, pattern in _SEMANTIC_TOKEN_PATTERNS.items()
    )
    + ")",
    re.VERBOSE,
)
_PHONE_RE = re.compile(
    rf"(?P<number>{_PHONE_PATTERN})(?P<suffix>{_KOREAN_SUFFIX_PATTERN})?"
)
_EMERGENCY_RE = re.compile(
    rf"(?P<number>112|119)(?P<suffix>{_KOREAN_SUFFIX_PATTERN})?"
)
_DECIMAL_RE = re.compile(_DECIMAL_PATTERN)
_RANGE_RE = re.compile(
    rf"(?P<left>{_NUMBER_PATTERN}){_HSPACE}{_RANGE_SEPARATOR}{_HSPACE}"
    rf"(?P<right>{_NUMBER_PATTERN})(?:{_HSPACE}(?P<unit>{_RANGE_UNIT_PATTERN})"
    rf"(?P<suffix>{_KOREAN_SUFFIX_PATTERN})?)?"
)
_RANGE_BOTH_RE = re.compile(
    rf"(?P<left>{_NUMBER_PATTERN}){_HSPACE}(?P<left_unit>{_RANGE_BOTH_UNIT_PATTERN})"
    rf"{_HSPACE}{_RANGE_SEPARATOR}{_HSPACE}"
    rf"(?P<right>{_NUMBER_PATTERN}){_HSPACE}(?P<unit>{_RANGE_BOTH_UNIT_PATTERN})"
    rf"(?P<suffix>{_KOREAN_SUFFIX_PATTERN})?"
)
_SCALED_RANGE_RE = re.compile(
    rf"(?P<left>{_NUMBER_PATTERN}){_HSPACE}(?P<left_scale>{_SCALE_PATTERN}){_HSPACE}{_RANGE_SEPARATOR}{_HSPACE}"
    rf"(?P<right>{_NUMBER_PATTERN}){_HSPACE}(?P<right_scale>{_SCALE_PATTERN}){_HSPACE}원"
    rf"(?P<suffix>{_KOREAN_SUFFIX_PATTERN})?"
)
_QUANTITY_UNIT_RE = re.compile(
    rf"(?:"
    rf"(?P<numerator>{_UNSIGNED_NUMBER_PATTERN})/"
    rf"(?P<denominator>{_UNSIGNED_NUMBER_PATTERN})"
    rf"|(?P<number>{_NUMBER_PATTERN})(?:{_HSPACE}(?P<scale>{_SCALE_PATTERN}))?"
    rf"{_HSPACE}(?P<approximation>여)?"
    rf"){_HSPACE}(?P<unit>{_WRITTEN_UNIT_PATTERN})"
)
_INDEFINITE_UNIT_RE = re.compile(
    rf"(?P<quantifier>몇|수){_HSPACE}(?P<unit>{_WRITTEN_UNIT_PATTERN})"
)
_UNIT_PER_RE = re.compile(
    rf"(?P<unit>{_WRITTEN_UNIT_PATTERN})당(?P<suffix>{_KOREAN_SUFFIX_PATTERN})?"
)
_STANDALONE_UNIT_SYMBOL_RE = re.compile(
    rf"(?P<unit>{_STANDALONE_UNIT_SYMBOL_PATTERN})"
    rf"(?P<suffix>{_KOREAN_SUFFIX_PATTERN})?"
)
_NUMBER_HANGUL_UNIT_RE = re.compile(
    rf"(?P<number>{_NUMBER_PATTERN}){_HSPACE}(?P<word>{_HANGUL_UNIT_PATTERN}[가-힣]*)"
)
_FRACTION_RE = re.compile(
    rf"(?P<numerator>{_UNSIGNED_NUMBER_PATTERN})/"
    rf"(?P<denominator>{_UNSIGNED_NUMBER_PATTERN})"
)
_PERCENT_RE = re.compile(rf"(?P<number>{_NUMBER_PATTERN}){_HSPACE}(?P<unit>%[pP]|%|％)")
_DATE_RE = re.compile(
    rf"(?P<year>[0-9]{{4}}){_HSPACE}(?P<separator>[-./]){_HSPACE}"
    rf"(?P<month>[0-9]{{1,2}}){_HSPACE}(?P=separator){_HSPACE}"
    rf"(?P<day>[0-9]{{1,2}})(?:\.?(?P<suffix>{_KOREAN_SUFFIX_PATTERN}))?"
)
_MONTH_DAY_RE = re.compile(
    rf"(?P<month>[0-9]{{1,2}}){_HSPACE}월{_HSPACE}"
    rf"(?P<day>[0-9]{{1,2}}){_HSPACE}일(?P<suffix>{_KOREAN_SUFFIX_PATTERN})?"
)
_MONTH_RE = re.compile(
    rf"(?P<month>[0-9]{{1,2}}){_HSPACE}월(?P<suffix>{_KOREAN_SUFFIX_PATTERN})?"
)
_YEAR_MONTH_RE = re.compile(
    rf"(?P<year>[0-9]{{4}}){_HSPACE}년"
    rf"(?:{_HSPACE}(?P<month>[0-9]{{1,2}}){_HSPACE}월)?"
    rf"(?P<suffix>{_KOREAN_SUFFIX_PATTERN})?"
)
_KOREAN_DATE_RE = re.compile(
    rf"(?P<year>[0-9]{{4}}){_HSPACE}년{_HSPACE}(?P<month>[0-9]{{1,2}})"
    rf"{_HSPACE}월{_HSPACE}(?P<day>[0-9]{{1,2}}){_HSPACE}일"
    rf"(?P<suffix>{_KOREAN_SUFFIX_PATTERN})?"
)
_COLON_TIME_RE = re.compile(
    rf"(?:(?P<period>오전|오후){_HSPACE})?(?P<hour>[0-9]{{1,2}}):"
    rf"(?P<minute>[0-9]{{2}})(?::(?P<second>[0-9]{{2}}))?"
    rf"(?P<suffix>{_KOREAN_SUFFIX_PATTERN})?"
)
_KOREAN_TIME_RE = re.compile(
    rf"(?:(?P<period>오전|오후){_HSPACE})?(?P<hour>[0-9]{{1,2}}){_HSPACE}시"
    rf"(?:{_HSPACE}(?P<minute>[0-9]{{1,2}}){_HSPACE}분"
    rf"(?:{_HSPACE}(?P<second>[0-9]{{1,2}}){_HSPACE}초)?)?"
    rf"(?P<suffix>{_KOREAN_SUFFIX_PATTERN})?"
)
_TIME_RANGE_RE = re.compile(_TIME_RANGE_PATTERN, re.VERBOSE)
_CURRENCY_RE = re.compile(
    rf"(?P<symbol>[\$₩€£¥]){_HSPACE}(?P<number>{_NUMBER_PATTERN})"
    rf"(?:{_HSPACE}(?P<spoken_unit>{_CURRENCY_WORD_PATTERN}))?"
)
_ISO_CURRENCY_RE = re.compile(
    rf"(?:(?P<prefix>{_ISO_CURRENCY_PATTERN}){_HSPACE}(?P<prefix_number>{_NUMBER_PATTERN})"
    rf"|(?P<suffix_number>{_NUMBER_PATTERN}){_HSPACE}(?P<suffix>{_ISO_CURRENCY_PATTERN}))"
    rf"(?:{_HSPACE}(?P<spoken_unit>{_CURRENCY_WORD_PATTERN}))?"
)
_SCALED_CURRENCY_RE = re.compile(
    rf"(?P<number>{_NUMBER_PATTERN}){_HSPACE}(?P<scale>{_SCALE_PATTERN}){_HSPACE}원"
    rf"(?P<suffix>{_KOREAN_SUFFIX_PATTERN})?"
)
_SCALED_QUANTITY_RE = re.compile(
    rf"(?P<body>{_SCALED_NUMBER_PATTERN}){_HSPACE}"
    rf"(?P<approximation>여)?{_HSPACE}(?P<word>{_UNIT_PATTERN}[가-힣]*)"
)
_SCALED_COMPONENT_RE = re.compile(
    rf"(?P<number>{_NUMBER_PATTERN}){_HSPACE}(?P<small>[십백천])?"
    rf"{_HSPACE}(?P<large>[만억조])?"
)
_NIGHTS_DAYS_RE = re.compile(
    rf"(?P<nights>{_NUMBER_PATTERN}){_HSPACE}박{_HSPACE}"
    rf"(?P<days>{_NUMBER_PATTERN}){_HSPACE}일(?P<suffix>[가-힣]*)"
)
_ORDINAL_RE = re.compile(rf"제{_HSPACE}(?P<body>{_NUMBER_PATTERN}{_HSPACE}{_HANGUL_UNIT_PATTERN}[가-힣]*)")
_NUMBER_SUFFIX_RE = re.compile(
    rf"(?P<number>{_NUMBER_PATTERN})(?P<suffix>{_KOREAN_SUFFIX_PATTERN})"
)
_EXPONENT_RE = re.compile(
    rf"(?P<base>{_UNSIGNED_NUMBER_PATTERN})\^(?P<exponent>[-−]?[0-9]+)"
)
_POLICIES = frozenset({"preserve", "warn", "error"})

_UNSUPPORTED_NUMERIC_KINDS = frozenset(
    {
        "unsupported_numeric",
        "unsupported_prefixed_numeric",
        "unsupported_math",
        "unsupported_semantic_pair",
        "malformed_phone",
        "malformed_structured",
        "mixed_currency",
        "unsupported_range",
        "unsupported_comparison",
        "non_ascii_numeric_cluster",
    }
)
_AMBIGUOUS_TOKEN_MESSAGES = {
    "contextual_identifier": (
        "ambiguous_numeric",
        "문맥상 식별번호인 숫자는 수량으로 읽지 않습니다.",
    ),
    "contextual_short_date": (
        "ambiguous_numeric",
        "연도가 없는 날짜 표기의 월·일 순서를 확정할 수 없습니다.",
    ),
    "non_ascii_decimal": (
        "ambiguous_numeric",
        "ASCII가 아닌 숫자의 읽기를 확정할 수 없습니다.",
    ),
    "mixed_numeric_suffix": (
        "ambiguous_identifier",
        "숫자 뒤에 문자 체계가 혼합된 토큰은 전체 원문을 보존합니다.",
    ),
    "mixed_numeric_context": (
        "ambiguous_identifier",
        "숫자 뒤에 문자 체계가 혼합된 토큰은 전체 원문을 보존합니다.",
    ),
    "ambiguous_hyphen": (
        "ambiguous_hyphen",
        "하이픈이 범위인지 식별자인지 확정할 수 없습니다.",
    ),
    "ambiguous_latin_hyphen": (
        "unconverted_latin",
        "하이픈 영문 표현의 관용 읽기를 확정할 수 없습니다.",
    ),
    "ambiguous_identifier": (
        "ambiguous_identifier",
        "영숫자 식별자의 의도한 읽기를 확정할 수 없습니다.",
    ),
    "ambiguous_numeric": (
        "ambiguous_numeric",
        "긴 숫자가 식별번호인지 수량인지 확정할 수 없습니다.",
    ),
    "ambiguous_number_word": (
        "ambiguous_numeric",
        "숫자 뒤 표기가 조사인지 낱말인지 확정할 수 없습니다.",
    ),
    "date_range": (
        "ambiguous_numeric",
        "날짜 범위 읽기는 지원하지 않아 원문을 보존합니다.",
    ),
    "mixed_fraction": (
        "ambiguous_numeric",
        "대분수 읽기는 지원하지 않아 원문을 보존합니다.",
    ),
    "jamo_cluster": (
        "unsupported_script",
        "연속된 자모는 웃음 표기나 초성어일 수 있어 원문을 보존합니다.",
    ),
    "han": (
        "unconverted_han",
        "한자의 문맥상 한국어 읽기를 확정할 수 없습니다.",
    ),
    "latin": (
        "unconverted_latin",
        "영문 고유명사의 관용 읽기를 확정할 수 없습니다.",
    ),
    "unsupported_symbol": (
        "unsupported_symbol",
        "발화 규칙이 없는 의미 기호는 원문을 보존합니다.",
    ),
}
_SIMPLE_RENDER_METHODS = {
    "phone": "_render_phone",
    "emergency": "_render_emergency",
    "time": "_render_time",
    "time_range": "_render_time_range",
    "ordinal": "_render_ordinal",
    "history": "_render_history",
    "currency": "_render_currency",
    "iso_currency": "_render_iso_currency",
    "scaled_currency": "_render_scaled_currency",
    "acronym": "_render_acronym",
}
