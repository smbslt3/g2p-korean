# SPDX-License-Identifier: MIT
"""유한한 규칙 활용을 원형 출현별 자모 유래와 함께 재생성한다."""

from __future__ import annotations

from dataclasses import dataclass
import unicodedata

from .hangul import CHOSEONG, JUNGSEONG, JONGSEONG, is_modern_syllable


from .word_grammar import (ENDINGS, SUFFIXES, PARTICLES, VARIABLES,
                           base_tag as _base, parse_parts)


_COMPATIBILITY_CODAS = {value: chr(0x11A7 + index)
                        for index, value in enumerate(JONGSEONG) if value in {"ㄴ", "ㄹ", "ㅁ", "ㅂ", "ㅆ"}}


def _role(jamo):
    value = ord(jamo)
    return ("onset" if 0x1100 <= value <= 0x1112 else
            "vowel" if 0x1161 <= value <= 0x1175 else
            "coda" if 0x11A8 <= value <= 0x11C2 else "other")


def _compatible(jamo):
    value = ord(jamo)
    if _role(jamo) == "onset":
        return CHOSEONG[value - 0x1100]
    if _role(jamo) == "vowel":
        return JUNGSEONG[value - 0x1161]
    if _role(jamo) == "coda":
        return JONGSEONG[value - 0x11A7]
    return jamo


@dataclass(frozen=True, order=True, slots=True)
class SourceAtom:
    """같은 원형·태그라도 출현과 원형 내부 위치가 다른 근거다."""

    occurrence: int
    source_offset: int
    role: str
    jamo: str


@dataclass(frozen=True, slots=True)
class ProvenAtom:
    """실제 표면 자모와 그것을 생성한 원형 자모의 집합이다."""

    jamo: str
    offset: int
    role: str
    origins: tuple[SourceAtom, ...]


@dataclass(frozen=True, slots=True)
class RuleStep:
    """한 원래 경계에서 적용한 유한 변환과 삭제를 기록한다."""

    boundary: tuple[int, int]
    rule_id: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    before_origins: tuple[tuple[SourceAtom, ...], ...]
    after_origins: tuple[tuple[SourceAtom, ...], ...]
    deleted: tuple[SourceAtom, ...] = ()


@dataclass(frozen=True, slots=True)
class Occurrence:
    """공급된 원형 신원과 원시 범위를 출현별로 보존한다."""

    index: int
    form: str
    tag: str
    raw_span: tuple[int, int] | None


@dataclass(frozen=True, slots=True)
class DeletedOccurrence:
    """살아 있는 범위 없이 사라진 출현의 원형 원자와 유일한 경계다."""

    index: int
    offset: int
    boundary: tuple[int, int]
    rule_id: str
    atoms: tuple[SourceAtom, ...]


@dataclass(frozen=True, slots=True)
class TokenSurfaceProof:
    """토큰 전체 재생성과 정확한 범위·공동 유래를 분리해 제공한다."""

    start: int
    end: int
    parts: tuple[tuple[str, str], ...]
    morpheme_spans: tuple[tuple[int, int], ...]
    occurrences: tuple[Occurrence, ...]
    regenerated_spans: tuple[tuple[int, int] | None, ...]
    atoms: tuple[ProvenAtom, ...]
    steps: tuple[RuleStep, ...] = ()
    deleted_occurrences: tuple[DeletedOccurrence, ...] = ()

    @property
    def rule_steps(self):
        return tuple(step.rule_id for step in self.steps)

    @property
    def contracted_boundary(self):
        boundaries = tuple(dict.fromkeys(step.boundary for step in self.steps
                                         if step.deleted))
        return boundaries[0] if len(boundaries) == 1 else None

    @property
    def shared_offset(self):
        offsets = {atom.offset for atom in self.atoms if len({o.occurrence for o in atom.origins}) > 1}
        return next(iter(offsets)) if len(offsets) == 1 else None

    @property
    def ending_initial(self):
        boundary = self.contracted_boundary
        return self.parts[boundary[1]][0][0] if boundary is not None else None

    @property
    def shared_jamo_origins(self):
        offset = self.shared_offset
        return tuple((_compatible(atom.jamo), tuple(sorted({o.occurrence for o in atom.origins})))
                     for atom in self.atoms if atom.offset == offset) if offset is not None else ()


