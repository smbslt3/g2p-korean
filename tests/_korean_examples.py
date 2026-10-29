"""런타임 사전과 분리한 공식 규정 예시 정답을 읽는다."""

import json
from pathlib import Path


OFFICIAL_EXAMPLES = json.loads(
    Path(__file__).with_name("fixtures").joinpath("korean_official_examples.json").read_text(encoding="utf-8")
)
