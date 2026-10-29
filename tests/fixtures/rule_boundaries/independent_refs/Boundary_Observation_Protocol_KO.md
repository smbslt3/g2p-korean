# R42 경계 관찰의 휴대 가능한 계약

이 파일과 사례 기대값은 구현 선택 전에 고정한다. 구현의 파일명·클래스명에 맞추는 어댑터는 나중에 추가할 수 있다. 그때 기대값·원문·분석·사전 구조 사실을 바꾸지 않는다.

## 입력

`cases.jsonl`의 `input`만 어댑터의 `evaluate(payload)`에 전달한다. 기대값, 규범 링크, 평가 메모는 전달하지 않는다. 원문 좌표는 Python Unicode code point이며 NFC 한글을 사용한다. 원형 출현 `p0`, `p1` 등은 명시된 순서의 식별자다. 같은 형태소가 반복되어도 합치지 않는다.

`analysis_tokens`는 실제 `AnalysisToken` 생성자 필드에 대응한다. `canonical_parts`는 그 분석이 보존해야 하는 원형 출현·범위의 독립 명세다. `grammatical_structure`는 직접 분석이 주장하는 결합 관계를 명확히 적은 것이다. 단순 토큰 인접이나 전체 단어 품사만으로 합성 관계를 만들어서는 안 된다. 채택 API가 이러한 구조를 표현하지 못하면 어댑터에서 조용히 추정하지 말고 입력 표현의 한계로 보고한다. 원형별 표면 범위가 같은 축약 입력은 각 원형의 자모 유래를 보존해야 한다.

`dictionary_structure`는 정확 의미/표제 소유 범위에 귀속되는 보충 사실이다. 완성 발음을 포함하지 않는다. 이 평가용 사전 사실을 런타임 경로에 주입할 경우 그 사실 출처와 주입 지점을 결과에 남긴다. 이미 배포된 동등 구조 자료를 쓰는 경우도 원래 자료의 신원·범위를 보여야 한다. 분석이 다른 정상 동형 역할을 확정하면 명사 사전 사실을 무시한다. G-14처럼 동일 신원 안의 구조가 실제로 모순될 때는 미해결이다.

붙은 단어의 `route`는 `engine.pronounce` 또는 `G2P`다. GAP sidecar를 붙은 단어의 대체 엔진으로 사용하지 않는다. 향후 공백 사례를 추가하는 별도 집합은 원문에 ASCII 공백이 실제 있어야 하며, 연결 읽기 관계를 명시해야 한다. 이번 고정 78개 사례에는 공백 사례가 없고 GAP 호출은 허용하지 않는다.

## 관찰값

어댑터는 아래 필드를 실제 실행 증거에서 반환한다. 기대값에서 그대로 복사하거나 음운 결과를 역산하여 증명을 만드는 것은 금지한다.

```json
{
  "phone": "실제 공개 경로 결과",
  "route": "engine.pronounce",
  "analysis_source": "supplied",
  "whole_phone_override_used": false,
  "boundaries": [{
    "source_pair": [0, 1],
    "role": "formal_suffix_i",
    "selected_article": "17",
    "status": "verified",
    "applicability": "eligible",
    "authority": "direct_analysis",
    "left_origin": "p0",
    "right_origin": "p1",
    "original_coda": "ㅌ",
    "original_receiver": "이",
    "consumption_count": 1,
    "consumed_articles": ["17"],
    "contracted": true,
    "native_evidence": {
      "word_certificate": {},
      "surface_proof": {},
      "boundary_record": {}
    }
  }],
  "native_evidence": {"invocation": {}, "override_audit": {}}
}
```

빈 객체는 모양 설명일 뿐이며 실제 증거에서 빈 객체를 반환하면 통과하지 못한다. 네이티브 필드 이름을 휴대 필드로 변환한 매핑은 어댑터 문서에 적는다. 논리 상태를 새로 결정하는 규범 규칙은 어댑터에 구현하지 않는다. `dict:p0` 등은 정확 사전 구조의 원형 출현을 뜻하며 원래 분석 토큰을 덮은 새 토큰이 아니다.

`consumption_count`는 이 물리 경계에 대한 제15·17·29항 권한 소비 횟수다. 후속 받침·비음화·경음화 사건 수와 다르다. G-12·13의 `selected_article=null`은 장벽 때문에 소비자를 실행하지 않았다는 뜻이며 구조의 역할 자체는 보존된다. A15-09는 문법 역할이 검증되었으나 앞 받침이 없어 소리 이동이 필요하지 않다. 이 경우 문법 실패로 보고하지 않는다.

`whole_phone_override_used`는 이번 세 표제의 치환을 제거한 일반 경로와 나머지 여섯 기존 경로를 구별한다. migrated 세 표제 및 일반화 사례에서 `true`이면 표면 발음이 같아도 실패다. 여섯 보존 경로는 `true`여도 보존 점수만 받을 수 있다. 원형별 구조 사전 자료를 사용한 것은 완성 발음 치환으로 세지 않는다.

## 실행

```powershell
python output/g2p_progressive_round42_20261028/independent_refs/run_refs.py --validate-only
python output/g2p_progressive_round42_20261028/independent_refs/run_refs.py --adapter ABSOLUTE_ADAPTER.py --report ABSOLUTE_REPORT.json
```

어댑터는 별도 모듈의 `evaluate(payload)`와 `construct_invalid(record)`를 제공한다. `construct_invalid`는 생성만 시도하여 예외 형식명 또는 `null`을 반환한다. C 사례는 후보 음운 경로를 호출하지 않고, 생성자 거부를 음운 방어 통과로 세지 않는다. 실행기는 동결 해시를 검증한 뒤에만 어댑터를 가져온다. 결과는 일반화·방어·기존 이관·생성자를 분리하며 누락 증거를 통과로 세지 않는다.