@dataclass(frozen=True, slots=True)
class _Atom:
    jamo: str
    origins: tuple[SourceAtom, ...]


@dataclass(frozen=True, slots=True)
class _State:
    atoms: tuple[_Atom, ...]
    steps: tuple[RuleStep, ...] = ()


def _grammar(parts, *, allow_auxiliary=True):
    """표면 조각의 경계 허가는 공유 순수 문법 결과에서만 받는다."""
    grammar = parse_parts(parts, fragment=True, allow_auxiliary=allow_auxiliary)
    if grammar.lexical_status == "eligible" or grammar.reason == "independent_basis_absent":
        return grammar.boundaries
    return None


def _canonical_atoms(parts):
    result = []
    for occurrence, (form, tag) in enumerate(parts):
        atoms = []
        for offset, character in enumerate(form):
            if tag in ENDINGS and offset == 0 and character in _COMPATIBILITY_CODAS:
                decomposed = _COMPATIBILITY_CODAS[character]
            elif (not is_modern_syllable(character)
                  and not (tag in ENDINGS and offset == 0 and _role(character) == "coda")):
                return None
            else:
                decomposed = unicodedata.normalize("NFD", character)
            for jamo in decomposed:
                role = _role(jamo)
                if role == "other":
                    return None
                atoms.append(_Atom(jamo, (SourceAtom(occurrence, offset, role, jamo),)))
        result.append(tuple(atoms))
    return tuple(result)


def _step(boundary, rule_id, before, after, deleted=()):
    return RuleStep(boundary, rule_id, tuple(a.jamo for a in before),
                    tuple(a.jamo for a in after), tuple(a.origins for a in before),
                    tuple(a.origins for a in after), tuple(sorted(deleted)))


def _regular(form, tag):
    return not tag.endswith("-I") and (not form.endswith("르") or tag.endswith("-R"))


def _pre_ha_sound(character):
    """단순 받침의 대표음만 진단하며 원형·표면 자모는 바꾸지 않는다."""
    if not is_modern_syllable(character):
        return None
    jamo = unicodedata.normalize("NFD", character)
    if len(jamo) == 2:
        return "vowel"
    return {
        "ᆨ": "ㄱ", "ᆩ": "ㄱ", "ᆿ": "ㄱ",
        "ᆮ": "ㄷ", "ᆺ": "ㄷ", "ᆻ": "ㄷ", "ᆽ": "ㄷ", "ᆾ": "ㄷ", "ᇀ": "ㄷ",
        "ᆸ": "ㅂ", "ᇁ": "ㅂ", "ᆫ": "ㄴ", "ᆯ": "ㄹ", "ᆷ": "ㅁ", "ᆼ": "ㅇ",
    }.get(jamo[2])


def _source_syllable(parts, occurrence, offset):
    """공급 원형의 한 음절을 정확한 출현·위치의 원자에 대응한다."""
    return tuple(_Atom(jamo, (SourceAtom(occurrence, offset, _role(jamo), jamo),))
                 for jamo in unicodedata.normalize("NFD", parts[occurrence][0][offset]))


