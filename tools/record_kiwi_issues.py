"""G2P를 경유하지 않고 누적 이슈 후보의 Kiwi 공개 API 결과를 보존한다."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import sys


def token_record(token):
    return {"form": token.form, "tag": token.tag, "start": token.start, "length": token.len}


def matches_target(tokens, case):
    target = case.get("target")
    if target is None:
        return None
    relevant = [token for token in tokens if token["start"] < target["end"] and token["start"] + token["length"] > target["start"]]
    actual = [(token["form"], token["tag"]) for token in relevant]
    return actual in [[tuple(pair) for pair in variant] for variant in target["accepted"]]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, default=Path("docs/KIWI_ISSUE_LEDGER.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", choices=("cong", "cong-global"), default="cong")
    parser.add_argument("--top-n", type=int, default=5)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("기존 이슈 증거를 덮어쓰지 않습니다.")
    if not 1 <= args.top_n <= 20:
        parser.error("--top-n은 1~20이어야 합니다.")
    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    from kiwipiepy import Kiwi

    kiwi = Kiwi(model_type=args.model)
    rows = []
    for case in ledger["cases"]:
        for example in case["examples"]:
            modes = []
            for name, options in (("default", {}), ("components", {"split_complex": True, "saisiot": True})):
                tokens = [token_record(token) for token in kiwi.tokenize(example["input"], **options)]
                analyses = [{"score": float(score), "tokens": [token_record(token) for token in tokens]}
                            for tokens, score in kiwi.analyze(example["input"], top_n=args.top_n, **options)]
                modes.append({"mode": name, "options": options, "tokens": tokens,
                              "target_matches": matches_target(tokens, example), "analyses": analyses})
            rows.append({"case_id": case["id"], "classification": case["classification"],
                         "role": example["role"], "input": example["input"], "target": example.get("target"), "modes": modes})
    record = {"created_utc": datetime.now(timezone.utc).isoformat(), "python": sys.executable,
              "kiwipiepy": version("kiwipiepy"), "model_package": version("kiwipiepy-model"), "model_type": args.model,
              "ledger_sha256": hashlib.sha256(args.ledger.read_bytes()).hexdigest(), "top_n": args.top_n,
              "interpretation": "target_matches는 명시한 문맥·의도에 대한 대조이며 중의적 단편의 전역 정답 판정이 아니다.", "rows": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"cases": len(ledger["cases"]), "examples": len(rows), "version": record["kiwipiepy"], "model": args.model}, ensure_ascii=False))


if __name__ == "__main__":
    main()
