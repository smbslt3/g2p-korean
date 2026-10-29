# SPDX-License-Identifier: MIT
"""정확한 뜻·등록 구성의 소유권을 어근 내부 속성으로 옮긴다.

원자적 어휘 사실을 기존 소유권 계약으로 소비한다. 완성 발음과 문장 치환은 없다.
"""

from dataclasses import dataclass, replace
from itertools import product
from types import SimpleNamespace

from .lexicon import LexicalStructure
from .rules import TENSE_ONSET


@dataclass(frozen=True)
class InternalOnsetConstraint:
    """형태소 독립성을 주장하지 않는 어휘 내부 초성 제약이다."""

    offset: int
    source_onset: str
    required_onset: str
    boundary_kind: str

    def __post_init__(self):
        if type(self.offset) is not int or self.offset <= 0:
            raise ValueError("내부 초성 위치는 양의 정수여야 합니다.")
        if TENSE_ONSET.get(self.source_onset) != self.required_onset:
            raise ValueError("내부 초성 제약은 기존 일반 된소리 전이만 허용합니다.")
        if self.boundary_kind not in {"compound_component", "lexical_syllable"}:
            raise ValueError("내부 초성 경계의 종류가 올바르지 않습니다.")


@dataclass(frozen=True)
class OwnedLexicalRoot:
    """뜻 신원, 원어 및 어근 안의 선택적 경음화 경계만 보관한다."""

    identity: str
    spelling: str
    owner_pos: frozenset[str]
    parts: tuple[tuple[str, str], ...]
    hanja: str
    sense_ids: frozenset[str] = frozenset()
    tense_boundaries: tuple[int, ...] = ()
    expected_onsets: tuple[tuple[int, str], ...] = ()
    default_reading: bool = False
    identity_classes: frozenset[str] = frozenset()
    internal_onsets: tuple[InternalOnsetConstraint, ...] = ()
    component_analyses: tuple[tuple[tuple[str, str], ...], ...] | None = None

    def __post_init__(self):
        # 전체 명사의 품사와 내부 성분의 품사는 서로 상속하지 않는다.
        # None은 기존 선언의 소유 계약을 보존하고, 빈 튜플은 통짜 분석만 허용한다.
        if self.component_analyses is not None:
            for analysis in self.component_analyses:
                if (not analysis or any(not form or not tag or "+" in tag for form, tag in analysis)
                        or "".join(form for form, _ in analysis) != self.spelling):
                    raise ValueError("명시 성분 분석은 전체 표기를 정확히 덮어야 합니다.")

    @property
    def lexical_structure(self):
        """확인된 내부 위치만 기존 공통 경계 규칙에 전달한다."""
        return LexicalStructure(self.parts, self.tense_boundaries)


@dataclass(frozen=True)
class OwnedPart:
    """등록 구성의 한 성분과 허용하는 실제 형태소 경로를 나타낸다."""

    spelling: str
    owner_pos: frozenset[str]
    root_identity: str | None = None
    split: tuple[tuple[str, frozenset[str]], ...] = ()


@dataclass(frozen=True)
class OwnedComposition:
    """허용한 결합과 전체·분리 분석만 신원 근거로 사용한다."""

    parts: tuple[OwnedPart, ...]
    owner_pos: frozenset[str]
    separators: tuple[str, ...] = ("",)


@dataclass(frozen=True)
class OwnedRootMatch:
    """소유 구성과 어근의 범위를 각각 보존한다."""

    root: OwnedLexicalRoot
    start: int
    end: int
    owner_start: int
    owner_end: int
    evidence_kind: str
    identity_decision: object = None


@dataclass(frozen=True)
class NominalSuffixLicense:
    """표면·품사·범주와 신원 보존을 함께 검증하는 국소 접미사 허가다."""

    affix_identity: str
    spelling: str
    morphological_class: str
    allowed_input_category: frozenset[str]
    output_category: str
    surface_realization_relation: str
    preserves_root_identity: bool
    allowed_following_tail_classes: frozenset[str]