def _ha_choices(state, right, parts, index, boundary):
    """활성 어간의 말음절 하와 ㄱ·ㄷ·ㅈ 시작 어미만 유한하게 줄인다."""
    if not boundary.active_ha or not boundary.inflection or len(right) < 2:
        return
    aspirated = {"ᄀ": "ᄏ", "ᄃ": "ᄐ", "ᄌ": "ᄎ"}.get(right[0].jamo)
    if aspirated is None or _role(right[1].jamo) != "vowel":
        return
    occurrence = index - 1
    form, tag = parts[occurrence]
    ha = _source_syllable(parts, occurrence, len(form) - 1)
    if len(ha) != 2 or tuple(atom.jamo for atom in ha) != ("ᄒ", "ᅡ") or state.atoms[-2:] != ha:
        return
    if len(form) > 1:
        previous, offset = occurrence, len(form) - 2
    elif _base(tag) in {"XSV", "XSA"} and occurrence > boundary.stem_start:
        previous, offset = occurrence - 1, len(parts[occurrence - 1][0]) - 1
    else:
        return
    preceding = _source_syllable(parts, previous, offset)
    if state.atoms[-2 - len(preceding):-2] != preceding:
        return
    sound = _pre_ha_sound(parts[previous][0][offset])
    if sound in {"ㄱ", "ㄷ", "ㅂ"}:
        after, deleted, rule = right, ha[0].origins + ha[1].origins, "맞춤법.40.붙임2.하탈락"
    elif sound in {"vowel", "ㄴ", "ㄹ", "ㅁ", "ㅇ"}:
        origins = tuple(sorted(ha[0].origins + right[0].origins))
        after = (_Atom(aspirated, origins), *right[1:])
        deleted, rule = ha[1].origins, "맞춤법.40.격음축약"
    else:
        return
    step = _step((occurrence, index), rule, (*ha, *right), after, deleted)
    yield _State((*state.atoms[:-2], *after), state.steps + (step,))


def _ji_anh_choices(state, right, parts, index, boundary):
    """정확한 지/EC와 않/VX를 소유·삭제 증거를 보존하며 줄인다."""
    if not boundary.negative_auxiliary or len(right) != 3 or len(state.atoms) < 2:
        return
    ji = _source_syllable(parts, index - 1, 0)
    onset, vowel = state.atoms[-2:]
    prior_ha = (index >= 2 and parts[index - 2][0].endswith("하")
                and _base(parts[index - 2][1]) in VARIABLES)
    ha_step = next((step for step in reversed(state.steps)
                    if step.boundary == (index - 2, index - 1)
                    and step.rule_id in {"맞춤법.40.격음축약", "맞춤법.40.붙임2.하탈락"}), None)
    if prior_ha and ha_step is None:
        # 하가 남아 있는 경로에서 제39항만 따로 조합하지 않는다.
        return
    if vowel != ji[1]:
        return
    if onset == ji[0]:
        pass
    elif (ha_step is None or ha_step.rule_id != "맞춤법.40.격음축약"
          or onset.jamo != "ᄎ" or ha_step.after_origins[0] != onset.origins):
        return
    if tuple(atom.jamo for atom in right) != ("ᄋ", "ᅡ", "ᆭ"):
        return
    fused = _Atom("ᅡ", tuple(sorted(vowel.origins + right[1].origins)))
    after = (onset, fused, right[2])
    step = _step((index - 1, index), "맞춤법.39.지않축약", (*state.atoms[-2:], *right),
                 after, right[0].origins)
    yield _State((*state.atoms[:-2], *after), state.steps + (step,))


def _irregular_ds_choices(state, right, parts, index, boundary):
    """명시된 활성 어간의 단일 ㄷ·ㅅ 종성만 공급된 모음 어미 앞에서 바꾼다."""
    if (not boundary.inflection or boundary.causative
            or index - 1 < boundary.stem_start
            or parts[index - 1][1] not in {"VV-I", "VA-I", "VX-I", "XSA-I"}
            or parts[index][1] not in ENDINGS
            or not is_modern_syllable(parts[index][0][0])
            or len(right) < 2 or right[0].jamo != "ᄋ"
            or right[1].jamo not in {"ᅡ", "ᅥ", "ᅳ"}):
        return
    occurrence = index - 1
    terminal = _source_syllable(parts, occurrence, len(parts[occurrence][0]) - 1)
    if (len(terminal) != 3 or terminal[-1].jamo not in {"ᆮ", "ᆺ"}
            or state.atoms[-3:] != terminal):
        return
    if terminal[-1].jamo == "ᆮ":
        changed = (*terminal[:-1], _Atom("ᆯ", terminal[-1].origins))
        rule, deleted = "맞춤법.18.5.ㄷ교체", ()
    else:
        changed = terminal[:-1]
        rule, deleted = "맞춤법.18.2.ㅅ탈락", terminal[-1].origins
    # 이 경계에서는 공급된 어미 전체를 보존하며 다시 모음 축약에 넣지 않는다.
    after = (*changed, *right)
    step = _step((occurrence, index), rule, (*terminal, *right), after, deleted)
    yield _State((*state.atoms[:-3], *after), state.steps + (step,))


