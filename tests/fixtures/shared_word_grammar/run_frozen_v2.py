"""고정 자료와 선택한 자체 소스를 비교하며 기대값을 실행 중 수정하지 않는다."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, is_dataclass
import hashlib
import importlib
import json
from pathlib import Path
import sys
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True


def plain(value):
    """증거를 JSON에 보존할 수 있는 값으로 바꾼다."""
    if is_dataclass(value):
        return {key: plain(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [plain(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(
            item, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return getattr(value, "value", value)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_receipt():
    """선택 소스를 가져오기 전에 고정 파일의 해시부터 확인한다."""
    manifest = json.loads((HERE / "freeze_manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["sha256"].items():
        if digest(HERE / name) != expected:
            raise RuntimeError("고정 자료 해시가 달라졌습니다: " + name)
    return manifest


def make_tokens(row, variant, AnalysisToken, offset=0):
    """동일 형태소 출현열의 유효한 분리·결합 포장을 만든다."""
    parts = tuple(tuple(part) for part in row["parts"])
    source = row["surface"]
    spans = row.get("spans")
    if spans is None:
        spans, cursor = [], 0
        for form, _ in parts:
            spans.append((cursor, cursor + len(form)))
            cursor += len(form)
    spans = tuple(tuple(span) for span in spans)
    if variant == "split":
        groups = [(index, index + 1) for index in range(len(parts))]
    elif variant == "mixed":
        groups = [(0, len(parts) - 1), (len(parts) - 1, len(parts))]
    elif variant == "shared_tail":
        groups = [(0, 1), (1, len(parts))]
    else:
        groups = [(0, len(parts))]
    result = []
    for begin, finish in groups:
        current = parts[begin:finish]
        local_spans = spans[begin:finish]
        start = min(span[0] for span in local_spans)
        end = max(span[1] for span in local_spans)
        result.append(AnalysisToken(
            source[start:end], "+".join(tag for _, tag in current),
            start + offset, end + offset, current,
            tuple((a + offset, b + offset) for a, b in local_spans),
        ))
    mutation = row.get("mutation")
    if mutation:
        token = result[0]
        kwargs = dict(form=token.form, tag=token.tag,
                      normalized_start=token.normalized_start, normalized_end=token.normalized_end,
                      morphemes=token.morphemes, morpheme_spans=token.morpheme_spans)
        if mutation == "missing_morphemes":
            kwargs.update(morphemes=(), morpheme_spans=())
        elif mutation == "tag_parts_conflict":
            kwargs["tag"] = "NNG+NNG"
        elif mutation == "canonical_identity_conflict":
            kwargs["morphemes"] = (("온", "XPN"), ("말", "NNG"))
        elif mutation == "reversed_spans":
            kwargs["morpheme_spans"] = tuple(reversed(token.morpheme_spans))
        elif mutation == "missing_first_token":
            return result[1:]
        elif mutation == "overlap_token":
            result.append(AnalysisToken(source[1:], "NNG", offset + 1, offset + len(source),
                                        ((source[1:], "NNG"),), ((offset + 1, offset + len(source)),)))
            return result
        else:
            raise RuntimeError("알 수 없는 고정 입력 변형입니다: " + mutation)
        result[0] = AnalysisToken(**kwargs)
    return result


def context(source, tokens, model, engine, morphology, *, barrier=None):
    """실제 자체 단위 생성기를 사용하고 장벽을 명시적으로 배치한다."""
    segments = []
    for index, char in enumerate(source):
        handler = model.Handler.PROTECTED if barrier == "protected" and index == 1 else model.Handler.KOREAN
        segments.append(model.OutputSegment(
            char, (model.SourceSpan.from_source(source, index, index + 1),), handler,
            "독립 문법 증명 입력",
            boundary_before=model.Boundary.HARD if barrier == "hard" and index == 1 else model.Boundary.MORPHEME,
            boundary_after=model.Boundary.MORPHEME,
        ))
    segments = tuple(segments)
    units = engine._build_units(segments, trace=True)
    annotation = morphology._Annotation.from_tokens(tuple(tokens), source)
    return annotation, units, segments, (1,) if barrier == "pause" else ()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--include-kiwi", action="store_true")
    args = parser.parse_args()
    output = args.out.resolve()
    if not output.is_relative_to(HERE):
        raise ValueError("검증 결과는 지정된 independent_refs 폴더 안에만 기록합니다.")
    receipt = freeze_receipt()
    fixture = json.loads((HERE / "frozen_cases.json").read_text(encoding="utf-8"))
    src = args.src.resolve()
    sys.path.insert(0, str(src))
    model = importlib.import_module("g2p_ko.model")
    roles = importlib.import_module("g2p_ko.korean.word_roles")
    morphology = importlib.import_module("g2p_ko.korean.morphology")
    engine = importlib.import_module("g2p_ko.korean.engine")
    proof_module = importlib.import_module("g2p_ko.korean.surface_proof")
    api = importlib.import_module("g2p_ko")
    for module in (model, roles, morphology, engine, proof_module, api):
        if not Path(module.__file__).resolve().is_relative_to(src):
            raise RuntimeError("선택한 소스 밖에서 프로젝트 모듈을 가져왔습니다.")
    certify = getattr(roles, "certify_word", None)
    records = []

    def record(kind, case_id, expected, observed, errors):
        records.append({"kind": kind, "id": case_id, "pass": not errors,
                        "expected": plain(expected), "observed": plain(observed), "errors": errors})

    semantic_groups = {}
    for row in fixture["certificate_cases"]:
        for variant in row["variants"]:
            case_id = row["id"] + ":" + variant
            errors, observed = [], {}
            try:
                tokens = make_tokens(row, variant, model.AnalysisToken)
                annotation, units, segments, pauses = context(row["surface"], tokens, model, engine, morphology)
                if certify is None:
                    errors.append("공유 certify_word API가 없습니다.")
                else:
                    result = certify(annotation, 0, units, segments, pauses)
                    observed["certificate"] = plain(result)
                    expected = row["expected"]
                    if result.lexical_status != expected["lexical_status"]:
                        errors.append("lexical_status 불일치")
                    if expected["assert_category"] and result.final_category != expected["final_category"]:
                        errors.append("final_category 불일치")
                    for source_key, field in (("host", "host_state"), ("tail", "tail_state"), ("surface_status", "surface_status")):
                        if expected[source_key] is not None and getattr(result, field) != expected[source_key]:
                            errors.append(field + " 불일치")
                    if result.surface_status not in {"verified", "unavailable", "conflict"}:
                        errors.append("정의되지 않은 surface_status")
                    if result.lexical_status == "eligible":
                        if result.start != 0 or result.end != len(row["surface"]):
                            errors.append("전체 원문 범위 불일치")
                        if tuple(result.parts) != tuple(tuple(part) for part in row["parts"]):
                            errors.append("원형 출현열 신원 불일치")
                    semantic = tuple(getattr(result, field) for field in (
                        "lexical_status", "final_category", "host_state", "tail_state", "surface_status"))
                    semantic_groups.setdefault(row["id"], []).append((variant, semantic))
                liaison = roles.lexical_liaison_target(annotation, 0, units, segments, pauses)
                first = annotation.starting_at(0)
                n_target = morphology._is_independent_word_n_insertion_target(
                    first, annotation=annotation, units=units, segments=segments, pause_boundaries=pauses,
                ) if first is not None else False
                observed["liaison_target"] = liaison
                observed["n_target"] = n_target
                wanted = row["expected"]["lexical_status"] == "eligible"
                if liaison != wanted:
                    errors.append("연음 소비자와 공유 어휘 적격성 불일치")
                if n_target != row["expected"]["n_target"]:
                    errors.append("단어 ㄴ 첨가 소비자와 공유 어휘 적격성 불일치")
                observed["tokens"] = plain(tokens)
                token_proofs = [proof_module.verified_token_surface(token) for token in tokens]
                observed["surface_proofs"] = [plain(proof) for proof in token_proofs]
                if row["id"] in {"contracted_derivation", "contracted_regular"}:
                    shared = [proof for proof in token_proofs if proof is not None and proof.shared_offset is not None]
                    if len(shared) != 1:
                        errors.append("공동 음절 유래 증명이 없습니다.")
                    else:
                        proof = shared[0]
                        shared_offset = 2 if row["id"] == "contracted_derivation" else 0
                        expected_rule = "맞춤법.34.붙임2" if row["id"] == "contracted_derivation" else "맞춤법.35"
                        if proof.shared_offset != shared_offset or expected_rule not in proof.rule_steps:
                            errors.append("승인된 축약의 규칙·원문 좌표 provenance 불일치")
                        shared_vowels = [atom for atom in proof.atoms if atom.offset == shared_offset and atom.role == "vowel"]
                        if len(shared_vowels) != 1 or len({origin.occurrence for origin in shared_vowels[0].origins}) != 2:
                            errors.append("공동 모음을 단독 원형 소유로 바꿨습니다.")
            except Exception as exc:
                errors.append(type(exc).__name__ + ": " + str(exc))
            record("certificate", case_id, row["expected"], observed, errors)

    for case_id, variants in semantic_groups.items():
        if len(variants) > 1:
            errors = [] if all(value == variants[0][1] for _, value in variants) else ["유효한 토큰 포장 간 의미 상태 불일치"]
            record("packaging_equivalence", case_id, "동일 상태·품사·숙주·꼬리·표면 권한", variants, errors)

    barrier_reference = next(row for row in fixture["certificate_cases"] if row["id"] == "prefix_liaison_noun")
    for barrier in fixture["barriers"]:
        errors, observed = [], {}
        try:
            tokens = make_tokens(barrier_reference, "split", model.AnalysisToken)
            annotation, units, segments, pauses = context(barrier_reference["surface"], tokens, model, engine, morphology, barrier=barrier)
            if certify is None:
                errors.append("공유 certify_word API가 없습니다.")
            else:
                result = certify(annotation, 0, units, segments, pauses)
                observed["certificate"] = plain(result)
                if result.lexical_status != "unresolved":
                    errors.append("장벽은 문법 제외가 아니라 연속 증명의 미해결이어야 합니다.")
            observed["liaison_target"] = roles.lexical_liaison_target(annotation, 0, units, segments, pauses)
            observed["n_target"] = morphology._is_independent_word_n_insertion_target(tokens[0], annotation=annotation, units=units, segments=segments, pause_boundaries=pauses)
            if observed["liaison_target"] or observed["n_target"]:
                errors.append("내부 장벽이 있는 단어에 음운 권한을 발행했습니다.")
        except Exception as exc:
            errors.append(type(exc).__name__ + ": " + str(exc))
        record("barrier", barrier, {"lexical_status": "unresolved", "consumers": False}, observed, errors)

    for row in fixture["constructor_rejections"]:
        errors, observed = [], {}
        try:
            model.AnalysisToken(row["form"], row["tag"], row["start"], row["end"],
                                tuple(tuple(part) for part in row.get("morphemes", ())),
                                tuple(tuple(span) for span in row.get("spans", ())))
            errors.append("AnalysisToken 생성자가 무효 입력을 수용했습니다.")
        except ValueError as exc:
            observed["constructor_rejection"] = str(exc)
        except Exception as exc:
            errors.append(type(exc).__name__ + ": " + str(exc))
        record("constructor_rejection", row["id"], "ValueError", observed, errors)

    class FrozenAnalyzer:
        """각 공개 실행의 고정 분석 자료만 반환한다."""
        def __init__(self, source, tokens):
            self.source, self.tokens, self.calls = source, tuple(tokens), []

        def analyze(self, text, **kwargs):
            return self.analyze_components(text)

        def analyze_components(self, text):
            self.calls.append(text)
            if text != self.source:
                raise ValueError("고정 자료에 없는 분석 구간을 요청했습니다.")
            return self.tokens

        def saisiot_positions(self, text):
            return ()

    references = {row["id"]: row for row in fixture["certificate_cases"]}
    for row in fixture["public_gap_cases"]:
        errors, observed = [], {}
        try:
            reference = references[row["reference"]] if "reference" in row else {
                "parts": row["parts"], "surface": "".join(form for form, _ in row["parts"]),
            }
            source = row["left"] + " " + reference["surface"]
            right = len(row["left"]) + 1
            tokens = [model.AnalysisToken(row["left"], row["left_tag"], 0, len(row["left"]),
                                          ((row["left"], row["left_tag"]),), ((0, len(row["left"])),))]
            variant = row.get("variant", reference.get("variants", ["split"])[0])
            tokens.extend(make_tokens(reference, variant, model.AnalysisToken, right))
            analyzer = FrozenAnalyzer(source, tokens)
            with patch.object(engine, "KiwiAnalyzer", lambda: analyzer):
                result = api.G2P().convert_with_reading_conditions(
                    source, reading_conditions=[api.ReadingBoundary(len(row["left"]), row["relation"])])
            executions = result.boundary_executions
            observed.update(source=source, result=result.to_dict(), analyzer_calls=analyzer.calls)
            if len(executions) != 1:
                errors.append("공개 읽기 조건 실행 개수 불일치")
            else:
                execution = executions[0]
                for field, wanted in row["expected"].items():
                    if field == "rule":
                        if wanted not in execution.rule_ids:
                            errors.append("기대 음운 규칙의 경계 기록이 없습니다.")
                    elif field == "forbidden_rule":
                        if wanted in execution.rule_ids:
                            errors.append("예외 신원 보호 경계에서 ㄴ 첨가를 적용했습니다.")
                    elif getattr(execution, field) != wanted:
                        errors.append("공개 실행 " + field + " 불일치")
                if execution.source_offset != len(row["left"]) or execution.output_pair != (len(row["left"]) - 1, right):
                    errors.append("공개 실행 원문 경계 provenance 불일치")
            if result.aligned.result.source != source or result.aligned.result.normalized_text != source:
                errors.append("공개 결과의 원문 신원 불일치")
            if not result.aligned.result.complete:
                errors.append("고정 한글 자료가 불완전 결과입니다.")
            if not analyzer.calls and row["relation"] != "pause":
                errors.append("고정 분석기가 실제 공개 경로에서 호출되지 않았습니다.")
        except Exception as exc:
            errors.append(type(exc).__name__ + ": " + str(exc))
        record("public_gap", row["id"], row["expected"], observed, errors)

    for index, row in enumerate(fixture["public_api_rejections"]):
        errors, observed = [], {}
        analyzer = FrozenAnalyzer(row["source"], ())
        try:
            with patch.object(engine, "KiwiAnalyzer", lambda: analyzer):
                api.G2P().convert_with_reading_conditions(row["source"], reading_conditions=[api.ReadingBoundary(row["offset"], row["relation"])])
            errors.append("비휴지 조건을 ASCII 단어 공백 밖에서 수용했습니다.")
        except api.InputValidationError as exc:
            observed["api_rejection"] = str(exc)
        except Exception as exc:
            errors.append(type(exc).__name__ + ": " + str(exc))
        record("public_api_rejection", str(index), "InputValidationError", observed, errors)

    observations = []
    if args.include_kiwi:
        actual = importlib.import_module("g2p_ko.analyzer").KiwiAnalyzer()
        for text in fixture["kiwi_observation_inputs"]:
            try:
                tokens = actual.analyze_components(text)
                observations.append({"source": text, "tokens": plain(tokens),
                                     "public_result": api.G2P().convert(text).to_dict()})
            except Exception as exc:
                observations.append({"source": text, "error": type(exc).__name__ + ": " + str(exc)})

    counts = Counter((row["kind"], row["pass"]) for row in records)
    result = {
        "schema": "r41_independent_run.v1", "source": str(src), "freeze": receipt,
        "source_sha256": {str(Path(module.__file__).resolve().relative_to(src)): digest(Path(module.__file__))
                          for module in (model, roles, morphology, engine, proof_module, api)},
        "project_api": "G2P.convert_with_reading_conditions / ASCII 단어 공백",
        "strict_api_present": certify is not None,
        "total": len(records), "passed": sum(row["pass"] for row in records),
        "failed": sum(not row["pass"] for row in records),
        "by_kind": {kind: {"passed": counts[kind, True], "failed": counts[kind, False]}
                    for kind in sorted({row["kind"] for row in records})},
        "records": records, "kiwi_observations": observations,
        "scope_ko": "관찰용 실제 Kiwi 출력은 정답이나 독립 문법 계약의 증거로 재사용하지 않는다. 생성자 거부·공유 증명·소비자·공개 공백 읽기 API를 분리한다.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plain(result), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({key: result[key] for key in ("strict_api_present", "total", "passed", "failed", "by_kind")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