NOMINAL_SUFFIX_LICENSES = (
    NominalSuffixLicense("nominal_plural", "들", "XSN", frozenset({"common", "proper", "nominal"}),
                         "nominal", "exact_concatenation", True, frozenset({"particle", "copula"})),
    NominalSuffixLicense("nominal_relational_derivation", "적", "XSN", frozenset({"common"}),
                         "nominal", "exact_concatenation", True, frozenset({"plural", "particle", "copula"})),
)


_COMMON = frozenset({"NNG"})
_NOMINAL = frozenset({"NNG", "NNP"})

OWNED_LEXICAL_ROOTS = (
    OwnedLexicalRoot(
        "munja_text_文字", "문자", _COMMON,
        (("문", "NNG"), ("자", "NNG")), "文字",
        frozenset({"munja.text", "munja.message_shorthand"}), (1,), ((1, "ㅈ"),), True,
    ),
    OwnedLexicalRoot(
        "ilsan_place_一山", "일산", _NOMINAL,
        (("일", "NNG"), ("산", "NNG")), "一山",
        identity_classes=frozenset({"place_name_type"}),
    ),
)

# 出題의 명사 신원만 등록한다. 내부 경음화는 일반 한자어 규칙에 맡긴다.
OWNED_NOMINAL_ORIGIN_ROOTS = (
    OwnedLexicalRoot(
        "chulje_exam_出題", "출제", _COMMON,
        (("출", "NNG"), ("제", "NNG")), "出題", default_reading=True,
    ),
)


# 성|격은 음절·한자 정렬이다. 성과 격의 독립 명사나 합성어 분류를 추가하지 않는다.
OWNED_INTERNAL_ONSET_ROOTS = (
    OwnedLexicalRoot(
        "uyugap_container_牛乳匣", "우유갑", _COMMON,
        (("우유", "NNG"), ("갑", "NNG")), "牛乳匣", default_reading=True,
        internal_onsets=(InternalOnsetConstraint(2, "ㄱ", "ㄲ", "compound_component"),),
    ),
    OwnedLexicalRoot(
        "seonggyeok_nature_性格", "성격", _COMMON,
        (("성격", "NNG"),), "性格", default_reading=True,
        internal_onsets=(InternalOnsetConstraint(1, "ㄱ", "ㄲ", "lexical_syllable"),),
    ),
)


# 성분열은 관찰한 정상 분석의 구조 메타데이터이며 어원·보편 접미사 규칙이 아니다.
# 발가락은 확인한 통짜 명사만 허용하고, 두 고유어에는 한자 신원을 붙이지 않는다.
OWNED_DECLARED_INTERNAL_ONSET_ROOTS = (
    OwnedLexicalRoot(
        "ganeungseong_possibility_可能性", "가능성", _COMMON,
        (("가능성", "NNG"),), "可能性", default_reading=True,
        internal_onsets=(InternalOnsetConstraint(2, "ㅅ", "ㅆ", "lexical_syllable"),),
        component_analyses=((("가능", "NNG"), ("성", "XSN")),),
    ),
    OwnedLexicalRoot(
        "balgarak_body", "발가락", _COMMON,
        (("발가락", "NNG"),), "", default_reading=True,
        internal_onsets=(InternalOnsetConstraint(1, "ㄱ", "ㄲ", "lexical_syllable"),),
        component_analyses=(),
    ),
    OwnedLexicalRoot(
        "baldwikkumchi_body", "발뒤꿈치", _COMMON,
        (("발뒤꿈치", "NNG"),), "", default_reading=True,
        internal_onsets=(InternalOnsetConstraint(1, "ㄷ", "ㄸ", "lexical_syllable"),),
        component_analyses=((("발", "NNG"), ("뒤꿈치", "NNG")),),
    ),
    OwnedLexicalRoot(
        "dalbit_moonlight", "달빛", _COMMON,
        (("달빛", "NNG"),), "", default_reading=True,
        internal_onsets=(InternalOnsetConstraint(1, "ㅂ", "ㅃ", "lexical_syllable"),),
        component_analyses=(),
    ),
)


