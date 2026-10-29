# SPDX-License-Identifier: MIT
"""원형 출현열만으로 숙주·꼬리와 경계별 변환 권한을 확인한다."""

from dataclasses import dataclass


ENDINGS = frozenset({"EP", "EF", "EC", "ETM", "ETN"})
SUFFIXES = frozenset({"XSN", "XSV", "XSA", "XSM"})
PARTICLES = frozenset({"JKS", "JKC", "JKG", "JKO", "JKB", "JKV", "JKQ", "JX", "JC"})
PARTICLE_HOST_DOMAINS = {
    tag: frozenset({"nominal", "nominalized"})
    for tag in {"JKS", "JKC", "JKG", "JKO", "JKB", "JKV"}
}
_TYPED_LEXICAL_HOSTS = frozenset({"nominal", "nominalized", "predicate", "adverbial",
                                   "modifier", "final", "connective", "adnominal"})
VARIABLES = frozenset({"VV", "VA", "VX", "XSV", "XSA"})
NOUNS = frozenset({"NNG", "NNP", "NNB", "NNBC", "NP", "NR"})
INDEPENDENT_CATEGORIES = frozenset({"noun", "verb", "adjective", "adverb", "modifier"})
BASES = {**dict.fromkeys(NOUNS, "noun"), "XR": "root", "VV": "verb", "VX": "verb",
         "VA": "adjective", "MAG": "adverb", "MAJ": "adverb", "MM": "modifier",
         "IC": "interjection", "VCN": "adjective"}
DERIVATIONS = {
    "XSN": (frozenset({"root", "noun", "verb", "adjective", "adverb"}), "noun"),
    "XSV": (frozenset({"root", "noun", "adverb"}), "verb"),
    "XSA": (frozenset({"root", "noun", "adverb"}), "adjective"),
    "XSM": (frozenset({"root", "noun", "verb", "adjective", "adverb"}), "adverb"),
}


def base_tag(tag):
    """원래 표지를 보존한 채 선언된 용언의 품사만 비교한다."""
    return tag[:-2] if tag.endswith(("-I", "-R")) and tag[:-2] in VARIABLES else tag


@dataclass(frozen=True, slots=True)
class BoundaryLicense:
    """표면 변환기가 쓸 수 있는 원래 경계와 활성 어간의 범위다."""

    inflection: bool = False
    causative: bool = False
    stem_start: int = 0
    active_ha: bool = False
    negative_auxiliary: bool = False


@dataclass(frozen=True, slots=True)
class GrammarResult:
    """파싱 실패도 부분 상태와 그 이유를 잃지 않는 자료다."""

    lexical_status: str
    final_category: str | None
    host_state: str
    tail_state: str
    reason: str
    boundaries: tuple[BoundaryLicense, ...]
    basis_tag: str | None = None
    prefixed: bool = False
    derived: bool = False
    all_noun: bool = False
    possible_categories: frozenset[str] = frozenset()
    core_starts: tuple[int, ...] = (0,)


