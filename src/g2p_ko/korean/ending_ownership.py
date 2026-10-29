# SPDX-License-Identifier: MIT
"""어미의 원형 자모를 표면 좌표에 대응시켜 제27항의 소유를 판정한다."""

from __future__ import annotations

from dataclasses import dataclass
import unicodedata

from ..model import AnalysisToken
from .surface_proof import surface_proof_conflict, verified_token_surface


@dataclass(frozen=True, slots=True)
class _Owner:
    """표면의 한 음운 성분에 대응한 원형 형태소다."""

    form: str
    tag: str


def _certified_owners(proof):
    """출현 집합이 하나인 인증 자모만 기존 단독 소유 API로 투영한다."""
    result = {}
    for atom in proof.atoms:
        occurrences = {origin.occurrence for origin in atom.origins}
        if len(occurrences) == 1:
            index = next(iter(occurrences))
            result[(atom.offset, atom.role)] = _Owner(*proof.parts[index])
    return result


def _surface_atoms(token: AnalysisToken) -> tuple[tuple[str, int, str], ...]:
    """분해 자모마다 원래 정규화 문자 좌표와 음절 내 역할을 보존한다."""

    atoms = []
    for offset, character in enumerate(token.form, token.normalized_start):
        for jamo in unicodedata.normalize("NFD", character):
            value = ord(jamo)
            role = (
                "onset" if 0x1100 <= value <= 0x1112
                else "vowel" if 0x1161 <= value <= 0x1175
                else "coda" if 0x11A8 <= value <= 0x11C2
                else "other"
            )
            atoms.append((jamo, offset, role))
    return tuple(atoms)


def _source_owners(token: AnalysisToken) -> dict[tuple[int, str], _Owner]:
    """끝에서 일치하는 원형만 배정하여 어간 길이와 겹침 길이를 혼동하지 않는다."""

    proof = verified_token_surface(token)
    if proof is not None and (token.morphemes or "ETM" not in token.tag.split("+")):
        return _certified_owners(proof)
    if proof is None and surface_proof_conflict(token):
        return {}
    atoms = _surface_atoms(token)
    tags = tuple(part.strip() for part in token.tag.split("+"))
    # 옛 제공 분석에는 원형이 없는 결합 태그가 있다. 이 태그만으로는
    # 내부 어미 경계를 증명할 수 없으므로 어간 부분에 E 소유를 주지 않는다.
    ordinary_tag = "+".join(tag for tag in tags if not tag.startswith("E"))
    ordinary_owner = _Owner(token.form, ordinary_tag)
    owners = {(offset, role): ordinary_owner for _, offset, role in atoms}

    if not token.morphemes:
        if tags and all(tag.startswith("E") for tag in tags) and "ETM" not in tags:
            # 단독 어미 토큰은 제공 분석이 어미 자체의 원문 범위를 명시한다.
            owner = _Owner(token.form, token.tag)
            return {(offset, role): owner for _, offset, role in atoms}
        if "ETM" in tags:
            # 원형 없는 관형형 태그의 호환 범위는 표면 끝의 ㄹ 받침뿐이다.
            for jamo, offset, role in atoms:
                if offset == token.normalized_end - 1 and role == "coda" and jamo == "ᆯ":
                    owners[(offset, role)] = _Owner("ㄹ", "ETM")
        return owners

    if tags != tuple(tag for _, tag in token.morphemes):
        return owners

    source_jamo = tuple(jamo for jamo, _, _ in atoms)
    cursor = len(atoms)
    for form, tag in reversed(token.morphemes):
        # 호환 ㄹ과 종성 ᆯ은 같은 어미 성분이다. 완성형 음절은 NFD로
        # 대응하므로 보+ㄹ과 볼이 길이가 달라도 실제 받침 좌표를 찾는다.
        jamo = tuple(unicodedata.normalize("NFD", form.replace("ㄹ", "ᆯ")))
        alternatives = [jamo]
        if tag.startswith("E") and form.startswith("을"):
            # -(으)ㄹ의 으 없는 표면 이형태도 받침부터 정확히 대조한다.
            alternatives.append(jamo[2:])
        matched = next((part for part in alternatives if part and len(part) <= cursor
                        and source_jamo[cursor - len(part):cursor] == part), None)
        if matched is None:
            # 활용 축약으로 앞쪽 원형이 다르더라도 이미 확인한 끝부분의
            # 소유는 보존한다. 불일치 구간을 길이로 건너뛰지 않는다.
            break
        start = cursor - len(matched)
        owner = _Owner(form, tag)
        for _, offset, role in atoms[start:cursor]:
            owners[(offset, role)] = owner
        cursor = start
    return owners


def source_owner(token: AnalysisToken, offset: int, role: str) -> _Owner | None:
    """주어진 표면 음운 성분을 실제로 소유한 원형을 반환한다."""

    return _source_owners(token).get((offset, role))