def registered_owned_roots():
    """기존 등록 묶음의 계약을 보존하며 모든 정확 소유 어근을 열거한다."""
    return (*OWNED_LEXICAL_ROOTS, *OWNED_NOMINAL_ORIGIN_ROOTS,
            *OWNED_INTERNAL_ONSET_ROOTS, *OWNED_DECLARED_INTERNAL_ONSET_ROOTS)

# 메시지 앞 요소와 一山이 확인된 단일 지명 구성만 등록한다.
OWNED_COMPOSITIONS = (
    OwnedComposition((
        OwnedPart("문자", _COMMON, "munja_text_文字", (("문", _COMMON), ("자", _COMMON))),
        OwnedPart("메시지", _COMMON),
    ), _COMMON, ("", " ")),
    OwnedComposition((
        OwnedPart("일산", _NOMINAL, "ilsan_place_一山", (("일", _NOMINAL | {"NR"}), ("산", _NOMINAL))),
        OwnedPart("동구", _NOMINAL, split=(("동", _COMMON), ("구", frozenset({"NNG", "XSN"})))),
    ), _NOMINAL),
)


def _truthful(token, text, start, end, allowed):
    """표면 좌표와 형태소열이 모두 맞는 단순 명사 분석만 받는다."""
    return (
        token is not None
        and token.normalized_start == start and token.normalized_end == end
        and token.form == text[start:end] and token.tag in allowed
        and (not token.morphemes or (
            all(tag == token.tag for _, tag in token.morphemes)
            and "".join(form for form, _ in token.morphemes) == token.form
        ))
    )


def _part_owned(text, annotation, start, part):
    """전체 성분 또는 선언한 분리 경로가 성분 양 끝을 정확히 소유해야 한다."""
    end = start + len(part.spelling)
    if _truthful(annotation.starting_at(start), text, start, end, part.owner_pos):
        return True
    if not part.split:
        return False
    cursor = start
    for form, allowed in part.split:
        next_end = cursor + len(form)
        if text[cursor:next_end] != form or not _truthful(
            annotation.starting_at(cursor), text, cursor, next_end, allowed,
        ):
            return False
        cursor = next_end
    return cursor == end


def _simple_owned_token(token, text, start, end, allowed):
    """한 성분의 표면·품사·유래가 동일한 원문 범위를 소유해야 한다."""
    return (_truthful(token, text, start, end, allowed)
            and (not token.morphemes or token.morphemes == ((token.form, token.tag),)))


def _root_owned(text, annotation, start, root, source_annotation=None):
    """전체 명사와 정확히 선언한 내부 성분 분석을 별개의 소유 경로로 검증한다."""
    if root.component_analyses is None:
        # 기존 선언에서 허용하던 성분 품사와 분석 범위를 바꾸지 않는다.
        part = OwnedPart(root.spelling, root.owner_pos, split=tuple(
            (form, root.owner_pos) for form, _ in root.parts
        ))
        return _part_owned(text, annotation, start, part)
    end = start + len(root.spelling)
    if source_annotation is not None:
        source = source_annotation.starting_at(start)
        if (source is not None and source.normalized_end >= end
                and source.tag in {"NNG", "NNP"} and source.tag not in root.owner_pos):
            # 원래 명사 포장의 품사는 성분 투영 후에도 남는 전체 소유 조건이다.
            # 명시된 NNG+XSN 같은 결합 태그는 포장 명사 품사로 바꾸지 않는다.
            return False
    token = annotation.starting_at(start)
    if _simple_owned_token(token, text, start, end, root.owner_pos):
        return True
    # 통짜 명사 포장 안의 세부 유래도 선언한 성분열과 정확히 같아야 한다.
    if (_truthful(token, text, start, end, root.owner_pos)
            and token.morphemes in root.component_analyses):
        return True
    for analysis in root.component_analyses:
        cursor = start
        for form, tag in analysis:
            next_end = cursor + len(form)
            if (text[cursor:next_end] != form
                    or not _simple_owned_token(annotation.starting_at(cursor), text, cursor,
                                               next_end, frozenset({tag}))):
                break
            cursor = next_end
        else:
            if cursor == end:
                return True
    return False


