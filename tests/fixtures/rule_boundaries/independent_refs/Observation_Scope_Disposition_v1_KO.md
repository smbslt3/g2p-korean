# R42 저장 결과의 부분 관찰 범위 보충 버전 1

이 보충은 보존된 v6 JSON의 관찰 필드만 후처리한다. 새 런타임·Kiwi·기준선 실행, 구현 검사, 골드 읽기·수정은 수행하지 않았다. 결과를 본 뒤 추가한 관찰 범위 해석이며 새 규범 정답이나 미접촉 홀드아웃으로 표현하지 않는다.

원본 JSON과 v5/v6 비교는 그대로 보존한다. 새 JSON은 원본 경로와 SHA256, 원래 비교, 부분 관찰 비교를 함께 기록한다. 원시 문법 상태나 반환 DTO를 고치지 않는다.

| 정확한 네이티브 조건 | 부분 관찰 처리 | 계속 유지하는 검사 |
|---|---|---|
| verified + not_required + prior_independent_lexical_recipient | 새 대상 역할이나 기원이 계산되지 않았으면 해당 필드만 unbound | 문법 상태, 적용성, 실제 소비와 조항 |
| unresolved + blocked + phonological_barrier, 역할·기원 미계산 | 해당 물리 역할 판단에 사용할 문법 상태도 unbound. grammar DTO 존재만으로 물리 역할 검증을 추론하지 않음 | blocked, 소비 0회, 금지 조항 |
| unresolved + unresolved + whole_surface_evidence_unavailable | 인증되지 않은 물리 역할·기원은 unbound. authority도 unbound이며 명시적 사유를 unsupported_surface_proof로 별도 표시 | unresolved 상태 요구, 적용성, 소비와 조항 |

`source='analysis'`는 입력 기원의 명칭이며 직접 증명의 강도가 아니다. 전체 표면 증명 불가 사유로 긍정적인 역할·권한 증명을 만들지 않는다. 이미 계산된 역할의 모순, 실제 출처 충돌은 실패로 남긴다.

eligible 경계, 양의 실제 소비, 소비 조항 또는 실제 eligible/변경/규칙 반환 사건이 있으면 이 완화 분류 자체를 적용하지 않는다. 기존 적용성·소비 횟수·금지 조항·선택 조항 검사는 고치지 않는다. 발음·실제 사건 일관성 등 다른 지표도 그대로 유지한다.

정확한 `-I -X utf8 -B` 합성 점검 19개가 통과했다. 실제 eligible 동작, 소비·조항, 반환 사건, 미해결 긍정 전이 요구, 출처 충돌, 계산된 오역할, 원래 발음·사건 실패를 숨기지 않는 음성 검사를 포함한다. 생산 모듈을 가져오지 않았다.

보존된 candidate06 결과의 네 행에서 role 2개, status 2개, authority 1개의 리터럴 실패를 미연결 관찰로 표시했다. 원래 v6의 경계 필드 실패 네 행은 새 뷰에서 partial_unbound다. 이는 네 행의 완전한 증명 통과가 아니다. 기존 부재 전제 미충족·미전달 입력·범위 변경 처리는 그대로 유지한다.

원래 발음 실패 한 행은 그대로 남는다. A17-14 한 행의 별도 개발 정답 교정은 적용하지 않았다. 전체 결과는 **부분 관찰**이며 **78/78 완전 증명**으로 보고하지 않는다.

실행한 후처리 명령:

```powershell
.venv\Scripts\python.exe -I -X utf8 -B output/g2p_progressive_round42_20261028/independent_refs/observation_scope_postprocess_v1.py --input output/g2p_progressive_round42_20261028/independent_refs/candidate06_controlled_v6_final.json --report output/g2p_progressive_round42_20261028/independent_refs/candidate06_controlled_v6_observation_v1.json
```

필요한 지원 파일은 후처리 Python 파일과 선택한 보존 v6 JSON뿐이다. 프로젝트 패키지, 후보 원본, 골드 또는 이전 어댑터를 불러오지 않는다. 원본 JSON을 덮어쓰거나 이미 존재하는 결과 경로를 사용할 수 없다. `OBSERVATION_SCOPE_V1_FREEZE.json`에 도구·합성 영수증·보충 문서·새 결과와 원본 결과 해시를 고정한다.