def _ending_choices(left, right, parts, index, boundary):
    """조화가 확인된 아/어 및 정확한 하의 여 이형태만 별도 생성한다."""
    yield right, ()
    if len(right) < 2 or right[0].jamo != "ᄋ" or right[1].jamo not in {"ᅡ", "ᅥ", "ᅧ"}:
        return
    form, tag = parts[index - 1]
    if right[1].jamo == "ᅡ" and unicodedata.normalize("NFD", form).endswith("ᅵ"):
        # 공급된 개별 원형 아는 제36항을 위해 어로 바꾸지 않는다.
        return
    ha = form == "하" and _base(tag) in {"XSV", "XSA"}
    if ha:
        selected, rule = "ᅧ", "맞춤법.18.7"
    else:
        if right[1].jamo == "ᅧ" or not _regular(form, tag):
            return
        left_vowels = [atom.jamo for atom in left if _role(atom.jamo) == "vowel"]
        if not left_vowels:
            return
        last = left_vowels[-1]
        if last == "ᅳ":
            # 같은 파생 어간 안의 앞 음절만 ㅡ 조화의 문맥으로 쓴다.
            stem = "".join(part for part, _ in parts[boundary.stem_start:index])
            vowels = [jamo for jamo in unicodedata.normalize("NFD", stem) if _role(jamo) == "vowel"]
            last = vowels[-2] if len(vowels) > 1 else None
        selected, rule = ("ᅡ" if last in {"ᅡ", "ᅩ"} else "ᅥ"), "맞춤법.16"
    if selected != right[1].jamo:
        changed = (right[0], _Atom(selected, right[1].origins), *right[2:])
        yield changed, (_step((index - 1, index), rule, right, changed),)