def _licensed_tail(text, annotation, end, owner, nominal_tail_validator):
    """붙은 조사는 표면·품사·형태소열을 검증하고 계사는 기존 검증기에 맡긴다."""
    cursor, _, _ = _licensed_suffix_chain(text, annotation, end, owner)
    if cursor is None:
        return False
    while cursor < len(text) and text[cursor].isalnum():
        token = annotation.starting_at(cursor)
        if token is None or token.normalized_end <= cursor:
            return False
        if token.tag.split("+")[0] == "VCP":
            return nominal_tail_validator is not None and nominal_tail_validator(
                annotation, cursor, annotation.ending_at(cursor), text[owner.normalized_start:cursor],
            )
        parts = token.morphemes or ((token.form, token.tag),)
        tags = tuple(token.tag.split("+"))
        if (
            not tags or any(not tag.startswith("J") for tag in tags)
            or tuple(tag for _, tag in parts) != tags
            or "".join(form for form, _ in parts) != token.form
            or token.form != text[cursor:token.normalized_end]
        ):
            return False
        cursor = token.normalized_end
    return True


def _licensed_suffix_chain(text, annotation, end, owner):
    """원래 명사 바로 뒤의 검증한 접미사 사슬만 내부 속성을 상속한다."""
    cursor = end
    category = "proper" if owner is not None and owner.tag == "NNP" else "common"
    chain = []
    permitted = frozenset({"derivation", "plural", "particle", "copula"})
    while cursor < len(text) and text[cursor].isalnum():
        token = annotation.starting_at(cursor)
        if token is None or token.tag != "XSN":
            break
        license = next((item for item in NOMINAL_SUFFIX_LICENSES
                        if item.spelling == token.form and category in item.allowed_input_category), None)
        kind = "plural" if license is not None and license.affix_identity == "nominal_plural" else "derivation"
        if (license is None or kind not in permitted or not license.preserves_root_identity
                or not _truthful(token, text, cursor, token.normalized_end, frozenset({"XSN"}))):
            return None, (), category
        chain.append((license, cursor, token.normalized_end))
        cursor = token.normalized_end
        category = license.output_category
        permitted = license.allowed_following_tail_classes
    token = annotation.starting_at(cursor)
    if chain and token is not None and token.normalized_start == cursor:
        tail_class = "copula" if token.tag.split("+")[0] == "VCP" else "particle" if token.tag.startswith("J") else "other"
        if cursor < len(text) and text[cursor].isalnum() and tail_class not in permitted:
            return None, (), category
    return cursor, tuple(chain), category


def _direct_part_origins_match(token):
    """직접 연결 원형의 명시 범위가 누적 원문 범위와 모순되지 않는지 확인한다."""
    if not token.morpheme_spans:
        return True
    cursor = token.normalized_start
    expected = []
    for form, _ in token.morphemes:
        expected.append((cursor, cursor + len(form)))
        cursor += len(form)
    return tuple(expected) == token.morpheme_spans


def _project_original_part(token, index, start):
    """같은 원형 조각의 실제 범위만 보존하며 새 원시 분석 범위를 만들지 않는다."""
    form, tag = token.morphemes[index]
    end = start + len(form)
    spans = ()
    if (len(token.morpheme_spans) == len(token.morphemes)
            and token.morpheme_spans[index] == (start, end)):
        spans = (token.morpheme_spans[index],)
    return replace(token, form=form, tag=tag, normalized_start=start, normalized_end=end,
                   morphemes=((form, tag),), morpheme_spans=spans)


def _atomic_annotation(text, annotation):
    """진실한 연속 명사·접미 분석은 전체 토큰에서도 같은 원문 성분으로 투영한다."""
    tokens = []
    for token in annotation._tokens_starting_at.values():
        parts = token.morphemes
        tags = tuple(tag for _, tag in parts)
        surface = text[token.normalized_start:token.normalized_end]
        nominal = bool(tags and tags[0] in {"NNG", "NNP"} and all(tag == "XSN" for tag in tags[1:]))
        licensed_shape = token.tag == "+".join(tags) or (token.tag in {"NNG", "NNP"} and nominal)
        if (len(parts) > 1 and licensed_shape and token.form == surface
                and "".join(form for form, _ in parts) == surface and _direct_part_origins_match(token)):
            cursor = token.normalized_start
            for index, (form, tag) in enumerate(parts):
                tokens.append(_project_original_part(token, index, cursor))
                cursor += len(form)
        else:
            tokens.append(token)
    return type(annotation).from_tokens(tuple(tokens), text)