def parse_parts(parts, *, fragment=False, allow_auxiliary=True, initial_host=None):
    """형식 조각과 독립 단어 모드가 같은 유형별 전이를 공유한다."""
    parts = tuple(parts)
    boundaries = [BoundaryLicense() for _ in parts]
    category, host, tail, basis = None, "unknown", "unknown", None
    prefixed, derived, independent, all_noun = False, False, False, False
    possible = frozenset()
    core_starts = [0]

    def result(status, reason):
        return GrammarResult(status, category, host, tail, reason, tuple(boundaries),
                             basis, prefixed, derived, all_noun, possible, tuple(core_starts))

    if not parts or any(not form or not tag or "+" in tag for form, tag in parts):
        return result("unresolved", "original_parts_unavailable")
    index = 0
    while index < len(parts) and parts[index][1] == "XPN":
        index += 1
    prefixed = index > 0
    if index == len(parts):
        host, tail = "formal", "none"
        return result("excluded", "independent_basis_absent")
    basis = base_tag(parts[index][1])
    if initial_host is not None:
        # 이미 소유·신원이 확인된 명사의 바깥 꼬리를 가짜 원형 없이 검사한다.
        if initial_host != "nominal" or prefixed:
            return result("unresolved", "initial_host_unproven")
        index, basis, host, tail, independent = -1, None, "nominal", "none", True
    elif basis in BASES:
        category = BASES[basis]
        independent = category in INDEPENDENT_CATEGORIES
        host = {"noun": "nominal", "verb": "predicate", "adjective": "predicate",
                "adverb": "adverbial", "modifier": "modifier", "root": "root"}.get(category, "formal")
        tail = "none"
    elif not prefixed and basis in SUFFIXES | ENDINGS | PARTICLES | {"VCP"}:
        # 형식 조각의 표면 인증과 독립 단어 권한은 서로 다른 모드다.
        if not fragment:
            host, tail = "formal", "none"
            return result("excluded", "independent_basis_absent")
        host, tail = "formal", "none"
        if basis in SUFFIXES:
            category = DERIVATIONS[basis][1]
            host = {"noun": "nominal", "verb": "predicate", "adjective": "predicate",
                    "adverb": "adverbial"}[category]
        elif basis in ENDINGS:
            category = "verb"
            host = {"EP": "predicate", "EF": "final", "EC": "connective",
                    "ETM": "adnominal", "ETN": "nominalized"}[basis]
            tail = {"EP": "prefinal", "EF": "final", "EC": "connective",
                    "ETM": "adnominal", "ETN": "nominalized"}[basis]
        elif basis == "VCP":
            category, host, tail = "noun", "predicate", "open_inflection"
    else:
        return result("unresolved", "unsupported_basis_tag")

    if prefixed and independent:
        category, host = None, "lexical_unknown"
        possible = INDEPENDENT_CATEGORIES
    elif category is not None:
        possible = frozenset({category})
    # 정확한 전체 명사열의 수신 적격성만 남기며 접미사의 범위를 추론하지 않는다.
    if initial_host is None and not prefixed and all(base_tag(tag) in NOUNS for _, tag in parts):
        all_noun, category, host, tail = True, "noun", "nominal", "none"
        return result("eligible", "whole_nominal_recipient")
    if initial_host is None and not prefixed and all(tag == "MAG" for _, tag in parts):
        category, host, tail = "adverb", "adverbial", "none"
        return result("eligible", "whole_adverbial_recipient")

    stem_start, family, particles, case_seen = 0, "", False, False
    ending_seen = basis in ENDINGS
    terminal = basis in ENDINGS - {"EP"}
    if basis == "VCP":
        family = "copula_"
    for current in range(index + 1, len(parts)):
        form, tag = parts[current]
        tag_base = base_tag(tag)
        left_form, left_tag = parts[current - 1]
        left_base = base_tag(left_tag)
        if host == "lexical_unknown":
            # 단일 기반 밖의 형식 꼬리는 유일한 바깥 결합의 숙주를 증명한다.
            # 이 증명은 접두 결합 이전 품사를 결과 품사로 복사하지 않는다.
            if current == index + 1 and tag in ENDINGS:
                host, possible = "predicate", frozenset({"verb", "adjective"})
            elif current == index + 1 and tag == "VCP":
                host = "nominal"
            elif current == index + 1 and tag in PARTICLES:
                following_tags = tuple(part_tag for _, part_tag in parts[current:])
                if all(part_tag in PARTICLES for part_tag in following_tags):
                    if any(part_tag != "JX" for part_tag in following_tags):
                        host = "nominal"
                    else:
                        particles, tail = True, "particles"
                        continue
                else:
                    return result("unresolved", "prefixed_tail_scope_unproven")
            elif particles and tag == "JX":
                continue
            else:
                return result("unresolved", "prefixed_host_category_unproven")
        if tag in PARTICLES:
            if host in {"nominal", "nominalized"}:
                if tag != "JX" and case_seen:
                    return result("unresolved", "particle_stacking_unproven")
                case_seen = case_seen or tag != "JX"
            elif host in {"adverbial", "final", "connective"} and tag == "JX":
                pass
            elif (tag in PARTICLE_HOST_DOMAINS and host in _TYPED_LEXICAL_HOSTS
                  and not ({host} & PARTICLE_HOST_DOMAINS[tag])):
                return result("excluded", "particle_host_excluded")
            else:
                return result("unresolved", "particle_host_unproven")
            particles, tail = True, family + "particles"
            continue
        if particles:
            return result("excluded", "content_after_particle_chain")
        if tag_base == "VX" and left_tag == "EC":
            if not allow_auxiliary:
                return result("unresolved", "auxiliary_structure_unavailable")
            boundaries[current] = BoundaryLicense(
                stem_start=stem_start,
                negative_auxiliary=parts[current - 1] == ("지", "EC") and (form, tag) == ("않", "VX"),
            )
            category, possible, host = "verb", frozenset({"verb"}), "predicate"
            family, tail, stem_start = "auxiliary_", "auxiliary_open", current
            ending_seen, terminal = False, False
            core_starts.append(current)
            continue
        if tag_base in SUFFIXES:
            if prefixed:
                return result("unresolved", "prefixed_derivation_scope_unproven")
            if ending_seen or family:
                return result("excluded", "derivation_after_inflection")
            inputs, output = DERIVATIONS[tag_base]
            verbal_suffix = (tag_base == "XSV" and form in {"이", "히"} and category in {"verb", "adjective"}
                             and not tag.endswith("-I"))
            causative = verbal_suffix and form == "이"
            if category not in inputs and not verbal_suffix:
                return result("excluded", "derivation_input_excluded")
            boundaries[current] = BoundaryLicense(causative=causative, stem_start=stem_start)
            category, possible, independent, derived = output, frozenset({output}), True, True
            host = {"noun": "nominal", "verb": "predicate", "adjective": "predicate",
                    "adverb": "adverbial"}[output]
            tail = "derivation"
            continue
        if tag == "VCP":
            if form != "이":
                return result("unresolved", "copula_identity_unproven")
            if host not in {"nominal", "nominalized"}:
                return result("excluded", "copula_host_excluded")
            if current + 1 == len(parts) or parts[current + 1][1] not in ENDINGS:
                return result("excluded", "copula_ending_absent")
            family, host, tail, stem_start = "copula_", "predicate", "open_inflection", current
            ending_seen, terminal = False, False
            continue
        if tag in ENDINGS:
            if terminal:
                return result("unresolved", "ending_after_terminal")
            if host != "predicate":
                return result("excluded", "ending_host_excluded")
            boundaries[current] = BoundaryLicense(
                inflection=left_base in VARIABLES or left_tag in ENDINGS,
                stem_start=stem_start,
                # 독립 용언의 원형 또는 실제 파생 구조 안의 하만 활성 어간이다.
                active_ha=(left_form.endswith("하")
                           and not left_tag.endswith("-I")
                           and (left_base in {"VV", "VA", "VX"}
                                or left_form == "하" and left_base in {"XSV", "XSA"} and derived)),
            )
            ending_seen, terminal = True, tag != "EP"
            host = {"EP": "predicate", "EF": "final", "EC": "connective",
                    "ETM": "adnominal", "ETN": "nominalized"}[tag]
            tail = family + {"EP": "prefinal", "EF": "final", "EC": "connective",
                             "ETM": "adnominal", "ETN": "nominalized"}[tag]
            continue
        return result("unresolved", "unowned_content_or_unsupported_structure")
    if not independent:
        return result("excluded", "independent_basis_absent")
    if prefixed and ending_seen and not terminal:
        return result("unresolved", "prefixed_inflection_incomplete")
    if host == "predicate" and not ending_seen and tail == "none":
        tail = "open_inflection"
    return result("eligible", "complete_grammatical_word")