def _boundary_choices(state, right, parts, index, boundary):
    """각 원래 경계를 한 번만 방문하여 직접 연결 또는 규칙 변환한다."""
    yield _State(state.atoms + right, state.steps)
    yield from _ha_choices(state, right, parts, index, boundary)
    yield from _ji_anh_choices(state, right, parts, index, boundary)
    yield from _irregular_ds_choices(state, right, parts, index, boundary)
    if not boundary.inflection and not boundary.causative:
        return
    left = state.atoms
    if (len(left) < 2 or _role(left[-1].jamo) != "vowel"
            or _role(left[-2].jamo) != "onset"):
        return
    form, tag = parts[index - 1]
    ha = form == "하" and _base(tag) in {"XSV", "XSA"}
    if not ha and not _regular(form, tag):
        return
    if boundary.inflection and form.endswith("하") and not ha:
        # 제외한 하 활용에서는 일반 조화 단계도 새 인증의 근거가 아니다.
        return
    if boundary.inflection and (
        len(right) < 2 or right[0].jamo != "ᄋ" or right[1].jamo not in {"ᅡ", "ᅥ", "ᅧ"}
        or len(right) > 2 and _role(right[2].jamo) == "coda" and right[2].jamo != "ᆻ"
    ):
        return
    if boundary.causative:
        if (parts[index][0] != "이" or _base(parts[index][1]) != "XSV"
                or parts[index][1].endswith("-I") or len(right) != 2):
            return
        choices = ((right, ()),)
    else:
        choices = _ending_choices(left, right, parts, index, boundary)
    for ending, allomorph in choices:
        if allomorph:
            yield _State(left + ending, state.steps + allomorph)
        if (len(ending) < 2 or ending[0].jamo != "ᄋ"
                or len(ending) > 2 and _role(ending[2].jamo) == "coda" and ending[2].jamo != "ᆻ"):
            continue
        lv, rv = left[-1].jamo, ending[1].jamo
        ha = form == "하" and _base(tag) in {"XSV", "XSA"}
        selected = None
        exclusive_ending = False
        if boundary.causative:
            selected = {"ᅡ": ("ᅢ", "맞춤법.37"), "ᅧ": ("ᅨ", "맞춤법.37"),
                        "ᅩ": ("ᅬ", "맞춤법.37"), "ᅮ": ("ᅱ", "맞춤법.37"),
                        "ᅳ": ("ᅴ", "맞춤법.37")}.get(lv) if rv == "ᅵ" else None
        elif ha:
            if rv == "ᅧ":
                selected = ("ᅢ", "맞춤법.34.붙임2")
        elif form.endswith("하"):
            # 이 계약의 하 부류를 다른 용언 원형으로 확대하지 않는다.
            continue
        else:
            # 직접 원형이 다른 조화 계열이면 이형태 단계를 거친 경우만 축약한다.
            valid_right = list(_ending_choices(left, right, parts, index, boundary))
            selected_vowel = valid_right[-1][0][1].jamo
            if rv != selected_vowel:
                continue
            pairs = {
                ("ᅡ", "ᅡ"): ("ᅡ", "맞춤법.34"),
                ("ᅥ", "ᅥ"): ("ᅥ", "맞춤법.34"),
                ("ᅢ", "ᅥ"): ("ᅢ", "맞춤법.34.붙임1"),
                ("ᅦ", "ᅥ"): ("ᅦ", "맞춤법.34.붙임1"),
                ("ᅩ", "ᅡ"): ("ᅪ", "맞춤법.35"),
                ("ᅮ", "ᅥ"): ("ᅯ", "맞춤법.35"),
                ("ᅬ", "ᅥ"): ("ᅫ", "맞춤법.35.붙임2"),
                ("ᅵ", "ᅥ"): ("ᅧ", "맞춤법.36"),
            }
            selected = pairs.get((lv, rv))
            if lv == "ᅳ" and rv in {"ᅡ", "ᅥ"} and _base(tag) in VARIABLES:
                selected, exclusive_ending = (rv, "맞춤법.18.4"), True
        if selected is None:
            continue
        vowel, rule = selected
        origins = ending[1].origins if exclusive_ending else tuple(sorted(set(left[-1].origins + ending[1].origins)))
        fused = (_Atom(vowel, origins),)
        after = (left[-2], *fused, *ending[2:])
        deleted = ending[0].origins + (left[-1].origins if exclusive_ending else ())
        step = _step((index - 1, index), rule, (*left[-2:], *ending), after, deleted)
        yield _State((*left[:-2], *after), state.steps + allomorph + (step,))


def _stable_prefix(atoms):
    last = next((index for index in range(len(atoms) - 1, -1, -1)
                 if _role(atoms[index].jamo) == "onset"), len(atoms))
    return "".join(atom.jamo for atom in atoms[:last])


def _accounted_atoms(parts, state):
    """살아 있는 유래와 삭제가 정규 원형 원자를 중복 없이 모두 설명해야 한다."""
    originals = _canonical_atoms(parts)
    if originals is None:
        return None
    canonical = {origin for group in originals for atom in group for origin in atom.origins}
    live = [origin for atom in state.atoms for origin in atom.origins]
    deleted = [origin for step in state.steps for origin in step.deleted]
    if (any(not atom.origins for atom in state.atoms)
            or len(live) != len(set(live)) or len(deleted) != len(set(deleted))
            or set(live) & set(deleted) or set(live) | set(deleted) != canonical):
        return None
    for step in state.steps:
        before = {origin for origins in step.before_origins for origin in origins}
        after = {origin for origins in step.after_origins for origin in origins}
        if (step.boundary[1] != step.boundary[0] + 1
                or not 0 <= step.boundary[0] < step.boundary[1] < len(parts)
                or not before <= canonical or after & set(step.deleted)
                or before != after | set(step.deleted)):
            return None
    return originals