def _outside_owned(text, annotation, start, end, nominal_tail_validator):
    """앞에 붙은 다른 낱말과 미등록 후행 명사·접미사는 소유 범위에서 제외한다."""
    return (
        (start == 0 or not text[start - 1].isalnum())
        and _licensed_tail(text, annotation, end, annotation.ending_at(end), nominal_tail_validator)
    )


def _composition_part_owned(text, annotation, start, part, roots, source_annotation=None):
    """등록 어근의 명시 성분 계약을 결합 안에서도 같은 소비기로 검증한다."""
    root = roots.get(part.root_identity)
    if root is not None and root.component_analyses is not None:
        return (root.spelling == part.spelling
                and _root_owned(text, annotation, start, root, source_annotation))
    return _part_owned(text, annotation, start, part)


def _whole_composition_owned(text, annotation, start, end, composition, separators, roots,
                             source_annotation=None):
    """통짜 결합도 세부 유래가 있으면 선언한 각 성분의 품사를 지켜야 한다."""
    strict = any(part.root_identity in roots and roots[part.root_identity].component_analyses is not None
                 for part in composition.parts)
    if not strict:
        # 기존 등록 결합의 전체 소유 계약은 그대로 유지한다.
        return _truthful(annotation.starting_at(start), text, start, end, composition.owner_pos)
    source = source_annotation if source_annotation is not None else annotation
    token = source.starting_at(start)
    if _simple_owned_token(token, text, start, end, composition.owner_pos):
        return True
    if (token is None or token.normalized_start != start or token.normalized_end != end
            or token.form != text[start:end] or token.tag not in composition.owner_pos
            or not token.morphemes
            or any(not form or not tag or "+" in tag for form, tag in token.morphemes)
            or "".join(form for form, _ in token.morphemes) != token.form
            or not _direct_part_origins_match(token)):
        return False
    # 전체 명사 포장의 허용 품사는 위에서 검증한다. 세부 유래의 품사는 바꾸지 않는다.
    # 선언한 결합 전체에 한해 정확히 정렬한 유래를 투영하고 각 내부 소유를 재검증한다.
    projected = []
    cursor = start
    for index, (form, tag) in enumerate(token.morphemes):
        projected.append(_project_original_part(token, index, cursor))
        cursor += len(form)
    details = type(annotation).from_tokens(tuple(projected), text)
    cursor = start
    for index, part in enumerate(composition.parts):
        if not _composition_part_owned(text, details, cursor, part, roots, details):
            return False
        cursor += len(part.spelling)
        if index < len(separators):
            cursor += len(separators[index])
    return cursor == end