def verified_morpheme_surfaces(token: AnalysisToken):
    """정확한 비중첩 원시 범위에서 직접 일치·아/어 어미 대응만 확인한다.

    원형의 첫 어/아 모음만 대응시키며 초성·받침·나머지 표면은 같아야 한다.
    겹침·축약이나 다른 품사의 표면 차이는 이 경로로 소유하지 않는다.
    """
    if verified_token_surface(token) is None and surface_proof_conflict(token):
        return None
    parts, spans = token.morphemes, token.morpheme_spans
    if (not parts or len(parts) != len(spans)
            or tuple(tag for _, tag in parts) != tuple(token.tag.split("+"))):
        return None
    cursor, result = token.normalized_start, []
    for (form, tag), (start, end) in zip(parts, spans):
        if start != cursor or not start < end <= token.normalized_end:
            return None
        surface = token.form[start-token.normalized_start:end-token.normalized_start]
        if form != surface:
            if (tag not in {"EP", "EF", "EC", "ETM", "ETN"}
                    or not form or not surface or form[1:] != surface[1:]):
                return None
            original = unicodedata.normalize("NFD", form[0])
            observed = unicodedata.normalize("NFD", surface[0])
            if (len(original) < 2 or len(observed) < 2
                    or original[0] != "ᄋ" or observed[0] != "ᄋ"
                    or {original[1], observed[1]} != {"ᅡ", "ᅥ"}
                    or original[2:] != observed[2:]):
                return None
        result.append((form, tag, start, end, surface))
        cursor = end
    return tuple(result) if cursor == token.normalized_end else None


def verified_source_owners(token: AnalysisToken) -> dict[tuple[int, str], _Owner]:
    """기본 잔여 배정 없이 직접 대응한 원형 자모의 소유만 반환한다.

    융합 앞부분의 전체 활용을 복원하지 않아도 이미 일치한 말단은 남긴다.
    마지막 음절 내부의 부분 대응은 실제 겹침 범위가 보존된 경우만 쓴다.
    """
    proof = verified_token_surface(token)
    if proof is not None:
        return _certified_owners(proof)
    if surface_proof_conflict(token):
        return {}
    atoms = _surface_atoms(token)
    surfaces = verified_morpheme_surfaces(token)
    if surfaces is not None:
        # 검증한 성분 대응을 원래 canonical 형태소 소유자로 기록한다.
        return {(offset, role): _Owner(form, tag)
                for form, tag, start, end, _ in surfaces
                for _, offset, role in atoms if start <= offset < end}
    parts = token.morphemes or ((token.form, token.tag),)
    if tuple(tag for _, tag in parts) != tuple(token.tag.split("+")):
        return {}
    owners = {}
    compatibility = {"ㄴ": "ᆫ", "ㄹ": "ᆯ", "ㅁ": "ᆷ", "ㅂ": "ᆸ", "ㅆ": "ᆻ"}
    def jamo(form):
        return tuple(unicodedata.normalize("NFD", "".join(compatibility.get(c, c) for c in form)))
    source = tuple(atom[0] for atom in atoms)
    cursor = len(atoms)
    for index in range(len(parts)-1, -1, -1):
        form, tag = parts[index]
        original = jamo(form)
        alternatives = [original]
        if tag in {"EP", "EF", "EC", "ETM", "ETN"} and form.startswith("을"):
            alternatives.append(original[2:])
        matched = next((part for part in alternatives if part and len(part) <= cursor
                        and source[cursor-len(part):cursor] == part), None)
        if matched is None:
            # 원시 겹침은 소실된 초성·모음을 발명하지 않는다. 실제 끝 자모가
            # 해당 성분 범위 안에 있고 다른 원형과 경쟁하지 않을 때만 보존한다.
            if not token.morpheme_spans or index == 0:
                break
            start, end = token.morpheme_spans[index]
            previous_start, previous_end = token.morpheme_spans[index-1]
            if not start < previous_end or tag not in {"EP", "EF", "EC", "ETM", "ETN"}:
                break
            count = 0
            while (count < min(len(original), cursor)
                   and original[-count-1] == source[cursor-count-1]
                   and start <= atoms[cursor-count-1][1] < end):
                count += 1
            if count:
                for atom in atoms[cursor-count:cursor]:
                    if atom[2] != "coda":
                        continue
                    # 같은 원시 위치를 덮는 이전 성분의 종성과 같으면 경쟁 소유다.
                    competing = any(atom[0] == jamo(prior)[-1]
                        and prior_span[0] <= atom[1] < prior_span[1]
                        for (prior, _), prior_span in zip(parts[:index], token.morpheme_spans[:index])
                        if jamo(prior) and 0x11A8 <= ord(jamo(prior)[-1]) <= 0x11C2)
                    if not competing:
                        owners[(atom[1], atom[2])] = _Owner(form, tag)
            break
        for _, offset, role in atoms[cursor-len(matched):cursor]:
            owners[(offset, role)] = _Owner(form, tag)
        cursor -= len(matched)
    # 직접 앞부분 대응도 보존한다. 뒤쪽 불일치의 길이로 건너뛰지 않는다.
    cursor = 0
    for form, tag in parts:
        original = jamo(form)
        if not original or source[cursor:cursor+len(original)] != original:
            break
        for _, offset, role in atoms[cursor:cursor+len(original)]:
            key = (offset, role)
            owner = _Owner(form, tag)
            if key in owners and owners[key] != owner:
                owners.pop(key)
            else:
                owners[key] = owner
        cursor += len(original)
    return owners


def ending_coda_owner(token: AnalysisToken, offset: int) -> _Owner | None:
    """제27항의 근거가 되는 ㄹ 받침의 어미 소유만 반환한다."""

    atoms = _surface_atoms(token)
    if not any(jamo == "ᆯ" and position == offset and role == "coda"
               for jamo, position, role in atoms):
        return None
    owner = source_owner(token, offset, "coda")
    if owner is None or not any(tag.startswith("E") for tag in owner.tag.split("+")):
        return None
    return owner