def _deleted_occurrence(index, originals, proven, steps):
    """전체 하 삭제의 원자·경계와 양옆 표면으로 단 하나의 삭제 위치를 증명한다."""
    own = tuple(origin for atom in originals[index] for origin in atom.origins)
    own_set = set(own)
    events = [step for step in steps if own_set & set(step.deleted)]
    if (len(events) != 1 or events[0].rule_id != "맞춤법.40.붙임2.하탈락"
            or events[0].boundary != (index, index + 1) or set(events[0].deleted) != own_set):
        return None
    previous = {atom.offset for atom in proven if any(origin.occurrence < index for origin in atom.origins)}
    following = {atom.offset for atom in proven if any(origin.occurrence > index for origin in atom.origins)}
    if not previous or not following or max(previous) + 1 != min(following):
        return None
    event = events[0]
    return DeletedOccurrence(index, min(following), event.boundary, event.rule_id, tuple(sorted(own)))


def _proof(token, parts, spans, state):
    raw = "".join(atom.jamo for atom in state.atoms)
    surface = unicodedata.normalize("NFC", raw)
    if surface != token.form or unicodedata.normalize("NFD", surface) != raw:
        return None
    originals = _accounted_atoms(parts, state)
    if originals is None:
        return None
    proven = []
    cursor = 0
    for offset, character in enumerate(surface, token.normalized_start):
        for jamo in unicodedata.normalize("NFD", character):
            atom = state.atoms[cursor]
            proven.append(ProvenAtom(jamo, offset, _role(jamo), atom.origins))
            cursor += 1
    ranges, deleted_occurrences = [], []
    for index in range(len(parts)):
        positions = [atom.offset for atom in proven if any(origin.occurrence == index for origin in atom.origins)]
        if not positions:
            deleted = _deleted_occurrence(index, originals, proven, state.steps)
            if deleted is None or not spans or spans[index] != (deleted.offset, deleted.offset):
                return None
            ranges.append(None)
            deleted_occurrences.append(deleted)
        else:
            live_range = (min(positions), max(positions) + 1)
            if spans and spans[index] != live_range:
                return None
            ranges.append(live_range)
    if not spans and (state.steps or "".join(form for form, _ in parts) != token.form):
        return None
    occurrences = tuple(Occurrence(index, form, tag, spans[index] if spans else None)
                        for index, (form, tag) in enumerate(parts))
    return TokenSurfaceProof(token.normalized_start, token.normalized_end, parts, spans,
                             occurrences, tuple(ranges), tuple(proven), state.steps, tuple(deleted_occurrences))


def _licensed_states(parts, surface):
    """원시 범위와 무관한 승인 표면 언어의 유한 상태만 생성한다."""
    originals = _canonical_atoms(parts)
    if originals is None:
        return ()
    grammar = _grammar(parts)
    expected = unicodedata.normalize("NFD", surface)
    states = (_State(originals[0]),)
    for index in range(1, len(parts)):
        unique = {}
        for state in states:
            options = (_boundary_choices(state, originals[index], parts, index, grammar[index])
                       if grammar is not None else (_State(state.atoms + originals[index], state.steps),))
            for option in options:
                if expected.startswith(_stable_prefix(option.atoms)):
                    # 살아 있는 소유가 같아도 삭제의 원래 경계가 다르면 합치지 않는다.
                    key = (tuple((atom.jamo, atom.origins) for atom in option.atoms),
                           tuple((step.boundary, step.rule_id, step.deleted)
                                 for step in option.steps if step.deleted))
                    unique.setdefault(key, option)
        states = tuple(unique.values())
    return states


def licensed_spelling(parts, surface):
    """정확한 표기·어휘 범주용 약한 근거이며 원시 범위나 자모 소유는 발행하지 않는다."""
    parts = tuple(parts)
    if (not parts or any(not form or not tag or "+" in tag for form, tag in parts)
            or not surface or not all(is_modern_syllable(char) for char in surface)):
        return False
    expected = unicodedata.normalize("NFD", surface)
    return any("".join(atom.jamo for atom in state.atoms) == expected
               for state in _licensed_states(parts, surface))