def _structural_owned_root_matches(text, annotation, selections=(), *, nominal_tail_validator=None,
                                   source_annotation=None):
    """뜻 선택과 등록 구성에 같은 정확 범위 검사를 적용한다."""
    roots = {root.identity: root for root in registered_owned_roots()}
    seen = set()
    rejected_compositions = set()
    for choice in selections:
        for root in roots.values():
            if choice.sense_id not in root.sense_ids or choice.spelling != root.spelling:
                continue
            if (
                text[choice.start:choice.end] == root.spelling
                and _root_owned(text, annotation, choice.start, root, source_annotation)
                and _outside_owned(text, annotation, choice.start, choice.end, nominal_tail_validator)
            ):
                key = root.identity, choice.start, choice.end
                seen.add(key)
                yield OwnedRootMatch(root, choice.start, choice.end, choice.start, choice.end, "selected_sense")
    for composition in OWNED_COMPOSITIONS:
        for separators in product(composition.separators, repeat=len(composition.parts) - 1):
            spelling = composition.parts[0].spelling + "".join(
                separator + part.spelling for separator, part in zip(separators, composition.parts[1:])
            )
            start = text.find(spelling)
            while start >= 0:
                end = start + len(spelling)
                whole = _whole_composition_owned(text, annotation, start, end, composition,
                                                 separators, roots, source_annotation)
                cursor = start
                owned = True
                locations = []
                for index, part in enumerate(composition.parts):
                    component_owned = _composition_part_owned(text, annotation, cursor, part, roots,
                                                               source_annotation)
                    owned = owned and (whole or component_owned)
                    if part.root_identity is not None:
                        locations.append((roots[part.root_identity], cursor, cursor + len(part.spelling)))
                    cursor += len(part.spelling)
                    if index < len(separators):
                        cursor += len(separators[index])
                if owned and _outside_owned(text, annotation, start, end, nominal_tail_validator):
                    for root, root_start, root_end in locations:
                        key = root.identity, root_start, root_end
                        if key not in seen:
                            seen.add(key)
                            yield OwnedRootMatch(root, root_start, root_end, start, end, "registered_composition")
                else:
                    # 표기는 등록 구성과 같아도 분석이 부적합하면 기본 읽기로 우회하지 않는다.
                    rejected_compositions.update((root.identity, root_start, root_end)
                                                 for root, root_start, root_end in locations)
                start = text.find(spelling, start + 1)
    # 불충분한 문맥의 보통명사에 적용하는 사전 기본 읽기 정책이다.
    # 이 경로는 메시지 뜻을 관찰·확정했다는 의미 증거로 취급하지 않는다.
    for choice in selections:
        if choice.sense_id is not None or choice.reason != "insufficient_evidence":
            continue
        for root in roots.values():
            key = root.identity, choice.start, choice.end
            if not root.default_reading or choice.spelling != root.spelling or key in seen or key in rejected_compositions:
                continue
            if (
                text[choice.start:choice.end] == root.spelling
                and _root_owned(text, annotation, choice.start, root, source_annotation)
                and _outside_owned(text, annotation, choice.start, choice.end, nominal_tail_validator)
            ):
                seen.add(key)
                yield OwnedRootMatch(root, choice.start, choice.end, choice.start, choice.end, "dictionary_default_policy")


def owned_root_decisions(text, annotation, selections=(), *, nominal_tail_validator=None, hard_boundaries=frozenset()):
    """구조 검증, 관계 귀속, 경쟁 판정과 정책 기본값을 순서대로 분리한다."""
    from .owned_identity import decide_owned_identity, collect_owned_relations
    source_annotation = annotation
    annotation = _atomic_annotation(text, annotation)
    targets = []
    for root in registered_owned_roots():
        start = text.find(root.spelling)
        while start >= 0:
            targets.append(SimpleNamespace(start=start, end=start + len(root.spelling), spelling=root.spelling,
                                           sense_id=None, reason="insufficient_evidence"))
            start = text.find(root.spelling, start + 1)
    structural = tuple(_structural_owned_root_matches(
        text, annotation, targets, nominal_tail_validator=nominal_tail_validator,
        source_annotation=source_annotation,
    ))
    projections = []
    for match in structural:
        end, chain, _ = _licensed_suffix_chain(text, annotation, match.owner_end, annotation.ending_at(match.owner_end))
        if end is not None:
            projections.append((match, end, chain))
    relations = collect_owned_relations(text, annotation, projections, hard_boundaries)
    selections = {(item.start, item.end): item for item in selections}
    for match, nominal_end, chain in projections:
        yield decide_owned_identity(text, match, nominal_end, chain,
                                    selections.get((match.start, match.end)), relations)


def owned_root_matches(text, annotation, selections=(), *, nominal_tail_validator=None, hard_boundaries=frozenset()):
    """명시적 경쟁 신원과 관련 미지원 관계는 모든 적용 경로보다 먼저 차단한다."""
    for decision in owned_root_decisions(text, annotation, selections,
                                        nominal_tail_validator=nominal_tail_validator, hard_boundaries=hard_boundaries):
        if decision.applies:
            yield replace(decision.match, owner_end=decision.nominal_end,
                          evidence_kind=decision.match_evidence_kind, identity_decision=decision)
