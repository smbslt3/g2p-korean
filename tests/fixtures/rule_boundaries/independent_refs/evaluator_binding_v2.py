"""고정된 제03 후보의 실제 인증·적용·발음 호출을 관찰한다."""

from __future__ import annotations

import importlib
import importlib.util
import json
from contextlib import ExitStack
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from unittest.mock import patch

import input_binding_v1 as controlled_input


ROOT = Path(__file__).resolve().parent
BINDING_VERSION = "r42-native-observation-v2-candidate04-api"
CALL_SITES = {"certify": ["g2p_ko.korean.morphology", "certify_rule_boundaries"],
              "apply": ["g2p_ko.korean.engine", "apply_rule_boundaries"],
              "lexical": ["g2p_ko.korean.engine", "_apply_lexical_pronunciations"],
              "record": ["g2p_ko.korean.engine", "_record"]}
TAILS = ("", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ", "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ")
SOURCE_ALIASES = {"direct_analysis": "direct_analysis", "analysis": "direct_analysis",
                  "analysis_local_attachment": "direct_analysis",
                  "exact_identity_dictionary_structure": "exact_identity_dictionary_structure",
                  "dictionary_structure": "exact_identity_dictionary_structure"}
_PUBLIC_HELPER = None


def dto(value):
    """실제 DTO의 원시 범위·재생성 범위·삭제·공동 유래를 그대로 보존한다."""
    if isinstance(value, Enum):
        return dto(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: dto(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict):
        return {str(k): dto(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [dto(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((dto(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise TypeError("알려지지 않은 네이티브 DTO를 문자열 근거로 대체하지 않습니다.")


def load_public_helper():
    global _PUBLIC_HELPER
    if _PUBLIC_HELPER is not None:
        return _PUBLIC_HELPER
    spec = importlib.util.spec_from_file_location("r42_public_helper_native_v2", ROOT / "public_entrypoints_helper.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _PUBLIC_HELPER = module
    return module


def prepare_native_imports():
    """실제 실행이 허가된 원본 선택 문맥 안에서만 호출한다."""
    return {"morphology": importlib.import_module("g2p_ko.korean.morphology"),
            "engine": importlib.import_module("g2p_ko.korean.engine"),
            "pipeline": importlib.import_module("g2p_ko.pipeline")}


class Capture:
    """실제 호출의 반환 기록만 수집하며 기대값을 받지 않는다."""

    def __init__(self, aliases, payload, input_mode):
        self.aliases = aliases
        self.payload = payload
        self.input_mode = input_mode
        self.input_delivery = None
        self.native_api_available = {}
        self.certifications = []
        self.applications = []
        self.pronunciations = []
        self.lexical_calls = []
        self.lexical_records = []
        self.lexical_active = 0

    def install(self, stack):
        morphology, engine, pipeline = (self.aliases[k] for k in ("morphology", "engine", "pipeline"))
        self.input_delivery = controlled_input.install_annotation_input(stack, morphology, self.payload, self.input_mode)
        original_certify = getattr(morphology, "certify_rule_boundaries", None)
        original_apply = getattr(engine, "apply_rule_boundaries", None)
        self.native_api_available = {"certify": callable(original_certify), "apply": callable(original_apply)}
        original_lexical = engine._apply_lexical_pronunciations
        original_record = engine._record

        def certify(*args, **kwargs):
            result = original_certify(*args, **kwargs)
            self.certifications.append(dto(result))
            return result

        def apply(*args, **kwargs):
            supplied = dto(args[0] if args else kwargs["boundaries"])
            result = original_apply(*args, **kwargs)
            self.applications.append({"boundaries": supplied, "events": dto(result)})
            return result

        def lexical(*args, **kwargs):
            matches = args[1] if len(args) > 1 else kwargs["matches"]
            self.lexical_calls.append({"matches": dto(matches)})
            self.lexical_active += 1
            try:
                return original_lexical(*args, **kwargs)
            finally:
                self.lexical_active -= 1

        def record(*args, **kwargs):
            if self.lexical_active:
                self.lexical_records.append({"left": args[2], "right": args[3],
                                             "before": dto(args[4]), "rule_id": args[5]})
            return original_record(*args, **kwargs)

        def pronunciation(original, alias):
            def wrapped(*args, **kwargs):
                result = original(*args, **kwargs)
                self.pronunciations.append({"alias": alias, "result": dto(result)})
                return result
            return wrapped

        if callable(original_certify):
            stack.enter_context(patch.object(morphology, "certify_rule_boundaries", certify))
        if callable(original_apply):
            stack.enter_context(patch.object(engine, "apply_rule_boundaries", apply))
        stack.enter_context(patch.object(engine, "_apply_lexical_pronunciations", lexical))
        stack.enter_context(patch.object(engine, "_record", record))
        stack.enter_context(patch.object(engine, "pronounce", pronunciation(engine.pronounce, "engine.pronounce")))
        stack.enter_context(patch.object(pipeline, "pronounce", pronunciation(pipeline.pronounce, "pipeline.pronounce")))


def part_names(payload, native_parts):
    """네이티브 원형 순서가 제공 분석/정확 구조와 일치할 때만 ID를 연결한다."""
    direct = [(p["form"], p["tag"], p["id"]) for p in payload["canonical_parts"]]
    if [list(p[:2]) for p in direct] == native_parts:
        return [p[2] for p in direct]
    for fact in payload.get("dictionary_structure", ()):
        start, end = fact["owner_span"]
        before = [(p["form"], p["tag"], p["id"]) for p in payload["canonical_parts"] if p["span"][1] <= start]
        after = [(p["form"], p["tag"], p["id"]) for p in payload["canonical_parts"] if p["span"][0] >= end]
        expanded = before + [(p[0], p[1], f"dict:p{i}") for i, p in enumerate(fact["parts"])] + after
        if [list(p[:2]) for p in expanded] == native_parts:
            return [p[2] for p in expanded]
    return None


def proof_geometry(boundary):
    """원시 범위와 재생성 자료를 혼합하지 않고 원형 순서 대응을 확인한다."""
    proofs = boundary.get("surface_proofs", [])
    flattened = [part for proof in proofs for part in proof.get("parts", [])]
    if flattened != boundary["parts"]:
        return None
    occurrences = [occ for proof in proofs for occ in proof.get("occurrences", [])]
    if len(occurrences) != len(boundary["parts"]):
        return None
    if [[o["form"], o["tag"]] for o in occurrences] != boundary["parts"]:
        return None
    return [o.get("raw_span") for o in occurrences]


def original_coda(origin):
    if not origin or origin.get("role") != "coda":
        return None
    jamo = origin.get("jamo", "")
    if len(jamo) == 1 and 0x11A8 <= ord(jamo) <= 0x11C2:
        return TAILS[ord(jamo) - 0x11A7]
    return jamo if jamo in TAILS[1:] else None


def recipient_index(boundary):
    candidates = sorted({o["occurrence"] for o in boundary.get("recipient_origins", [])})
    candidates = [i for i in candidates if type(i) is int and 0 <= i < len(boundary["parts"])]
    desired = {"formal_suffix_i": "이", "formal_suffix_hi": "히", "semantic_suffix_eochi": "어치"}.get(boundary.get("role"))
    if desired:
        candidates = [i for i in candidates if boundary["parts"][i][0] == desired]
    return candidates[0] if len(candidates) == 1 else None


def contraction(boundary, recipient):
    """실제 공동 유래 ㅣ+어와 표면 ㅕ의 증거만 축약으로 투영한다."""
    proofs = boundary.get("surface_proofs", [])
    if not proofs or recipient is None:
        return None
    base = 0
    for proof in proofs:
        local = {o["index"]: base + i for i, o in enumerate(proof.get("occurrences", []))}
        for atom in proof.get("atoms", []):
            if atom.get("role") != "vowel" or atom.get("jamo") != "ᅧ":
                continue
            origins = atom.get("origins", [])
            i_origin = any(local.get(o.get("occurrence")) == recipient and o.get("role") == "vowel" and o.get("jamo") == "ᅵ" for o in origins)
            eo_origin = any(local.get(o.get("occurrence")) == recipient + 1 and o.get("role") == "vowel" and o.get("jamo") == "ᅥ" for o in origins)
            if i_origin and eo_origin and recipient + 1 < len(boundary["parts"]) and boundary["parts"][recipient + 1][1].startswith("E"):
                return True
        base += len(proof.get("parts", []))
    return False if base == len(boundary["parts"]) else None


def project_boundary(payload, boundary, capture):
    values = {"source_pair": boundary["pair"], "word_span": boundary["word_span"],
              "role": boundary["role"], "status": boundary["status"], "applicability": boundary["applicability"]}
    unsupported = {}
    if boundary["source"] == "analysis_local_attachment":
        values.pop("word_span")
        unsupported["word_span"] = "이 네이티브 출처는 attachment_span만 증명하며 전체 단어 적격성을 주장하지 않는다."
    if boundary["applicability"] == "blocked":
        unsupported["selected_article"] = "차단된 DTO의 article이 실행 선택인지 계획 조항인지 별도 의미 정의가 없다."
    else:
        values["selected_article"] = boundary["article"]
    if boundary["source"] in SOURCE_ALIASES:
        values["authority"] = SOURCE_ALIASES[boundary["source"]]
    else:
        unsupported["authority"] = "네이티브 source 값의 휴대 권한 명칭 대응이 정의되지 않았다."
    names = part_names(payload, boundary["parts"])
    geometry = proof_geometry(boundary)
    donor = boundary.get("donor_origin")
    donor_index = donor.get("occurrence") if donor else None
    recipient = recipient_index(boundary)
    for side, index in (("left", donor_index), ("right", recipient)):
        if names is not None and type(index) is int and 0 <= index < len(names):
            values[side + "_origin"] = names[index]
        else:
            unsupported[side + "_origin"] = "네이티브 원형 출현과 제공 분석/정확 구조의 순서 대응이 없다."
        if geometry is not None and type(index) is int and 0 <= index < len(geometry) and geometry[index] is not None:
            values[side + "_origin_span"] = geometry[index]
        else:
            unsupported[side + "_origin_span"] = "대응된 Occurrence.raw_span이 없다. 재생성 범위로 원시 범위를 만들지 않는다."
    coda = original_coda(donor)
    if coda is not None:
        values["original_coda"] = coda
    else:
        unsupported["original_coda"] = "원래 받침 SourceAtom이 없다. 현재 coda에서 역산하지 않는다."
    if recipient is not None:
        values["original_receiver"] = boundary["parts"][recipient][0]
    else:
        unsupported["original_receiver"] = "단일 수신 원형 출현을 고를 네이티브 근거가 없다."
    contracted = contraction(boundary, recipient)
    if contracted is not None:
        values["contracted"] = contracted
    else:
        unsupported["contracted"] = "전체 표면 증명과 수신 원형 대응이 없다."
    events = [e for call in capture.applications for e in call["events"] if e["boundary"]["pair"] == boundary["pair"]]
    states = {"eligible", "not_required", "blocked", "unresolved"}
    if capture.applications and all(e["applicability"] in states for e in events):
        consumed = [e for e in events if e["applicability"] == "eligible" and e["boundary"]["article"] in ("15", "17", "29")]
        values["consumption_count"] = len(consumed)
        values["consumed_articles"] = [e["boundary"]["article"] for e in consumed]
    else:
        unsupported["consumption_count"] = "확인된 실제 적용 호출/적용성 값이 없다."
        unsupported["consumed_articles"] = unsupported["consumption_count"]
    return {"source_pair": boundary["pair"], "values": values, "unsupported": unsupported,
            "authority_scope": "attachment_only" if boundary["source"] == "analysis_local_attachment" else "native_boundary_scope",
            "native_attachment_span": boundary.get("attachment_span"),
            "native_evidence": {"boundary_record": boundary, "events": events,
                                "grammar": boundary.get("grammar"), "surface_proofs": boundary.get("surface_proofs"),
                                "word_certificate": None},
            "word_certificate_unavailable_ko": "RuleBoundary는 별도 WordCertificate 객체를 반환하지 않는다."}


def evaluate_native(payload, *, aliases=None, invoke=None, input_mode="tokens_only"):
    aliases = prepare_native_imports() if aliases is None else aliases
    invoke = load_public_helper().run_public if invoke is None else invoke
    capture = Capture(aliases, payload, input_mode)
    with ExitStack() as stack:
        capture.install(stack)
        phone, public_result, calls = invoke(payload)
    native = capture.pronunciations[-1]["result"] if capture.pronunciations else None
    rewrites = native.get("rewrites") if native is not None else None
    records = [b for call in capture.certifications for b in call]
    result = {"binding_version": BINDING_VERSION, "phone": phone, "route": payload["route"],
              "input_mode": input_mode, "structure_delivery": capture.input_delivery, "native_api_available": capture.native_api_available,
              "analysis_source": "supplied", "analysis_observation": {"stub_installed": True, "call_count": len(calls), "calls": dto(calls)},
              "rule_trace_observation": {"status": "captured" if rewrites is not None else "not_exposed_by_result_dto",
                                         "count": len(rewrites) if rewrites is not None else None, "rewrites": rewrites},
              "completion_observation": {"status": "captured" if hasattr(public_result, "complete") else "not_exposed_by_result_dto",
                                         "value": getattr(public_result, "complete", None)},
              "boundaries": [project_boundary(payload, b, capture) for b in records],
              "whole_phone_override_used": bool(capture.lexical_records) if native is not None else None,
              "native_evidence": {"pronunciations": capture.pronunciations, "certify_calls": capture.certifications,
                                  "apply_calls": capture.applications, "lexical_application_calls": capture.lexical_calls,
                                  "lexical_application_records": capture.lexical_records,
                                  "override_meaning": "승인된 실제 완성 발음 적용 함수 안의 record 호출"}}
    return result


def evaluate(payload, *, input_mode="tokens_only"):
    return evaluate_native(payload, input_mode=input_mode)


def construct_invalid(payload):
    return load_public_helper().construct_invalid(payload)