def verified_token_surface(token):
    """정확한 전체 표면과 출현별 범위가 유일한 생산적 증명만 반환한다."""
    parts = token.morphemes or ((token.form, token.tag),)
    if (tuple(tag for _, tag in parts) != tuple(token.tag.split("+"))
            or any(not form for form, _ in parts)
            or isinstance(token.normalized_start, bool) or not isinstance(token.normalized_start, int)
            or isinstance(token.normalized_end, bool) or not isinstance(token.normalized_end, int)
            or not 0 <= token.normalized_start < token.normalized_end
            or len(token.form) != token.normalized_end - token.normalized_start
            or not all(is_modern_syllable(char) for char in token.form)):
        return None
    spans = token.morpheme_spans
    if spans and (len(spans) != len(parts) or any(
        len(span) != 2 or any(isinstance(value, bool) or not isinstance(value, int) for value in span)
        or not token.normalized_start <= span[0] <= span[1] <= token.normalized_end
        for span in spans
    ) or any(left[0] > right[0] or left[1] > right[1] for left, right in zip(spans, spans[1:]))):
        return None
    states = _licensed_states(parts, token.form)
    proofs = {}
    for state in states:
        proof = _proof(token, parts, spans, state)
        if proof is not None:
            deleted = tuple(sorted({origin for step in proof.steps for origin in step.deleted}))
            boundaries = tuple((step.boundary, step.rule_id, step.deleted)
                               for step in proof.steps if step.deleted)
            key = (proof.atoms, proof.regenerated_spans, deleted, boundaries, proof.deleted_occurrences)
            proofs.setdefault(key, proof)
    return next(iter(proofs.values())) if len(proofs) == 1 else None


def _observed_root_ownership_conflict(token, parts, spans):
    """유일한 실제 축약 증거에서 불변 원형과 형식 성분의 상호 소유 침범을 확인한다."""
    if not all(is_modern_syllable(char) for char in token.form):
        return False
    expected = unicodedata.normalize("NFD", token.form)
    witnesses = {}
    for state in _licensed_states(parts, token.form):
        if "".join(atom.jamo for atom in state.atoms) != expected:
            continue
        originals = _accounted_atoms(parts, state)
        if originals is None:
            continue
        key = (state.atoms, tuple((step.boundary, step.rule_id, step.deleted)
                                 for step in state.steps if step.deleted))
        witnesses.setdefault(key, (state, originals))
    if len(witnesses) != 1:
        # 서로 다른 전체 유래 증거에서 하나만 골라 모순을 만들지 않는다.
        return False
    state, originals = next(iter(witnesses.values()))
    syllables, cursor = [], 0
    for offset, character in enumerate(token.form, token.normalized_start):
        width = len(unicodedata.normalize("NFD", character))
        atoms = state.atoms[cursor:cursor + width]
        owners = {origin.occurrence for atom in atoms for origin in atom.origins}
        shared = any(len({origin.occurrence for origin in atom.origins}) > 1 for atom in atoms)
        syllables.append((offset, owners, shared))
        cursor += width
    if not any(shared for _, _, shared in syllables):
        return False
    formal_tags = SUFFIXES | ENDINGS | PARTICLES | {"XPN", "VCP"}
    for index, (form, tag) in enumerate(parts):
        if _base(tag) in formal_tags:
            continue
        live = tuple(atom for atom in state.atoms if any(origin.occurrence == index for origin in atom.origins))
        if live != originals[index]:
            continue
        positions = [offset for offset, owners, _ in syllables if index in owners]
        if (not positions or positions != list(range(positions[0], positions[0] + len(form)))
                or token.form[positions[0] - token.normalized_start:positions[-1] - token.normalized_start + 1] != form):
            continue
        begin, end = spans[index]
        if any(shared and index not in owners and begin <= offset < end
               for offset, owners, shared in syllables):
            return True
        # 형식 출현의 범위가 원형만 소유한 실제 음절을 주장하는 대칭 침범도 반증이다.
        exclusive = [offset for offset, owners, _ in syllables if owners == {index}]
        for other, (_, other_tag) in enumerate(parts):
            if other == index or _base(other_tag) not in formal_tags:
                continue
            begin, end = spans[other]
            if any(begin <= offset < end for offset in exclusive):
                return True
    return False


