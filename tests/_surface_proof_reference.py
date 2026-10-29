"""독립 작성된 증명·자모 유래·소유 기대를 검사하는 고정 보조 코드다."""

import dataclasses


TOKEN_FIELDS = ("form", "tag", "normalized_start", "normalized_end", "morphemes", "morpheme_spans")


def serial(value):
    if dataclasses.is_dataclass(value):
        return {field.name: serial(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(key): serial(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serial(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(serial(item) for item in value)
    if hasattr(value, "value"):
        return value.value
    return value


class Annotation:
    """인수된 annotation의 최소 조회 API만 제공하는 고정 분석 색인이다."""

    def __init__(self, text, tokens):
        self.text = text
        self.starts = {token.normalized_start: token for token in tokens}
        self.ends = {token.normalized_end: token for token in tokens}
        self.coverage = {i: token for token in tokens for i in range(token.normalized_start, token.normalized_end)}

    def starting_at(self, offset):
        return self.starts.get(offset)

    def ending_at(self, offset):
        return self.ends.get(offset)

    def covering(self, offset):
        return self.coverage.get(offset)


class Score:
    """같은 종류의 독립 주장끼리만 합산한다."""

    def __init__(self):
        self.metrics = {}
        self.family_metrics = {}

    def check(self, metric, expected, observed, checks, family):
        passed = expected == observed
        checks.append({"metric": metric, "passed": passed, "expected": serial(expected), "observed": serial(observed)})
        for bucket in (self.metrics.setdefault(metric, {"passed": 0, "total": 0}),
                       self.family_metrics.setdefault(family, {}).setdefault(metric, {"passed": 0, "total": 0})):
            bucket["passed"] += int(passed)
            bucket["total"] += 1


def make_context(case, modules, tokens):
    model, shared, hangul = modules["model"], modules["shared"], modules["hangul"]
    text = case["text"]
    hard_at = case.get("hard_boundary_at")
    cuts = [0, len(text)] if hard_at is None else [0, hard_at, len(text)]
    segments = []
    for index, (start, end) in enumerate(zip(cuts, cuts[1:])):
        segments.append(model.OutputSegment(text[start:end], (model.SourceSpan.from_source(text, start, end),),
                                           model.Handler.KOREAN, "독립 고정 분석 입력",
                                           boundary_before=model.Boundary.HARD if index else model.Boundary.WORD,
                                           boundary_after=model.Boundary.HARD if index + 1 < len(cuts) - 1 else model.Boundary.WORD))
    units = []
    for offset, char in enumerate(text):
        segment_index = next(i for i, (a, b) in enumerate(zip(cuts, cuts[1:])) if a <= offset < b)
        replacement = case.get("unit_source_replacements", {}).get(str(offset), char)
        spans = (model.SourceSpan(offset, offset + 1, replacement, len(text)),)
        handler = model.Handler.PROTECTED if offset in case.get("protected_offsets", ()) else model.Handler.KOREAN
        if hangul.is_modern_syllable(char):
            units.append(shared._Unit(segment_index, handler, spans, syllable=hangul.decompose_syllable(char, spans)))
        else:
            units.append(shared._Unit(segment_index, handler, spans, raw=char))
    return Annotation(text, tokens), units, tuple(segments), tuple(case.get("pause_boundaries", ()))


def flatten_proof_atoms(proof):
    if proof is None:
        return None
    if not hasattr(proof, "atoms"):
        return None
    return {(atom.offset, atom.role): {"jamo": atom.jamo,
                                      "origins": sorted({origin.occurrence for origin in atom.origins})}
            for atom in proof.atoms}


def expected_hulls(spec):
    positions = {index: [] for index in range(len(spec["morphemes"]))}
    for atom in spec["expect_atoms"]:
        for origin in atom["origins"]:
            positions[origin].append(atom["offset"])
    return [[min(value), max(value) + 1] for _, value in sorted(positions.items())]


def evaluate_case(case, modules, score):
    checks, records = [], []
    family = case["family"]
    check = lambda name, expected, actual: score.check(name, expected, actual, checks, family)
    if "expect_exception" in case:
        observed = None
        try:
            modules["model"].AnalysisToken(**case["payload"])
        except Exception as exc:
            observed = type(exc).__name__
        check("constructor_input_rejection", case["expect_exception"], observed)
        return {"id": case["id"], "family": family, "checks": checks}

    tokens = []
    for spec in case["tokens"]:
        try:
            token = modules["model"].AnalysisToken(**{key: spec[key] for key in TOKEN_FIELDS if key in spec})
            tokens.append(token)
        except Exception as exc:
            check("unexpected_constructor_failure", None, {"type": type(exc).__name__, "message": str(exc)})
            return {"id": case["id"], "family": family, "checks": checks}
        try:
            proof = modules["roles"]._verified_token_surface(token)
            check("token_surface_proof", spec["expect_proof"], proof is not None)
        except Exception as exc:
            proof = None
            check("token_surface_proof", spec["expect_proof"], {"type": type(exc).__name__, "message": str(exc)})
        record = {"token": token.to_dict(), "proof": serial(proof)}
        if spec["expect_proof"]:
            check("token_proof_identity", [token.normalized_start, token.normalized_end, serial(token.morphemes)],
                  None if proof is None else [proof.start, proof.end, serial(proof.parts)])
            observed_atoms = flatten_proof_atoms(proof)
            record["atom_origin_api"] = "available" if observed_atoms is not None else "unavailable"
            check("atom_inventory", len(spec["expect_atoms"]),
                  len(proof.atoms) if proof is not None and hasattr(proof, "atoms") else None)
            try:
                owners = modules["ownership"].verified_source_owners(token)
                record["singleton_owners"] = serial(owners)
            except Exception as exc:
                owners = {}
                record["owner_exception"] = {"type": type(exc).__name__, "message": str(exc)}
            for atom in spec["expect_atoms"]:
                key = (atom["offset"], atom["role"])
                expected = {"jamo": atom["jamo"], "origins": atom["origins"]}
                check("atom_origin_sets", expected, None if observed_atoms is None else observed_atoms.get(key))
                expected_owner = None
                if len(atom["origins"]) == 1:
                    form, tag = spec["morphemes"][atom["origins"][0]]
                    expected_owner = {"form": form, "tag": tag}
                observed_owner = owners.get(key)
                check("singleton_source_owners", expected_owner, serial(observed_owner))
            if proof is not None and hasattr(proof, "regenerated_spans"):
                check("occurrence_regenerated_hulls", expected_hulls(spec), serial(proof.regenerated_spans))
            else:
                check("occurrence_regenerated_hulls", expected_hulls(spec), None)
            if proof is not None and hasattr(proof, "occurrences"):
                check("canonical_occurrences", [[index, form, tag] for index, (form, tag) in enumerate(spec["morphemes"])],
                      [[o.index, o.form, o.tag] for o in proof.occurrences])
            else:
                check("canonical_occurrences", [[index, form, tag] for index, (form, tag) in enumerate(spec["morphemes"])], None)
            # 37항 융합 모음의 왼쪽 어휘 유래를 형식 수신 사슬에서 빼지 않는다.
            if any(effect["family"] == "a37_suffix_i" for effect in spec["expect_effects"]):
                capability = getattr(modules.get("surface_proof"), "certified_formal_recipient", None)
                shared = next(e["shared_offset"] for e in spec["expect_effects"] if e["family"] == "a37_suffix_i")
                if capability is not None and proof is not None:
                    check("formal_chain_cross_boundary_origin_guard", False, capability(proof, shared))
                else:
                    check("formal_chain_cross_boundary_origin_guard", False, None)
        records.append(record)

    annotation, units, segments, pauses = make_context(case, modules, tokens)
    try:
        role = modules["roles"].derived_word_role(annotation, case["role_start"], units, segments, pauses, exact_source=True)
        check("exact_derived_word_role", case["expect_role"], serial(role))
    except Exception as exc:
        check("exact_derived_word_role", case["expect_role"], {"type": type(exc).__name__, "message": str(exc)})

    formal_observation = None
    if "formal" in case:
        expected = case["formal"]
        try:
            relations = {tuple(pair): "ordinary_liaison" for pair in expected["pairs"]}
            decisions = modules["formal"].decide_formal_attachments(case["text"], units, segments, annotation, relations, pauses)
            rewrites = modules["shared"]._RewriteLog()
            events = modules["formal"].apply_formal_attachments(decisions, units, rewrites)
            formal_observation = {"decisions": serial(decisions), "events": serial(events), "rewrites": serial(rewrites),
                                  "local_surface": "".join(unit.text for unit in units)}
            for pair in expected["pairs"]:
                event = events.get(tuple(pair))
                decision = decisions.get(tuple(pair))
                for expected_key, attr, obj in [("expect_kind", "kind", decision), ("expect_role", "role", decision),
                                                ("expect_status", "status", event), ("expect_applicability", "applicability", event)]:
                    if expected_key in expected:
                        check("formal_consumer_eligibility", expected[expected_key], getattr(obj, attr, None))
                check("formal_consumer_effect", expected["expect_sound_effect"], getattr(event, "sound_effect", None))
                check("formal_consumer_rule_ids", expected["expect_rule_ids"], list(getattr(event, "rule_ids", ())))
            check("local_phone_surface", expected["expect_local_surface"], formal_observation["local_surface"])
        except Exception as exc:
            formal_observation = {"exception": {"type": type(exc).__name__, "message": str(exc)}}
            check("local_phone_surface", expected["expect_local_surface"], formal_observation)
    return {"id": case["id"], "family": family, "checks": checks, "tokens": records, "formal": formal_observation}


def checked(metrics, checks, name, expected, actual):
    passed = expected == actual
    checks.append({"metric": name, "passed": passed, "expected": serial(expected), "observed": serial(actual)})
    counter = metrics.setdefault(name, {"passed": 0, "total": 0})
    counter["passed"] += int(passed)
    counter["total"] += 1


def tokens_for(case, model):
    return tuple(model.AnalysisToken(**{key: spec[key] for key in TOKEN_FIELDS if key in spec}) for spec in case["tokens"])


def run_joined(case, modules, metrics):
    checks, calls, provider_errors = [], [], []
    check = lambda name, expected, actual: checked(metrics, checks, name, expected, actual)
    tokens = tokens_for(case, modules["model"])
    _, _, segments, pauses = make_context(case, modules, tokens)

    class FixedAnalyzer:
        """분석기 의존성만 고정하며 실제 형태소·음운 실행 순서는 바꾸지 않는다."""

        def analyze_components(self, text):
            calls.append(text)
            if text != case["text"]:
                provider_errors.append({"requested": text, "available": case["text"]})
                raise ValueError("원래 동결 입력과 다른 분석 구간을 요청했습니다.")
            return tokens

        def analyze(self, text, **kwargs):
            return self.analyze_components(text)

    original_factory = modules["phonology"].KiwiAnalyzer
    modules["phonology"].KiwiAnalyzer = FixedAnalyzer
    try:
        pronunciation = modules["phonology"].pronounce(segments, pause_boundaries=pauses)
    except Exception as exc:
        check("joined_local_transition", case["formal"]["expect_local_surface"], {"exception": type(exc).__name__, "message": str(exc)})
        return {"id": case["id"], "checks": checks, "analyzer_calls": calls}
    finally:
        modules["phonology"].KiwiAnalyzer = original_factory

    left, right = case["formal"]["pairs"][0]
    expected_ranges = [(left, left + 1), (right, right + 1)]
    expected_rules = case["formal"]["expect_rule_ids"]
    selected = []
    for rewrite in pronunciation.rewrites:
        ranges = sorted({(span.start, span.end) for span in rewrite.source_spans})
        if rewrite.rule_id in expected_rules and ranges == expected_ranges:
            selected.append(rewrite)
    observed_local = case["text"]
    if len(selected) == 1:
        observed_local = case["text"][:left] + selected[0].after + case["text"][right + 1:]
    check("joined_local_transition", case["formal"]["expect_local_surface"], observed_local)
    check("joined_target_rule_ids", expected_rules, [rewrite.rule_id for rewrite in selected])
    check("joined_source_aligned_before", case["text"][left:right + 1], selected[0].before if len(selected) == 1 else None)
    check("joined_fixed_provider_integrity", [], provider_errors)
    return {"id": case["id"], "family": case["family"], "checks": checks,
            "original_text": case["text"], "original_local_gold": case["formal"]["expect_local_surface"],
            "source_pair": [left, right], "selected_local_rewrites": serial(selected),
            "all_rewrites": serial(pronunciation.rewrites), "final_surface_observation_only": pronunciation.text,
            "diagnostics": serial(pronunciation.diagnostics), "analyzer_calls": calls,
            "fixed_tokens": serial(tokens), "full_output_gold_added": False}


def run_gap(case, modules, metrics):
    checks = []
    check = lambda name, expected, actual: checked(metrics, checks, name, expected, actual)
    tokens = tokens_for(case, modules["model"])
    annotation, units, segments, pauses = make_context(case, modules, tokens)
    proof = modules["roles"]._verified_token_surface(tokens[1])
    check("gap_recipient_surface_proof", case["expect_recipient_proof"], proof is not None)
    pair = tuple(case["pair"])
    decisions = modules["formal"].decide_formal_attachments(case["text"], units, segments, annotation,
                                                          {pair: "ordinary_liaison"}, pauses)
    rewrites = modules["shared"]._RewriteLog()
    events = modules["formal"].apply_formal_attachments(decisions, units, rewrites)
    decision, event = decisions.get(pair), events.get(pair)
    check("gap_decision_scope", case["expect_decision_present"], decision is not None)
    if case["expect_decision_present"]:
        check("gap_status", case["expect_status"], event.status if event is not None else None)
        check("gap_applicability", case["expect_applicability"], event.applicability if event is not None else None)
        check("gap_formal_role", case["expect_role"], decision.role if decision is not None else None)
    check("gap_sound_effect", case["expect_sound_effect"], event.sound_effect if event is not None else None)
    check("gap_rule_ids", case["expect_rule_ids"], list(event.rule_ids) if event is not None else [])
    check("gap_local_surface", case["expect_local_surface"], "".join(unit.text for unit in units))
    owners = modules["ownership"].verified_source_owners(tokens[1])
    if case["id"] in {"gap_dev_suffix_chain_single", "gap_dev_suffix_chain_hieuh"}:
        check("gap_shared_vowel_no_singleton", None, serial(owners.get((pair[1], "vowel"))))
    return {"id": case["id"], "checks": checks, "decisions": serial(decisions), "events": serial(events),
            "rewrites": serial(rewrites), "recipient_proof": serial(proof), "recipient_singletons": serial(owners)}
