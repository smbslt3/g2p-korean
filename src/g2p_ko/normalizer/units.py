"""수량사와 단위의 표면형 및 발화형을 정의한다."""

from __future__ import annotations

import re

from .conventional_english import CONVENTIONAL_READINGS, INITIALISMS

_NATIVE_COUNTERS = frozenset(
    {
        "개",
        "명",
        "사람",
        "마리",
        "번째",
        "시",
        "배",
        "가구",
        "게임",
        "건",
        "세트",
        "가지",
        "개비",
        "잔",
        "번",
        "장",
        "병",
        "권",
        "벌",
        "곳",
        "시간",
        "척",
        "차례",
        "바퀴",
        "경기",
        "골",
        "살",
        "달",
        "글자",
        "알",
        "켤레",
        "송이",
        "컵",
        "쪽",
        "채",
        "자루",
        "그루",
        "포기",
        "칸",
        "자리",
    }
)
# 칸과 자리는 수량을 세는 표기다. 새 단위 자질이 없는 과거 모델의
# 일반 한자어 점수가 이 명확한 기본값을 덮어쓰지 않게 한다.
_CONTEXT_INDEPENDENT_NATIVE_COUNTERS = frozenset({"칸", "자리"})
_UNIT_READINGS = {
    "km/h": "킬로미터 퍼 아워",
    "㎞/h": "킬로미터 퍼 아워",
    "m/s": "미터 퍼 세컨드",
    "km/s": "킬로미터 퍼 세컨드",
    "MB/s": "메가바이트 퍼 세컨드",
    "GB/s": "기가바이트 퍼 세컨드",
    "W/kg": "와트 퍼 킬로그램",
    "km/l": "킬로미터 퍼 리터",
    "kg": "킬로그램",
    "g/mL": "그램 퍼 밀리리터",
    "g/ml": "그램 퍼 밀리리터",
    "mg": "밀리그램",
    "g": "그램",
    "t": "톤",
    "mL": "밀리리터",
    "ml": "밀리리터",
    "L": "리터",
    "l": "리터",
    "cm": "센티미터",
    "mm": "밀리미터",
    "km": "킬로미터",
    "m": "미터",
    "mi": "마일",
    "mile": "마일",
    "ha": "헥타르",
    "ℓ": "리터",
    "nm": "나노미터",
    "μm": "마이크로미터",
    "µm": "마이크로미터",
    "m²": "제곱미터",
    "cm²": "제곱센티미터",
    "km²": "제곱킬로미터",
    "㎢": "제곱킬로미터",
    "m³": "세제곱미터",
    "cm³": "세제곱센티미터",
    "km³": "세제곱킬로미터",
    "㎡": "제곱미터",
    "㎥": "세제곱미터",
    "cc": "씨씨",
    "kcal": "킬로칼로리",
    "cal": "칼로리",
    "kJ": "킬로줄",
    "mmHg": "수은주밀리미터",
    "Hz": "헤르츠",
    "kHz": "킬로헤르츠",
    "MHz": "메가헤르츠",
    "GHz": "기가헤르츠",
    "W": "와트",
    "kW": "킬로와트",
    "MW": "메가와트",
    "Wh": "와트시",
    "kWh": "킬로와트시",
    "GWh": "기가와트시",
    "V": "볼트",
    "mV": "밀리볼트",
    "mA": "밀리암페어",
    "mAh": "밀리암페어시",
    "dB": "데시벨",
    "bpm": "비피엠",
    "rpm": "알피엠",
    "TEU": "티이유",
    "FEU": "에프이유",
    "ppm": "피피엠",
    "dpi": "디피아이",
    "KB": "킬로바이트",
    "MB": "메가바이트",
    "GB": "기가바이트",
    "TB": "테라바이트",
    "°C": "도씨",
    "°c": "도씨",
    "℃": "도씨",
    "㎏": "킬로그램",
    "㎎": "밀리그램",
    "㎖": "밀리리터",
    "㎞": "킬로미터",
    "㎝": "센티미터",
    "㎜": "밀리미터",
    "㎾h": "킬로와트시",
    "㎿": "메가와트",
}

# 이동 속도만 한국어 관용 어순으로 전치한다. 같은 슬래시 표기라도 전송률이나
# 단위 질량당 값은 `_UNIT_READINGS`의 "퍼" 읽기를 그대로 사용한다.
_SPEED_UNIT_READINGS = {
    "km/h": ("시속", "킬로미터"),
    "㎞/h": ("시속", "킬로미터"),
    "m/s": ("초속", "미터"),
    "km/s": ("초속", "킬로미터"),
}

