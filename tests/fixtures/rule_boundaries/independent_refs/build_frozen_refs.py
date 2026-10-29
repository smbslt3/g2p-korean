"""런타임을 가져오지 않고 독립 규범 참조를 한 번 고정한다."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CASES = []


def part(form, tag, start, end):
    return {"form": form, "tag": tag, "span": [start, end]}


def analysis(source, parts, packaging):
    if packaging == "opaque":
        return [{"form": source, "tag": parts[0]["tag"], "start": 0, "end": len(source),
                 "morphemes": [[source, parts[0]["tag"]]], "morpheme_spans": [[0, len(source)]]}]
    if packaging == "fused":
        return [{"form": source, "tag": "+".join(p["tag"] for p in parts), "start": 0,
                 "end": len(source), "morphemes": [[p["form"], p["tag"]] for p in parts],
                 "morpheme_spans": [p["span"] for p in parts]}]
    tokens = []
    for p in parts:
        start, end = p["span"]
        # 축약 음절을 함께 소유하는 원형들은 하나의 표면 토큰으로 묶는다.
        if tokens and start < tokens[-1]["end"]:
            tokens[-1]["tag"] += "+" + p["tag"]
            tokens[-1]["morphemes"].append([p["form"], p["tag"]])
            tokens[-1]["morpheme_spans"].append([start, end])
        else:
            tokens.append({"form": source[start:end], "tag": p["tag"], "start": start,
                           "end": end, "morphemes": [[p["form"], p["tag"]]],
                           "morpheme_spans": [[start, end]]})
    return tokens


def boundary(pair, role, article, left, right, coda, receiver, *, authority="direct_analysis",
             status="verified", applicability="eligible", consumes=1, forbidden=(), **extra):
    return {"source_pair": list(pair), "role": role, "selected_article": article,
            "status": status, "applicability": applicability, "authority": authority,
            "left_origin": left, "right_origin": right, "original_coda": coda,
            "original_receiver": receiver, "consumption_count": consumes,
            "forbidden_articles": list(forbidden), **extra}


def add(case_id, family, source, phone, parts, gold, *, packaging="split", sources=(),
        note="", dictionary=(), pauses=(), structure=(), scope="generalization",
        override="forbidden", route="engine.pronounce", reading=None):
    numbered = [{"id": f"p{i}", **p} for i, p in enumerate(parts)]
    payload = {"source": source, "route": route, "packaging": packaging,
               "analysis_tokens": analysis(source, numbered, packaging),
               "canonical_parts": numbered, "pause_boundaries": list(pauses),
               "dictionary_structure": list(dictionary), "grammatical_structure": list(structure)}
    if reading is not None:
        payload["gap_reading"] = reading
    for b in gold:
        b["word_span"] = [0, len(source)]
        for side in ("left", "right"):
            origin = b.get(side + "_origin")
            if origin and origin.startswith("p"):
                b[side + "_origin_span"] = numbered[int(origin[1:])]["span"]
            elif origin and origin.startswith("dict:p") and dictionary:
                item = dictionary[0]["parts"][int(origin[6:])]
                b[side + "_origin_span"] = item[2:4]
            else:
                b[side + "_origin_span"] = None
    CASES.append({"case_id": case_id, "family": family, "evidence_scope": scope,
                  "input": payload, "expected": {"allowed_phones": phone,
                  "boundaries": gold, "whole_phone_override": override,
                  "comparison_scope": "raw_hangul_without_vowel_length"},
                  "sources": list(sources), "note_ko": note})


def structural(relation, left, right, output, **extra):
    return {"relation": relation, "left": left, "right": right,
            "output_category": output, **extra}


# 새 구성의 의미·문법을 먼저 명시하며, 표제 등재 사실로 오해하지 않는다.
for ident, base, phone, tail, pack in [
    ("A15-01", "밥값", "밥까버치", "", "split"),
    ("A15-02", "밥값", "밥까버치", "", "fused"),
    ("A15-03", "집값", "집까버치만", "만", "split"),
    ("A15-04", "책값", "책까버치를", "를", "fused"),
    ("A15-05", "이틀", "이트러치", "", "split"),
    ("A15-06", "사흘", "사흐러치", "", "fused"),
    ("A15-07", "나흘", "나흐러치도", "도", "split"),
    ("A15-08", "보름", "보르머치", "", "split"),
    ("A15-09", "하루", "하루어치", "", "split"),
]:
    n = len(base)
    coda = {"값": "ㅄ", "틀": "ㄹ", "흘": "ㄹ", "름": "ㅁ", "루": ""}[base[-1]]
    pieces = [part(base, "NNG", 0, n), part("어치", "XSN", n, n + 2)]
    if tail:
        pieces.append(part(tail, "JKO" if tail == "를" else "JX", n + 2, n + 3))
    add(ident, "article15_semantic_eochi", base + "어치" + tail, [phone], pieces,
        [boundary((n - 1, n), "semantic_suffix_eochi", "15", "p0", "p1", coda,
                  "어치", applicability="eligible" if coda else "not_required",
                  consumes=1 if coda else 0, forbidden=("14", "17", "29"))],
        packaging=pack, sources=("S15", "SE"),
        structure=[structural("semantic_suffix_derivation", "p0", "p1", "N")],
        note="금액에 해당하는 양 또는 기간에 해당하는 분량이라는 뜻으로 독립 구성했다. 사전 등재 표제라고 주장하지 않는다.")


def pal(ident, source, phone, pieces, left, right, pair, coda, receiver="이", *,
        packaging="split", contraction=False, note="", sources=("S17",)):
    relations = [structural("formal_suffix_derivation", left, right,
                            "ADV" if pieces[int(right[1:])]["tag"] == "XSM" else
                            "N" if pieces[int(right[1:])]["tag"] == "XSN" else "V")]
    if contraction:
        relations.append({"relation": "approved_i_eo_contraction", "left": right,
                          "right": f"p{int(right[1:]) + 1}", "joint_surface_span": list(pair[1:]) + [pair[1] + 1]})
    if left == "p1":
        relations.append({"relation": "nominal_compound", "left": "p0",
                          "right_parts": [left, right], "output_category": "N"})
    add(ident, "article17_formal_i_hi", source, phone, pieces,
        [boundary(pair, "formal_suffix_hi" if receiver == "히" else "formal_suffix_i",
                  "17", left, right, coda, receiver, forbidden=("15", "29"),
                  contracted=contraction)], packaging=packaging, sources=sources,
        structure=relations, note=note)


pal("A17-01", "굳이", ["구지"], [part("굳", "VA", 0, 1), part("이", "XSM", 1, 2)], "p0", "p1", (0, 1), "ㄷ")
pal("A17-02", "굳이", ["구지"], [part("굳", "VA", 0, 1), part("이", "XSM", 1, 2)], "p0", "p1", (0, 1), "ㄷ", packaging="fused")
pal("A17-03", "같이", ["가치"], [part("같", "VA", 0, 1), part("이", "XSM", 1, 2)], "p0", "p1", (0, 1), "ㅌ")
pal("A17-04", "맏이", ["마지"], [part("맏", "XR", 0, 1), part("이", "XSN", 1, 2)], "p0", "p1", (0, 1), "ㄷ")
pal("A17-05", "해돋이", ["해도지"], [part("해", "NNG", 0, 1), part("돋", "VV", 1, 2), part("이", "XSN", 2, 3)], "p1", "p2", (1, 2), "ㄷ", packaging="fused")
pal("A17-06", "벼훑이", ["벼훌치"], [part("벼", "NNG", 0, 1), part("훑", "VV", 1, 2), part("이", "XSN", 2, 3)], "p1", "p2", (1, 2), "ㄾ")
pal("A17-07", "붙이다", ["부치다"], [part("붙", "VV", 0, 1), part("이", "XSV", 1, 2), part("다", "EF", 2, 3)], "p0", "p1", (0, 1), "ㅌ")
pal("A17-08", "핥이다", ["할치다"], [part("핥", "VV", 0, 1), part("이", "XSV", 1, 2), part("다", "EF", 2, 3)], "p0", "p1", (0, 1), "ㄾ")
pal("A17-09", "닫히다", ["다치다"], [part("닫", "VV", 0, 1), part("히", "XSV", 1, 2), part("다", "EF", 2, 3)], "p0", "p1", (0, 1), "ㄷ", "히")
pal("A17-10", "걷히니", ["거치니"], [part("걷", "VV", 0, 1), part("히", "XSV", 1, 2), part("니", "EC", 2, 3)], "p0", "p1", (0, 1), "ㄷ", "히", note="구름이 걷히는 피동 의미이며 걷다의 다른 동형 의미를 섞지 않는다.")
pal("A17-11", "붙이어", ["부치어", "부치여"], [part("붙", "VV", 0, 1), part("이", "XSV", 1, 2), part("어", "EC", 2, 3)], "p0", "p1", (0, 1), "ㅌ", sources=("S17", "S22"))
pal("A17-12", "굳히어", ["구치어", "구치여"], [part("굳", "VA", 0, 1), part("히", "XSV", 1, 2), part("어", "EC", 2, 3)], "p0", "p1", (0, 1), "ㄷ", "히", sources=("S17", "S22"))
pal("A17-13", "붙여", ["부처"], [part("붙", "VV", 0, 1), part("이", "XSV", 1, 2), part("어", "EC", 1, 2)], "p0", "p1", (0, 1), "ㅌ", contraction=True, sources=("S17", "S5", "S36"))
pal("A17-14", "붙였다", ["부쳗따"], [part("붙", "VV", 0, 1), part("이", "XSV", 1, 2), part("었", "EP", 1, 2), part("다", "EF", 2, 3)], "p0", "p1", (0, 1), "ㅌ", contraction=True, packaging="fused", sources=("S17", "S5", "S36"))
pal("A17-15", "굳혀", ["구처"], [part("굳", "VA", 0, 1), part("히", "XSV", 1, 2), part("어", "EC", 1, 2)], "p0", "p1", (0, 1), "ㄷ", "히", contraction=True, sources=("S17", "S5", "S36"))
pal("A17-16", "닫혀", ["다처"], [part("닫", "VV", 0, 1), part("히", "XSV", 1, 2), part("어", "EC", 1, 2)], "p0", "p1", (0, 1), "ㄷ", "히", contraction=True, packaging="fused", sources=("S17", "S5", "S36"))
pal("A17-17", "핥여", ["할처"], [part("핥", "VV", 0, 1), part("이", "XSV", 1, 2), part("어", "EC", 1, 2)], "p0", "p1", (0, 1), "ㄾ", contraction=True, sources=("S17", "S5", "S36"), note="핥이다의 활용형이다. ㄾ의 ㄹ 잔여와 축약 모음의 후속 처리를 함께 요구한다.")


for ident, left, right, tail, phone, packaging in [
    ("A29-01", "솜", "이불", "", "솜니불", "split"),
    ("A29-02", "꽃", "잎", "", "꼰닙", "split"),
    ("A29-03", "꽃", "잎", "이", "꼰니피", "fused"),
    ("A29-04", "꽃", "잎", "이랑", "꼰니피랑", "split"),
    ("A29-05", "풀", "잎", "", "풀립", "split"),
    ("A29-06", "솔", "잎", "을", "솔리플", "fused"),
    ("A29-07", "콩", "잎", "은", "콩니픈", "split"),
    ("A29-08", "밭", "일", "", "반닐", "split"),
    ("A29-09", "밭", "일", "만", "반닐만", "fused"),
    ("A29-10", "집", "일", "", "짐닐", "split"),
    ("A29-11", "삯", "일", "", "상닐", "split"),
    ("A29-12", "밭", "이랑", "이랑", "반니랑이랑", "split"),
]:
    n = len(left)
    end = n + len(right)
    parts = [part(left, "NNG", 0, n), part(right, "NNG", n, end)]
    if tail:
        tag = {"이": "JKS", "을": "JKO", "이랑": "JC", "은": "JX", "만": "JX"}[tail]
        parts.append(part(tail, tag, end, end + len(tail)))
    coda = {"솜": "ㅁ", "꽃": "ㅊ", "풀": "ㄹ", "솔": "ㄹ", "콩": "ㅇ", "밭": "ㅌ", "집": "ㅂ", "삯": "ㄳ"}[left]
    add(ident, "article29_nominal_compound", left + right + tail, [phone], parts,
        [boundary((n - 1, n), "lexical_component", "29", "p0", "p1", coda,
                  right, forbidden=("15", "17"))], packaging=packaging,
        sources=("S29", "S18"), structure=[structural("nominal_compound", "p0", "p1", "N")],
        note="뒤 조사 꼬리의 범위는 합성 명사 성분과 별개다. ㄹ 뒤의 첨가 ㄴ은 후속 유음화를 거친다.")

for ident, noun, coda, phone in [
    ("A29-13", "밭", "ㅌ", "바치랑"),
    ("A29-14", "끝", "ㅌ", "끄치랑"),
    ("A29-15", "솥", "ㅌ", "소치랑"),
]:
    add(ident, "particle_homograph", noun + "이랑", [phone],
        [part(noun, "NNG", 0, 1), part("이랑", "JC", 1, 3)],
        [boundary((0, 1), "formal_particle", "17", "p0", "p1", coda, "이랑", forbidden=("29", "15"))],
        sources=("S17", "S29"), structure=[structural("particle_attachment", "p0", "p1", "N")])


def guard(ident, source, parts, pair, role, coda, receiver, *, phone=None,
          packaging="split", status="excluded", applicability="not_required",
          authority="direct_analysis", forbidden=("15", "17", "29"),
          note="", pauses=(), dictionary=(), structure=(), **extra):
    add(ident, "authority_guard", source, phone, parts,
        [boundary(pair, role, None, "p0", "p1" if len(parts) > 1 else None,
                  coda, receiver, status=status, applicability=applicability,
                  authority=authority, consumes=0, forbidden=forbidden, **extra)],
        packaging=packaging, sources=("SC", "S17", "S5"), note=note,
        pauses=pauses, dictionary=dictionary, structure=structure, scope="guard")


guard("G-01", "마디", [part("마디", "NNG", 0, 2)], (0, 1), None, "", "디", phone=["마디"], note="한 형태소 안의 디는 원형 ㄷ+접미사 이가 아니다.")
guard("G-02", "견디다", [part("견디", "VV", 0, 2), part("다", "EF", 2, 3)], (0, 1), None, "", "디", phone=["견디다"], note="V 내부 철자를 분해하여 제17항 권한을 만들지 않는다.")
guard("G-03", "곧이어", [part("곧", "MAG", 0, 1), part("이어", "MAG", 1, 3)], (0, 1), "lexical_component", "ㄷ", "이어", phone=["고디어"], note="곧이의 파생 이와 달리 독립 부사 이어다. 공식 해설의 비구개음화 어휘 사실을 보존한다.")
guard("G-04", "버텨", [part("버티", "VV", 0, 2), part("어", "EC", 1, 2)], (0, 1), None, "", "티", phone=["버텨"], note="원형의 ㅌ과 ㅣ가 같은 어간 출현 안에 있다. 활용 축약만으로 접미사 이가 생기지 않는다.")
guard("G-05", "밭에", [part("밭", "NNG", 0, 1), part("에", "JKB", 1, 2)], (0, 1), "formal_particle", "ㅌ", "에", phone=["바테"], forbidden=("15", "17", "29"), note="조사라도 원형 수신 모음이 ㅣ가 아니면 제17항 조건이 아니다.")
guard("G-06", "밭의", [part("밭", "NNG", 0, 1), part("의", "JKG", 1, 2)], (0, 1), "formal_particle", "ㅌ", "의", phone=["바틔", "바테"], note="조사 의의 규범 변이는 제5항 범위이며, 이를 원형 이로 역산하지 않는다.")
guard("G-07", "값을", [part("값", "NNG", 0, 1), part("을", "JKO", 1, 2)], (0, 1), "formal_particle", "ㅄ", "을", phone=["갑쓸"], note="겹받침의 형식 조사 연음이다. -어치의 의미 정책을 형식 수신자로 확대하지 않는다.")
guard("G-08", "꽃이랑", [part("꽃", "NNG", 0, 1), part("이랑", "JC", 1, 3)], (0, 1), "formal_particle", "ㅊ", "이랑", phone=["꼬치랑"], note="원형 받침 ㅊ의 정상 연음이다. 결과 소리 ㅊ만으로 제17항 성공을 주장하지 않는다.")
guard("G-09", "이틀어치", [part("이틀어치", "NNG", 0, 4)], (1, 2), None, None, None, packaging="opaque", status="unresolved", applicability="unresolved", authority="missing_internal_structure", note="전체 NNG는 내부 접미사 신원을 증명하지 않는다. 완성 발음은 강제하지 않는다.")
guard("G-10", "굳이", [part("굳이", "MAG", 0, 2)], (0, 1), None, None, None, packaging="opaque", status="unresolved", applicability="unresolved", authority="missing_internal_structure", note="MAG 끝 이 패턴은 원형·파생 권한을 증명하지 않는다. 굳이의 규범 발음 부정이 아니라 제공된 증거의 한계다.")
guard("G-11", "꽃이랑", [part("꽃이랑", "NNG", 0, 3)], (0, 1), None, None, None, packaging="opaque", status="unresolved", applicability="unresolved", authority="missing_internal_structure", note="정확 표제/의미와 성분 소유가 없는 NNG 통짜에서 합성 경계를 발명하지 않는다.")
guard("G-12", "밭이랑", [part("밭", "NNG", 0, 1), part("이랑", "NNG", 1, 3)], (0, 1), "lexical_component", "ㅌ", "이랑", status="verified", applicability="blocked", pauses=(1,), note="원문 휴지가 증명된 내부 합성 경계의 음운 소비를 막는다.", structure=[structural("nominal_compound", "p0", "p1", "N")])
guard("G-13", "값어치", [part("값", "NNG", 0, 1), part("어치", "XSN", 1, 3)], (0, 1), "semantic_suffix_eochi", "ㅄ", "어치", status="verified", applicability="blocked", pauses=(1,), note="어치 신원이 참이어도 휴지를 넘지 않는다.", structure=[structural("semantic_suffix_derivation", "p0", "p1", "N")])
guard("G-14", "밭이랑", [part("밭", "NNG", 0, 1), part("이랑", "JC", 1, 3)], (0, 1), "formal_particle", "ㅌ", "이랑", status="unresolved", applicability="unresolved", authority="conflicting_same_identity_structure", dictionary=[{"identity": "밭이랑:명사:두둑과_고랑", "owner_span": [0, 3], "parts": [["밭", "NNG", 0, 1], ["이랑", "NNG", 1, 3]], "relation": "nominal_compound", "identity_claim": "same_selected_identity"}], note="명사 의미 신원을 동시에 확정하고 JC 직접 구조를 제공한 모순 입력이다. 이 한 사례만 의도적 의미 구조 충돌이며 정상 조사 동형 사례와 구별한다.")
guard("G-15", "붙여", [part("붙", "VV", 0, 1), part("이", "XSV", 1, 2), part("아", "EC", 1, 2)], (0, 1), "formal_suffix_i", "ㅌ", "이", status="unresolved", applicability="unresolved", authority="unsupported_surface_proof", note="붙+이+아는 붙여를 재생성하지 못한다. 음절 철자만 보고 이+어로 고치지 않는다. 의도적인 표면 증명 실패로서 생성자 불량과 구별한다.")
guard("G-16", "밭이다", [part("밭", "NNG", 0, 1), part("이", "VCP", 1, 2), part("다", "EF", 2, 3)], (0, 1), None, "ㅌ", "이", status="unresolved", applicability="unresolved", authority="contract_scope_deferred_vcp", note="규범상 [바치다]와 별개로 이번 계약은 미검증 VCP 가족의 새 소비 권한을 허가하지 않는다. 발음 정오 점수에는 넣지 않는다.")
guard("G-17", "높이를", [part("높", "VA", 0, 1), part("이", "XSN", 1, 2), part("를", "JKO", 2, 3)], (0, 1), "formal_suffix_i", "ㅍ", "이", phone=["노피를"], note="명사 파생 접미사 이의 형식 연음이다. XSN 전체를 실질 수신자로 만들면 [노비를]라는 오답이 생긴다.")
guard("G-18", "넓이", [part("넓", "VA", 0, 1), part("이", "XSN", 1, 2)], (0, 1), "formal_suffix_i", "ㄼ", "이", phone=["널비"], note="겹받침의 형식 접미사 연음이다. 모든 XSN에 제15항을 적용하여 [너비]로 바꾸지 않는다.")

add("A29-16", "single_consumption", "솜이불", ["솜니불"],
    [part("솜", "NNG", 0, 1), part("이불", "NNG", 1, 3)],
    [boundary((0, 1), "lexical_component", "29", "p0", "p1", "ㅁ", "이불", forbidden=("15", "17"))],
    sources=("S29", "SC"), structure=[structural("nominal_compound", "p0", "p1", "N"), structural("nominal_compound", "p0", "p1", "N")],
    note="같은 구조 사실이 중복 제출되어도 같은 물리 경계의 소비 권한은 한 번이다.")


# 이 아홉 표제의 원래 존재는 깨끗한 계약에서 전달된 런타임 사실이다.
MIGRATION = [
    ("M-01", "맛있다", ["마딛따", "마싣따"], "VA", None, "allowed_preserved"),
    ("M-02", "멋있다", ["머딛따", "머싣따"], "VA", None, "allowed_preserved"),
    ("M-03", "값어치", ["가버치"], "NNG", "15", "forbidden"),
    ("M-04", "공권력", ["공꿘녁"], "NNG", None, "allowed_preserved"),
    ("M-05", "값있다", ["가빋따"], "VA", None, "allowed_preserved"),
    ("M-06", "뜻있다", ["뜨딛따"], "VA", None, "allowed_preserved"),
    ("M-07", "알심", ["알씸"], "NNG", None, "allowed_preserved"),
    ("M-08", "곧이곧대로", ["고지곧때로"], "MAG", "17", "forbidden"),
    ("M-09", "밭이랑", ["반니랑"], "NNG", "29", "forbidden"),
]


def dictfact(word):
    first, second, tag, relation = {
        "값어치": ("값", "어치", "XSN", "semantic_suffix_derivation"),
        "곧이곧대로": ("곧", "이", "XSM", "adverb_suffix_derivation"),
        "밭이랑": ("밭", "이랑", "NNG", "nominal_compound"),
    }[word]
    return {"identity": word + (":명사:두둑과_고랑" if word == "밭이랑" else ":정확표제"),
            "owner_span": [0, len(word)], "parts": [[first, "VA" if word == "곧이곧대로" else "NNG", 0, 1],
            [second, tag, 1, 2 if word == "곧이곧대로" else len(word)]],
            "relation": relation, "source_id": "SC"}


for ident, word, phones, tag, article, override in MIGRATION:
    gold, facts = [], []
    if article:
        role = {"15": "semantic_suffix_eochi", "17": "formal_suffix_i", "29": "lexical_component"}[article]
        coda = {"15": "ㅄ", "17": "ㄷ", "29": "ㅌ"}[article]
        receiver = {"15": "어치", "17": "이", "29": "이랑"}[article]
        gold = [boundary((0, 1), role, article, "dict:p0", "dict:p1", coda, receiver,
                         authority="exact_identity_dictionary_structure", forbidden=tuple(x for x in ("15", "17", "29") if x != article))]
        facts = [dictfact(word)]
    pieces = ([part(word[:-1], tag, 0, len(word) - 1), part("다", "EF", len(word) - 1, len(word))]
              if tag == "VA" and word.endswith("다") else [part(word, tag, 0, len(word))])
    add(ident, "nine_entry_migration_preservation", word, phones,
        pieces, gold, packaging="split" if len(pieces) > 1 else "opaque", sources=("SC", "S15", "S17", "S29", "SM"),
        dictionary=facts, scope="migration_only", override=override, route="G2P",
        note="원래 매핑 보존/이관 전용이다. 미등록 어기 일반화 점수에 합치지 않는다. 불투명 분석도 정확 구조 사실로 지원하는 세 표제는 완성 발음 치환 없이 계산해야 한다.")

for ident, word, tail, tag, phone, article in [
    ("M-10", "값어치", "를", "JKO", "가버치를", "15"),
    ("M-11", "곧이곧대로", "만", "JX", "고지곧때로만", "17"),
    ("M-12", "밭이랑", "이랑", "JC", "반니랑이랑", "29"),
]:
    n = len(word)
    role = {"15": "semantic_suffix_eochi", "17": "formal_suffix_i", "29": "lexical_component"}[article]
    add(ident, "nine_entry_migration_tail", word + tail, [phone],
        [part(word, "MAG" if article == "17" else "NNG", 0, n), part(tail, tag, n, n + len(tail))],
        [boundary((0, 1), role, article, "dict:p0", "dict:p1", {"15": "ㅄ", "17": "ㄷ", "29": "ㅌ"}[article],
                  {"15": "어치", "17": "이", "29": "이랑"}[article], authority="exact_identity_dictionary_structure")],
        sources=("SC",), dictionary=[dictfact(word)], scope="migration_only", route="G2P",
        note="정확 표제 소유 범위는 꼬리 앞에서 끝난다. 조사가 내부 실질/형식 성분 신원을 덮지 않는다.")

for ident, host, tail, tag, phones in [
    ("M-13", "맛있", "는", "ETM", ["마딘는", "마신는"]),
    ("M-14", "멋있", "게", "EC", ["머딛께", "머싣께"]),
    ("M-15", "공권력", "도", "JX", ["공꿘녁또"]),
    ("M-16", "값있", "는", "ETM", ["가빈는"]),
    ("M-17", "뜻있", "게", "EC", ["뜨딛께"]),
    ("M-18", "알심", "도", "JX", ["알씸도"]),
]:
    n = len(host)
    add(ident, "nine_entry_migration_tail", host + tail, phones,
        [part(host, "VA" if tag in ("EC", "ETM") else "NNG", 0, n), part(tail, tag, n, n + len(tail))],
        [], sources=("SC", "SM", "S18"), scope="migration_only", route="G2P", override="allowed_preserved",
        note="아직 이관하지 않은 정확 어휘 경로의 합법적 활용/조사 꼬리 보존이다. 모든 X+있을 허용하는 일반 규칙의 근거가 아니다.")


def write_jsonl(name, records):
    (ROOT / name).write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in records), encoding="utf-8", newline="\n")


def main():
    if (ROOT / "FREEZE.json").exists():
        raise SystemExit("기존 동결이 있습니다. 원래 기대값을 다시 생성하지 않습니다.")
    assert 40 <= len(CASES) <= 80
    write_jsonl("cases.jsonl", CASES)
    invalid = [
        {"case_id": "C-01", "model": "AnalysisToken", "args": {"form": "밭", "tag": "NNG", "normalized_start": -1, "normalized_end": 1}, "expected_exception": "ValueError", "scope": "constructor_only", "note_ko": "음수 토큰 시작 좌표를 생성자가 거부해야 한다. 음운 방어 성공으로 세지 않는다."},
        {"case_id": "C-02", "model": "AnalysisToken", "args": {"form": "붙여", "tag": "VV+XSV+EC", "normalized_start": 0, "normalized_end": 2, "morphemes": [["붙", "VV"], ["이", "XSV"], ["어", "EC"]], "morpheme_spans": [[0, 1], [1, 3], [1, 2]]}, "expected_exception": "ValueError", "scope": "constructor_only", "note_ko": "원형 출현 범위가 표면 토큰 밖으로 벗어난다."},
        {"case_id": "C-03", "model": "AnalysisToken", "args": {"form": "밭이", "tag": "NNG+JKS", "normalized_start": 0, "normalized_end": 2, "morphemes": [["밭", "NNG"], ["이", "JKS"]], "morpheme_spans": [[False, 1], [1, 2]]}, "expected_exception": "ValueError", "scope": "constructor_only", "note_ko": "불리언 원형 범위를 좌표로 허용하지 않는다."},
    ]
    write_jsonl("constructor_invalid.jsonl", invalid)
    rows = ["# R42 독립 고정 사례 목록", "", "실행 전 독립 구성한 표면 발음/권한 기대값이다. `null` 발음은 채점하지 않으며 규범상 발음 부정이 아니다.", "", "| ID | 가족 | 입력 | 허용 표면 발음 | 증거 범위 |", "|---|---|---|---|---|"]
    for c in CASES:
        phones = c["expected"]["allowed_phones"]
        rows.append(f"| {c['case_id']} | {c['family']} | {c['input']['source']} | {' / '.join(phones) if phones is not None else '권한만 검사'} | {c['evidence_scope']} |")
    (ROOT / "Frozen_Case_Index_KO.md").write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")
    names = ["cases.jsonl", "constructor_invalid.jsonl", "Frozen_Case_Index_KO.md",
             "Normative_References_KO.md", "Boundary_Observation_Protocol_KO.md",
             "Source_Blind_Attestation_KO.md", "run_refs.py", "build_frozen_refs.py"]
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}
    manifest = {"format": "r42-independent-freeze-v1", "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
                "runtime_executed_before_freeze": False, "kiwi_executed_before_freeze": False,
                "candidate_inspected": False, "cases": len(CASES), "constructor_invalid_cases": len(invalid),
                "families": dict(Counter(c["family"] for c in CASES)), "sha256": hashes,
                "adapter_may_change": True, "gold_may_change_after_runtime": False}
    (ROOT / "FREEZE.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"cases": len(CASES), "constructor_invalid": len(invalid), "freeze_sha256": hashlib.sha256((ROOT / "FREEZE.json").read_bytes()).hexdigest()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
