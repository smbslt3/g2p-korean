# R42 네이티브 증거와 음운 적용성의 cold 투영 계약 버전 1

제05 후보 결과를 보지 않고 고정 정의와 깨끗한 계약만 사용했다. 원래 골드·원시 비교·기본 v5는 수정하지 않는다. 아래는 별도 개발 해석 뷰이며 원시 필드도 함께 보존한다.

네이티브 `status`는 문법 근거 상태, `article`은 후보 규칙 가족, `applicability`는 실제 소비 선택의 적용성이다. 이 세 축을 한 상태처럼 비교하지 않는다.

| 네이티브 상태/적용성 | 문법 근거 | 논리적 음운 적용성 | 선택 조항 |
|---|---|---|---|
| verified + eligible | verified 그대로 | eligible | 실제 후보 article |
| verified + not_required | verified 그대로 | excluded | 없음 |
| unresolved + unresolved | 미해결 그대로 | unresolved | 없음 |
| blocked | 원래 상태 그대로. 계산하지 않은 사실은 미연결 | blocked | 없음 |

고정 기대 `status=verified`는 문법 근거 축과 비교한다. 고정 음운 가드의 `status=excluded`는 `verified+not_required`인 경우 논리적 음운 제외와 비교할 수 있다. 이를 네이티브 status를 excluded로 고쳐 기록하는 일로 취급하지 않는다. 그 밖의 원시 상태는 자동으로 바꾸지 않는다. `not_required`의 후보 article은 남기되 선택 조항은 없음으로 투영한다.

차단이 역할/원형 계산보다 먼저 일어나 `role`이나 원형 근거가 None이면 해당 사실은 미연결이다. None을 긍정적 부재 증명이나 다른 역할의 오답으로 사용하지 않는다. 계산된 역할·출처·원형의 명백한 모순까지 숨기지 않는다. 차단 적용성과 실제 소비 0회는 계속 확인한다.

실제 적용 사건은 이 투영으로 삭제하거나 0회로 만들지 않는다. `not_required/blocked/unresolved`인데 실제 eligible 사건이 있거나, 문법 미검증 경계를 실제 적용했다면 일관성 실패다. eligible 상태의 잘못된 조항·소비·변환은 그대로 실패다. 출처 충돌과 미지원 표면 증명 가드도 그대로 유지한다.

`legacy_structure_delegation`은 원래 상태·원형·표면 증명을 유지한 not_required 위임으로 취급한다. 원래 grammatical status를 제외/미해결로 다시 쓰지 않고 실제 소비도 만들어 내지 않는다. `formal_ending_i`/`predicate_inflection`/`ending_grammar`는 네이티브의 별도 형식 어미 역할로 보존하며 접미사 역할로 바꾸지 않는다.

G16의 이전 VCP 보류와 G10의 정확 구조 부재 전제는 아래 별도 개발 범위/전제 판정으로 구분한다. 어느 경우에도 실제 발음에서 권한을 역산하지 않고, 조건이 충족되지 않은 옛 음성 가드를 통과로 세지 않는다.