# 문자 자체가 단위 전용이라 일반 영문 약어와 충돌하지 않는 표기만 독립적으로
# 읽는다. ASCII 단위는 숫자·수량사·`당` 문맥이 없으면 보존한다.
_STANDALONE_UNIT_SYMBOLS = frozenset(
    {
        "ℓ",
        "°C",
        "°c",
        "℃",
        "㎡",
        "㎥",
        "㎏",
        "㎎",
        "㎖",
        "㎞",
        "㎝",
        "㎜",
        "㎢",
        "㎾h",
        "㎿",
    }
)
# 이동 속도 표기와 단위 전용 유니코드 기호는 식별자와 겹치지 않으므로
# 숫자를 언제나 한자어 수사로 읽는다. 통화도 금액이라는 의미가 확정되므로
# 자릿수 읽기로 바꾸지 않는다. 문맥 판별기에 보낼 이유가 없다.
_CONTEXT_INDEPENDENT_SINO_UNITS = (
    frozenset(_SPEED_UNIT_READINGS)
    | _STANDALONE_UNIT_SYMBOLS
    | frozenset(
        {
            "호실",
            "동",
            "단계",
            "종",
            "호선",
            "원",
            "달러",
            "유로",
            "엔",
            "파운드",
            "위안",
        }
    )
)
_SINO_UNITS = frozenset(
    {
        "초",
        "분",
        "일",
        "주",
        "개월",
        "월",
        "년",
        "점",
        "포인트",
        "퍼센트",
        "레벨",
        "점수",
        "등급",
        "등",
        "원",
        "달러",
        "유로",
        "엔",
        "파운드",
        "회",
        "차",
        "기",
        "호",
        "페이지",
        "도",
        "층",
        "학년",
        "학기",
        "학점",
        "교시",
        "세기",
        "라운드",
        "세",
        "차원",
        "위안",
        "호실",
        "동",
        "단계",
        "종",
        "박",
        "호선",
    }
)
# 이미 발화형으로 쓰는 단위의 한글 표기는 원문에서도 같은 단위로 인식한다.
# 인식 어휘를 발화 어휘와 같게 묶어 새 읽기를 도입하지 않으며, 여러 낱말로
# 읽는 단위(`km/h` → 킬로미터 퍼 아워)와 다른 뜻의 낱말과 표기가 겹치는
# `톤`(색·음의 단계는 두 톤처럼 고유어로 센다)은 제외한다.
_HANGUL_SPELLED_UNITS = frozenset(
    reading for reading in _UNIT_READINGS.values() if " " not in reading
) - {"톤"}
_ALL_UNITS = tuple(
    sorted(
        _NATIVE_COUNTERS | _SINO_UNITS | _HANGUL_SPELLED_UNITS | set(_UNIT_READINGS),
        key=lambda item: (-len(item), item),
    )
)
_UNIT_PATTERN = "(?:" + "|".join(re.escape(item) for item in _ALL_UNITS) + ")"
_WRITTEN_UNIT_PATTERN = "(?:" + "|".join(
    re.escape(item)
    for item in sorted(_UNIT_READINGS, key=lambda item: (-len(item), item))
) + ")"
_WRITTEN_UNIT_INITIAL_PATTERN = "[" + re.escape(
    "".join(sorted({item[0] for item in _UNIT_READINGS}))
) + "]"
_STANDALONE_UNIT_SYMBOL_PATTERN = "(?:" + "|".join(
    re.escape(item)
    for item in sorted(_STANDALONE_UNIT_SYMBOLS, key=lambda item: (-len(item), item))
) + ")"
_HANGUL_UNITS = tuple(
    item
    for item in _ALL_UNITS
    if item in _NATIVE_COUNTERS or item in _SINO_UNITS or item in _HANGUL_SPELLED_UNITS
)
_HANGUL_UNIT_PATTERN = "(?:" + "|".join(re.escape(item) for item in _HANGUL_UNITS) + ")"
_NUMBER_PATTERN = r"[+\-−]?[0-9](?:[0-9,]*[0-9])?(?:\.[0-9]+)?"
_UNSIGNED_NUMBER_PATTERN = r"[0-9](?:[0-9,]*[0-9])?(?:\.[0-9]+)?"
_DECIMAL_PATTERN = r"[+\-−]?[0-9](?:[0-9,]*[0-9])?\.[0-9]+"

_SPOKEN_ACRONYMS = frozenset(INITIALISMS | set(CONVENTIONAL_READINGS))
_ACRONYM_PATTERN = (
    "(?:"
    + "|".join(
        re.escape(item)
        for item in sorted(_SPOKEN_ACRONYMS, key=lambda item: (-len(item), item))
    )
    + ")"
)
_JAMO_NAMES = {
    "ㄱ": "기역",
    "ㄲ": "쌍기역",
    "ㄳ": "기역시옷",
    "ㄴ": "니은",
    "ㄵ": "니은지읒",
    "ㄶ": "니은히읗",
    "ㄷ": "디귿",
    "ㄸ": "쌍디귿",
    "ㄹ": "리을",
    "ㄺ": "리을기역",
    "ㄻ": "리을미음",
    "ㄼ": "리을비읍",
    "ㄽ": "리을시옷",
    "ㄾ": "리을티읕",
    "ㄿ": "리을피읖",
    "ㅀ": "리을히읗",
    "ㅁ": "미음",
    "ㅂ": "비읍",
    "ㅃ": "쌍비읍",
    "ㅄ": "비읍시옷",
    "ㅅ": "시옷",
    "ㅆ": "쌍시옷",
    "ㅇ": "이응",
    "ㅈ": "지읒",
    "ㅉ": "쌍지읒",
    "ㅊ": "치읓",
    "ㅋ": "키읔",
    "ㅌ": "티읕",
    "ㅍ": "피읖",
    "ㅎ": "히읗",
}
_CURRENCIES = {"$": "달러", "₩": "원", "€": "유로", "£": "파운드", "¥": "엔"}
_ISO_CURRENCIES = {
    "KRW": "원",
    "USD": "달러",
    "EUR": "유로",
    "JPY": "엔",
    "CNY": "위안",
    "GBP": "파운드",
}
# 통화 금액의 세 자리 소수부는 유럽식 천 단위 구분점(5.000원 = 오천 원)일 수
# 있어 소수로 단정해 읽지 않는다.
_CURRENCY_UNIT_WORDS = frozenset(_CURRENCIES.values()) | frozenset(_ISO_CURRENCIES.values())
