"""기존 네이티브 관찰은 보존하고 선언 좌표 입력 연결만 버전 2로 바꾼다."""

from __future__ import annotations

import sys
from contextlib import ExitStack
from unittest.mock import patch

import evaluator_binding_v2 as native
import input_binding_v2 as controlled_input


BINDING_VERSION = "r42-native-observation-v3-once-validated-input"
CALL_SITES = native.CALL_SITES
prepare_native_imports = native.prepare_native_imports
construct_invalid = native.construct_invalid


def word_certificate_targets():
    """이미 실제로 가져온 승인 별칭만 찾으며 새 프로젝트 가져오기를 하지 않는다."""
    targets = []
    for name in ("g2p_ko.korean.boundary_consumers", "g2p_ko.korean.word_roles"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "certify_word", None)):
            targets.append((name + ".certify_word", module, "certify_word"))
    return targets


def install_word_observers(stack, targets, observed):
    aliases = []
    for alias, owner, attribute in targets:
        original = getattr(owner, attribute)

        def wrapped(*args, _original=original, _alias=alias, **kwargs):
            result = _original(*args, **kwargs)
            start = args[1] if len(args) > 1 and type(args[1]) is int else kwargs.get("start")
            observed.append({"alias": _alias, "start_argument": start, "certificate": native.dto(result)})
            return result

        stack.enter_context(patch.object(owner, attribute, wrapped))
        aliases.append(alias)
    return aliases


def evaluate_native(payload, *, aliases=None, invoke=None, input_mode="tokens_only", word_targets=None):
    if aliases is None:
        aliases = prepare_native_imports()
    word_objects = []
    targets = word_certificate_targets() if word_targets is None else word_targets
    # 기존 직렬 실행기의 한 호출 동안만 입력 의존성을 교체하고 곧 복원한다.
    with ExitStack() as stack:
        wrapped_aliases = install_word_observers(stack, targets, word_objects)
        stack.enter_context(patch.object(native, "controlled_input", controlled_input))
        result = native.evaluate_native(payload, aliases=aliases, invoke=invoke, input_mode=input_mode)
    result["native_observer_version"] = result["binding_version"]
    result["binding_version"] = BINDING_VERSION
    result["input_binding_version"] = controlled_input.INPUT_BINDING_VERSION
    result["word_certificate_observation"] = {"status": "captured" if word_objects else "not_observed",
                                               "count": len(word_objects), "wrapped_aliases": wrapped_aliases,
                                               "objects": word_objects}
    result["native_evidence"]["actual_word_certificates"] = word_objects
    claims = [fact for fact in payload.get("dictionary_structure", ()) if fact.get("identity_claim") == "same_selected_identity"]
    result["input_preconditions"] = {"same_selected_identity_claims": claims,
                                     "semantic_identity_delivery": "not_delivered" if claims else "not_required"}
    return result


def evaluate(payload, *, input_mode="tokens_only"):
    return evaluate_native(payload, input_mode=input_mode)
