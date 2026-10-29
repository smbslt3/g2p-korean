"""공개 발음 경로의 관찰만 연결하고 새 경계 권한은 미연결로 남긴다."""

from __future__ import annotations

import importlib.util
from collections import Counter
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping


BINDING_VERSION = "r42-public-observation-v1"
ROOT = Path(__file__).resolve().parent
AUTHORITY_BINDING = "unbound_pending_accepted_native_api"
_MISSING = object()


def _json_dto(value):
    """공개 DTO의 선언된 필드를 손실 추정 없이 JSON 값으로 옮긴다."""
    if isinstance(value, Enum):
        return _json_dto(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _json_dto(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        if any(not isinstance(k, str) for k in value):
            raise TypeError("DTO 매핑 키는 문자열이어야 합니다.")
        return {k: _json_dto(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_dto(v) for v in value]
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise TypeError("알려지지 않은 DTO 형식을 문자열 표현으로 대체하지 않습니다.")


def _dto_field(value, name):
    """매핑 또는 데이터 클래스에 선언된 필드만 읽는다."""
    if isinstance(value, Mapping):
        return value.get(name, _MISSING)
    if is_dataclass(value) and not isinstance(value, type):
        if name in {f.name for f in fields(value)}:
            return getattr(value, name)
    return _MISSING


def _helper():
    """동결 뒤 추가한 공개 진입점 보조 함수만 가져온다."""
    spec = importlib.util.spec_from_file_location("r42_public_entrypoints_helper_v1", ROOT / "public_entrypoints_helper.py")
    if spec is None or spec.loader is None:
        raise ValueError("공개 진입점 보조 함수를 가져올 수 없습니다.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def observe_public(payload, *, invoke=None):
    """실행 결과 DTO를 기록하되 기대값이나 발음에서 새 권한을 만들지 않는다."""
    invoker = _helper().run_public if invoke is None else invoke
    phone, native, calls = invoker(payload)
    if not isinstance(phone, str):
        raise TypeError("공개 발음 결과는 문자열이어야 합니다.")
    if not isinstance(calls, list):
        raise TypeError("제공 분석 호출 기록은 목록이어야 합니다.")
    calls_json = _json_dto(calls)
    traces = _dto_field(native, "rewrites")
    if traces is _MISSING:
        trace_capture = {"status": "not_exposed_by_result_dto", "count": None,
                         "rule_id_counts": None, "rewrites": None}
    else:
        if not isinstance(traces, (tuple, list)):
            raise TypeError("네이티브 rewrites 필드는 목록 또는 튜플이어야 합니다.")
        trace_rows = _json_dto(traces)
        rule_ids = []
        for row in trace_rows:
            if not isinstance(row, dict) or not isinstance(row.get("rule_id"), str):
                raise TypeError("각 네이티브 rewrite에는 문자열 rule_id가 필요합니다.")
            rule_ids.append(row["rule_id"])
        trace_capture = {"status": "captured", "count": len(trace_rows),
                         "rule_id_counts": dict(Counter(rule_ids)), "rewrites": trace_rows}
    complete = _dto_field(native, "complete")
    completion = {"status": "not_exposed_by_result_dto", "value": None}
    if complete is not _MISSING:
        if type(complete) is not bool:
            raise TypeError("공개 complete 필드는 불리언이어야 합니다.")
        completion = {"status": "captured", "value": complete}
    return {
        "binding_version": BINDING_VERSION,
        "phone": phone,
        "route": payload["route"],
        "analysis_source": "supplied",
        "analysis_observation": {"stub_installed": True, "call_count": len(calls_json),
                                 "calls": calls_json},
        "rule_trace_observation": trace_capture,
        "completion_observation": completion,
        "authority_binding": AUTHORITY_BINDING,
        "override_binding": AUTHORITY_BINDING,
        "whole_phone_override_used": None,
        "boundaries": None,
        "native_evidence": {
            "invocation": {"entrypoint": payload["route"], "source": payload["source"],
                           "pause_boundaries": list(payload.get("pause_boundaries", ())),
                           "analysis_call_count": len(calls_json),
                           "native_dto_type": type(native).__module__ + "." + type(native).__qualname__},
            "rule_traces": trace_capture,
            "override_audit": None,
        },
    }


def evaluate(payload):
    """기존 실행기와 같은 어댑터 진입점이며 실제 호출은 별도 허가 후 수행한다."""
    return observe_public(payload)


def construct_invalid(payload):
    """생성자 거부를 공개 진입점 보조 함수로 별도 관찰한다."""
    return _helper().construct_invalid(payload)
