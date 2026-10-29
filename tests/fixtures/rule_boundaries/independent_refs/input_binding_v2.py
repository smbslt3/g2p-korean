"""최초 제공 분석을 한 번 검증하고 같은 원문의 허가된 투영에 좌표만 잇는다."""

from __future__ import annotations

from unittest.mock import patch

import input_binding_v1 as original


INPUT_BINDING_VERSION = "r42-declared-source-coordinates-v2"


class InputBindingError(original.InputBindingError):
    """원문·실제 소유 범위 또는 최초 제공 분석의 검증이 실패한 경우다."""


def owned_ranges(tokens, text, source):
    """후속 원형의 신원을 재발명하지 않고 실제 토큰 소유 좌표만 확인한다."""
    if text != source:
        raise InputBindingError("후속 Annotation도 최초 통제 원문과 같은 text여야 합니다.")
    spans = []
    observed = []
    for token in tokens:
        start, end = token.normalized_start, token.normalized_end
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source):
            raise InputBindingError("실제 후속 토큰의 소유 좌표가 원문 범위를 벗어났습니다.")
        if not isinstance(token.form, str) or not token.form or not isinstance(token.tag, str) or not token.tag:
            raise InputBindingError("실제 후속 토큰의 형식/태그가 비어 있습니다.")
        spans.append((start, end))
        observed.append({"form": token.form, "tag": token.tag, "span": [start, end]})
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged, observed


def install_annotation_input(stack, morphology, payload, mode):
    if mode not in ("tokens_only", "controlled_structure_supplied"):
        raise InputBindingError("알려지지 않은 입력 모드입니다.")
    try:
        facts = original.declared_compounds(payload)
    except original.InputBindingError as error:
        raise InputBindingError(str(error)) from error
    receipt = {"input_binding_version": INPUT_BINDING_VERSION, "mode": mode,
               "declared_nominal_compounds": facts, "constructor_calls": [],
               "initial_validation": {"status": "not_requested", "count": 0},
               "dictionary_structure_injected": False, "other_relations_injected": False,
               "status": "declared_facts_not_delivered" if facts else "no_declared_nominal_compounds"}
    if mode == "tokens_only" or not facts:
        return receipt
    annotation_class = morphology._Annotation
    descriptor = annotation_class.__dict__.get("from_tokens")
    if not isinstance(descriptor, classmethod):
        raise InputBindingError("승인된 공통 from_tokens classmethod를 찾지 못했습니다.")
    native_constructor = descriptor.__func__
    declared = frozenset(f["source_boundary"] for f in facts)
    state = {"initial_validated": False}

    def from_tokens(cls, tokens, text="", compound_boundaries=frozenset(), nasal_liquid_boundaries=frozenset()):
        tokens = tuple(tokens)
        ranges, observed = owned_ranges(tokens, text, payload["source"])
        initial = not state["initial_validated"]
        if initial:
            try:
                original.validate_tokens(payload, tokens, text)
            except original.InputBindingError as error:
                raise InputBindingError(str(error)) from error
            state["initial_validated"] = True
            receipt["initial_validation"] = {"status": "validated_original_provider", "count": 1,
                                             "text": text, "token_count": len(tokens)}
        if not isinstance(compound_boundaries, frozenset) or any(type(i) is not int for i in compound_boundaries):
            raise InputBindingError("원래 compound_boundaries의 형식이 승인된 계약과 다릅니다.")
        # 한 경계의 양쪽 물리 음절이 같은 실제 소유 구간에 있을 때만 전달한다.
        deliverable = frozenset(b for b in declared if any(start <= b - 1 and b < end for start, end in ranges))
        skipped = declared - deliverable
        result = native_constructor(cls, tokens, text=text, compound_boundaries=compound_boundaries | deliverable,
                                    nasal_liquid_boundaries=nasal_liquid_boundaries)
        if not isinstance(result, cls) or result.text != text or not deliverable.issubset(result.compound_boundaries):
            raise InputBindingError("실제 소유 범위 안의 선언 좌표가 네이티브 Annotation에 전달되지 않았습니다.")
        receipt["constructor_calls"].append({"text": text, "initial_provider_validation": initial,
                                               "actual_owned_ranges": ranges, "actual_tokens": observed,
                                               "original_compound_boundaries": sorted(compound_boundaries),
                                               "validated_declared_boundaries": sorted(declared),
                                               "added_declared_boundaries": sorted(deliverable),
                                               "skipped_outside_owned_range": sorted(skipped),
                                               "delivered_compound_boundaries": sorted(result.compound_boundaries),
                                               "native_class": type(result).__module__ + "." + type(result).__qualname__,
                                               "tokens_preserved": True,
                                               "nasal_liquid_boundaries_preserved": result.nasal_liquid_boundaries == nasal_liquid_boundaries})
        receipt["status"] = "controlled_structure_supplied"
        return result

    stack.enter_context(patch.object(annotation_class, "from_tokens", classmethod(from_tokens)))
    return receipt
