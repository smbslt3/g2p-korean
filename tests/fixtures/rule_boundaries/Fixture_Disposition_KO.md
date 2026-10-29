# R42 휴대 회귀 픽스처 구성 영수증

이 폴더는 원래 동결 참조, 선택 src 평가기, 실제 네이티브 관찰 바인딩, 부분 관찰 후처리기와 한 행 개발 교정 정책을 포함한다. 저장된 런타임 보고서는 복사하지 않았다. 구현 원본·후보 구현 본문도 포함하지 않는다.

`independent_refs/`에는 원본 `FREEZE.json`이 요구하는 모든 파일과 v6의 전이 지원 모듈을 바이트 그대로 보존했다. `contract/`의 정확 구조 사실과 `cleanroom/.../Boundary_API_KO.json`은 이미 v6에 동결된 참조 메타데이터다. 뒤 경로는 원래 평가기의 메타데이터 영수증 경로를 유지하기 위한 것이며 실행 원본 선택과 무관하다. 어떤 구현도 그 경로에서 가져오지 않는다.

하네스는 이 전체 트리를 pytest 임시 폴더로 복사한다. 평가기와 후처리기의 HERE/새 결과 경로 제한은 그 임시 복사본 안에서 작동한다. 실제 프로젝트 입력은 `-I -X utf8 -B` 별도 프로세스에 명시적으로 전달한 `--src <저장소>/src` 하나뿐이다. 설치본·편집 가능 설치 대체를 금지하며 실제 모듈 출처와 원본 불변 영수증을 확인한다.

검사 범위는 다음과 같다.

- 원래 78행과 생성자 거부 3행의 개수·신원을 유지하고 실제 발음을 동결 문자열과 비교한다.
- 제15·17·29항의 실제 발음 전환, 경계의 적용성·선택 조항·소비 횟수·금지 조항을 확인한다. 실제 네이티브 값으로 연결됐거나 실제 eligible 기록·사건이 있으면 이 동작 필드는 passed여야 한다. 지원되지 않은 관찰은 partial_unbound에 속한 unbound로 보존하며 통과로 다시 쓰지 않는다.
- 실제 소비는 검증된 eligible 경계에서 최대 한 번이어야 한다. 일반화의 완성 발음 치환 금지, 기존 발음과 외부 조사 꼬리 보존을 함께 확인한다.
- 정확 사실로 부재 전제가 깨진 가드, 미전달 의미 신원 가드, 새 VCP 범위는 기존의 명시적 별도 처리를 유지한다. 한 보충 메타데이터 가드는 발음 정확도 점수로 세지 않는다.
- 역할·기원 등 미연결 사실은 부분 관찰로 남긴다. 이 하네스는 78/78 전체 경계 증명이나 새 미접촉 홀드아웃을 주장하지 않는다.

`normative_disposition_A17_14_v1.json`은 기존 `EVALUATOR_V5_FREEZE.json`의 해시로 동결된 정책이다. `score_phone_correction_v1.py`는 원래 결과의 발음 점수와 그 한 행만 별도 교정한 개발 점수를 함께 반환한다. 원본 cases와 기본 평가기 점수는 고치지 않는다. 교정 정책이 없거나 동결 해시가 다르면 의존성 실패이며 새로운 정답을 만들지 않는다.

준비 과정에서는 AST 구문 검사와 임시 트리의 합성 점검만 수행했다. 정확한 `-I -X utf8 -B` 실행에서 네이티브 평가기 22개, 관찰 범위 후처리기 19개, 별도 교정 점수기 4개의 직접 점검이 통과했다. 실제 프로젝트 런타임과 pytest 회귀 실행은 수행하지 않았다. 기존 테스트는 포장 방식만 읽었으며 구현 src, 후보 본문, 이전 비공개 자료와 새 후보 결과를 읽지 않았다.

하네스 보충 버전 2는 이미 동결된 네이티브 어댑터의 동작 관찰 부재도 부분 미연결로 유지한다. 원래 하네스·이 문서·픽스처 목록은 R42 독립 참조 폴더에 별도 보존했다. 이 수리는 하네스의 무조건 passed 요구만 좁혔으며 실제 발음·사건 일관성·치환 금지·계산된 필드 실패 검사를 바꾸지 않았다. 생산 모듈 없이 합성 DTO로 부재 관찰, 연결된 통과/실패, 실제 eligible 기록·반환 사건을 확인한 8개 점검이 통과했다.

집중 실행 명령:

```powershell
.venv\Scripts\python.exe -m pytest -q tests/test_rule_boundaries.py
```

저장된 결과의 교정 점수 명령:

```powershell
.venv\Scripts\python.exe -I -X utf8 -B tests/fixtures/rule_boundaries/score_phone_correction_v1.py --result <보존된-v6-결과.json> --policy tests/fixtures/rule_boundaries/independent_refs/normative_disposition_A17_14_v1.json --policy-freeze tests/fixtures/rule_boundaries/independent_refs/EVALUATOR_V5_FREEZE.json --report <새-교정점수.json>
```

교정 점수 스키마는 `raw_phone_counts_by_scope`, `development_corrected_phone_counts_by_scope`, `one_row.raw_phone_state`, `one_row.development_corrected_phone_state`다. `non_phone_metrics_modified=false`, `full_boundary_proof_claim=false`를 함께 기록한다.

부분 관찰 후처리기는 `--input <보존된-v6.json> --report <새-sidecar.json>`을 받는다. 입력·출력은 실행한 후처리기와 같은 HERE 폴더 안에 두며 기존 결과를 덮어쓸 수 없다. 순수 함수 `process_saved(saved_dict)`도 제공한다. 스키마의 `rows[].raw_v6_metrics`와 `observation_metrics`, `observation_scope_changes`를 나란히 보며, `partial_observation_only=true`, `full_78_of_78_proof_claim=false`를 유지한다.
