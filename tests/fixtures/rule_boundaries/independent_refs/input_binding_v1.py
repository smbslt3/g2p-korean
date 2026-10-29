"""이미 선언된 명사 합성 사실만 실제 공통 Annotation 생성자에 공급한다."""

from __future__ import annotations

from unittest.mock import patch


class InputBindingError(ValueError):
    """선언 입력의 소유·범위·태그 또는 실제 전달을 확인하지 못한 경우다."""


def declared_compounds(payload):
    parts = payload["canonical_parts"]
    identities = [p["id"] for p in parts]
    if len(set(identities)) != len(identities):
        raise InputBindingError("원형 출현 ID가 중복됩니다.")
    by_id = {p["id"]: p for p in parts}
    positions = {p["id"]: i for i, p in enumerate(parts)}
    facts = []
    for index, fact in enumerate(payload.get("grammatical_structure", ())):
        if fact.get("relation") != "nominal_compound":
            continue
        left_id = fact.get("left")
        right_ids = fact.get("right_parts")
        if right_ids is None:
            right_ids = [fact.get("right")]
        if not isinstance(right_ids, (list, tuple)) or not right_ids or left_id not in by_id or any(i not in by_id for i in right_ids):
            raise InputBindingError("선언된 명사 합성의 원형 ID가 명확하지 않습니다.")
        expected_positions = list(range(positions[left_id] + 1, positions[left_id] + 1 + len(right_ids)))
        if [positions[i] for i in right_ids] != expected_positions:
            raise InputBindingError("명시한 좌우 성분의 원형 순서가 인접하지 않습니다.")
        group = [by_id[left_id]] + [by_id[i] for i in right_ids]
        for part in group:
            span = part["span"]
            if (len(span) != 2 or any(type(v) is not int for v in span)
                    or not 0 <= span[0] < span[1] <= len(payload["source"])
                    or not isinstance(part["form"], str) or not part["form"]
                    or not isinstance(part["tag"], str) or not part["tag"]):
                raise InputBindingError("선언 원형의 신원·태그·범위가 올바르지 않습니다.")
        if any(a["span"][1] != b["span"][0] for a, b in zip(group, group[1:])):
            raise InputBindingError("선언된 합성 성분의 표면 범위가 정확히 인접하지 않습니다.")
        coordinate = group[1]["span"][0]
        if not 0 < coordinate < len(payload["source"]):
            raise InputBindingError("선언한 합성 경계가 단어 내부에 없습니다.")
        facts.append({"declaration_index": index, "relation": "nominal_compound", "left": left_id,
                      "right_parts": list(right_ids), "source_boundary": coordinate,
                      "owned_parts": [{"id": p["id"], "form": p["form"], "tag": p["tag"], "span": list(p["span"])} for p in group]})
    return facts


def validate_tokens(payload, tokens, text):
    if text != payload["source"]:
        raise InputBindingError("실제 Annotation의 text가 통제 원문과 다릅니다.")
    supplied = payload["analysis_tokens"]
    if len(tokens) != len(supplied):
        raise InputBindingError("실제 생성자 토큰 수가 제공 분석과 다릅니다.")
    flattened = []
    for token, wanted in zip(tokens, supplied):
        actual = (token.form, token.tag, token.normalized_start, token.normalized_end,
                  tuple(tuple(x) for x in token.morphemes), tuple(tuple(x) for x in token.morpheme_spans))
        expected = (wanted["form"], wanted["tag"], wanted["start"], wanted["end"],
                    tuple(tuple(x) for x in wanted["morphemes"]), tuple(tuple(x) for x in wanted["morpheme_spans"]))
        if actual != expected or text[token.normalized_start:token.normalized_end] != token.form:
            raise InputBindingError("실제 토큰의 신원·태그·소유 범위가 제공 분석과 다릅니다.")
        if len(token.morphemes) != len(token.morpheme_spans):
            raise InputBindingError("원형과 원시 범위의 수가 다릅니다.")
        flattened.extend((m[0], m[1], tuple(span)) for m, span in zip(token.morphemes, token.morpheme_spans))
    canonical = [(p["form"], p["tag"], tuple(p["span"])) for p in payload["canonical_parts"]]
    if flattened != canonical:
        raise InputBindingError("제공 원형 ID 순서의 신원·태그·범위가 실제 토큰 원형과 대응하지 않습니다.")


def install_annotation_input(stack, morphology, payload, mode):
    if mode not in ("tokens_only", "controlled_structure_supplied"):
        raise InputBindingError("알려지지 않은 입력 모드입니다.")
    facts = declared_compounds(payload)
    receipt = {"mode": mode, "declared_nominal_compounds": facts, "constructor_calls": [],
               "dictionary_structure_injected": False, "other_relations_injected": False,
               "status": "declared_facts_not_delivered" if facts else "no_declared_nominal_compounds"}
    if mode == "tokens_only" or not facts:
        return receipt
    annotation_class = morphology._Annotation
    descriptor = annotation_class.__dict__.get("from_tokens")
    if not isinstance(descriptor, classmethod):
        raise InputBindingError("승인된 공통 from_tokens classmethod를 찾지 못했습니다.")
    original = descriptor.__func__
    declared = frozenset(f["source_boundary"] for f in facts)

    def from_tokens(cls, tokens, text="", compound_boundaries=frozenset(), nasal_liquid_boundaries=frozenset()):
        tokens = tuple(tokens)
        validate_tokens(payload, tokens, text)
        if not isinstance(compound_boundaries, frozenset) or any(type(i) is not int for i in compound_boundaries):
            raise InputBindingError("원래 compound_boundaries의 형식이 승인된 계약과 다릅니다.")
        combined = compound_boundaries | declared
        result = original(cls, tokens, text=text, compound_boundaries=combined,
                          nasal_liquid_boundaries=nasal_liquid_boundaries)
        delivered = result.compound_boundaries
        if not isinstance(result, cls) or result.text != text or not declared.issubset(delivered):
            raise InputBindingError("실제 Annotation에 선언한 합성 사실이 전달되지 않았습니다.")
        receipt["constructor_calls"].append({"text": text, "original_compound_boundaries": sorted(compound_boundaries),
                                               "declared_boundaries": sorted(declared), "delivered_compound_boundaries": sorted(delivered),
                                               "native_class": type(result).__module__ + "." + type(result).__qualname__,
                                               "tokens_preserved": True, "nasal_liquid_boundaries_preserved": result.nasal_liquid_boundaries == nasal_liquid_boundaries})
        receipt["status"] = "controlled_structure_supplied"
        return result

    stack.enter_context(patch.object(annotation_class, "from_tokens", classmethod(from_tokens)))
    return receipt