def surface_proof_conflict(token):
    """인증 대상의 명시 모순과 별도 계약이 필요한 활용을 구별한다."""
    if (isinstance(token.normalized_start, bool) or not isinstance(token.normalized_start, int)
            or isinstance(token.normalized_end, bool) or not isinstance(token.normalized_end, int)
            or not 0 <= token.normalized_start < token.normalized_end
            or len(token.form) != token.normalized_end - token.normalized_start):
        return True
    if not token.morphemes:
        # 원형 없는 결합 표면 태그는 새 인증의 신원 충돌이 아니라 세부 근거의 부재다.
        return False
    parts = token.morphemes
    if tuple(tag for _, tag in parts) != tuple(token.tag.split("+")) or any(not form for form, _ in parts):
        return True
    spans = token.morpheme_spans
    if spans and (len(spans) != len(parts) or any(
        len(span) != 2 or any(isinstance(value, bool) or not isinstance(value, int) for value in span)
        or not token.normalized_start <= span[0] <= span[1] <= token.normalized_end for span in spans
    )):
        return True
    if not spans:
        # 새 변환에 필요한 원시 근거의 부재를 기존 대응과의 모순으로 바꾸지 않는다.
        return False
    full_spans = tuple(span for span in spans if span[0] < span[1])
    if any(left[0] > right[0] or left[1] > right[1] for left, right in zip(full_spans, full_spans[1:])):
        return True
    markers = tuple(index for index, span in enumerate(spans) if span[0] == span[1])
    if markers:
        if verified_token_surface(token) is not None:
            return False
        # 분석기가 공유 음절 안에 둔 어미 종성의 영폭 표시는 전체 범위 증거가 아니다.
        # 이 경로는 새 표면 인증을 만들지 않고 기존의 정확한 말단 대응만 남긴다.
        return not all(
            parts[index][1] in ENDINGS
            and (parts[index][0][0] in _COMPATIBILITY_CODAS or _role(parts[index][0][0]) == "coda")
            and any(start <= spans[index][0] < end for start, end in spans[:index])
            for index in markers
        )
    originals = _canonical_atoms(parts)
    if originals is None:
        return False
    if unicodedata.normalize("NFC", "".join(atom.jamo for group in originals for atom in group)) == token.form:
        return True
    # 만들 수 있는 다른 활용 경로가 있다는 사실은 관측된 신원·범위의 모순이 아니다.
    # 강한 자모 소유를 증명하지 못한 근거는 기존 범주 권한의 반증으로 승격하지 않는다.
    return _observed_root_ownership_conflict(token, parts, spans)


def certified_formal_recipient(proof, offset, *, chain_parts=None):
    """공동 모음을 단독 소유로 바꾸지 않고 오른쪽 형식 사슬만 증명한다."""
    if proof is None or proof.start != offset or not proof.parts:
        return False
    parts = proof.parts if chain_parts is None else tuple(chain_parts)
    if parts[:len(proof.parts)] != proof.parts:
        return False
    first_tag = _base(parts[0][1])
    if first_tag not in SUFFIXES | ENDINGS or _grammar(parts, allow_auxiliary=False) is None:
        return False
    chain = []
    for index, (_, tag) in enumerate(parts):
        if _base(tag) in SUFFIXES | ENDINGS:
            chain.append(index)
        else:
            break
    onset = next((atom for atom in proof.atoms if atom.offset == offset and atom.role == "onset"), None)
    vowel = next((atom for atom in proof.atoms if atom.offset == offset and atom.role == "vowel"), None)
    return bool(onset is not None and onset.jamo == "ᄋ"
                and {origin.occurrence for origin in onset.origins} == {0}
                and all(origin.role == "onset" and origin.jamo == "ᄋ" for origin in onset.origins)
                and vowel is not None and vowel.origins
                and {origin.occurrence for origin in vowel.origins} <= set(chain))
