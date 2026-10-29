# R41 독립 기대값 고정 및 실행 계약

이 폴더는 독립 검증 작성자만 작성했다. 검토한 프로젝트 내용은 승인된 자체 `src` 및 그와 동등한 R40 승인 소스 사본, R39 접두 범위 계약, R41 공유 문법 계약과 바깥 꼬리 제2판이다. 외부 G2P 구현, 기존 시험·픽스처·정답·평가 출력, 후보 구현, 비공개 집합을 보지 않았다. 기대값 고정 전 프로젝트 모듈·Kiwi·G2P를 가져오거나 실행하지 않았다.

`build_reference.py`는 표준 라이브러리만 사용하여 `frozen_cases.json`을 작성한다. `run_frozen.py`도 모듈 최상위에서는 표준 라이브러리만 가져오며, `main`에서 고정 자료의 해시를 확인한 뒤 명시적으로 지정한 소스를 가져온다. 실행자가 고정 전 이를 실행하지 않는 것이 절차의 선행 조건이다. 고정 자료·실행기·이 문서·수정 이력의 SHA256과 계약 해시는 `freeze_manifest.json`에 기록한다.

문법 기대값은 `eligible`·`excluded`·`unresolved`를 구분한다. 접두 구성의 어휘 적격성과 정확한 최종 품사, ETN의 명사적 숙주 기능과 사전 품사, 명사열의 수신 적격성과 합성·접미사 범위, XSN의 새 범주와 어휘 예외 신원은 별개다. 완전한 신뢰 근거로 알려진 불법 전이를 확인한 경우만 제외한다. 소유·태그 충돌, 미지원 구조와 미해결 표면 가족은 미해결이다. 기존 단순 용언의 제한된 어휘 권한을 보존하는 경우에는 표면 자모 증명까지 있다고 주장하지 않는다.

동일 원형 출현열의 분리·결합·부분 결합 포장을 비교한다. 허용된 표면 축약은 기존 `surface_proof`로 확인하고 공동 모음을 두 원형의 공동 유래로 보존하는지 검사한다. 생성자가 수용하지 않는 AnalysisToken 입력은 별도의 생성자 거부로 기록하며, 증명 실패 통계에 넣지 않는다. 보호·HARD·휴지는 음운 권한의 장벽이며 문법적 비적격성으로 바꾸지 않는다.

공개 소비자 검증은 실제 `G2P.convert_with_reading_conditions`를 호출한다. 비휴지 읽기 조건은 단어 사이 ASCII 공백에만 놓는다. 이 API를 단어 내부 증명 sidecar로 사용하지 않는다. 분석기는 그 실행에 고정한 AnalysisToken만 반환하도록 대체하며, 실제 공개 경로에서 호출됐는지 기록한다. 공개 결과의 원문·실행 좌표·규칙 기록·상태·적용성·소리 효과를 검사한다. 어휘 예외 신원과 새 XSN 명사 범주의 분리도 공개 경로에서 검증한다. 음운 적용성과 실제 소리 변화는 별도로 판정한다.

독립 실행 예시는 다음과 같다. 출력 경로는 이 폴더 아래로 제한한다.

```powershell
python -I output/g2p_progressive_round41_20261028/independent_refs/run_frozen.py --src output/g2p_progressive_round40_20261028/cleanroom/surface_proofs/candidate03/src --out output/g2p_progressive_round41_20261028/independent_refs/baseline_results.json
python -I output/g2p_progressive_round41_20261028/independent_refs/run_frozen.py --src src --out output/g2p_progressive_round41_20261028/independent_refs/candidate_results.json
```

`--include-kiwi`는 작은 고정 입력 집합의 실제 Kiwi 분석과 공개 변환을 관찰 자료로 추가한다. 그 결과에 정답 토큰을 맞추거나 독립 기대값을 수정하지 않는다. 분석기 버전과 포장 차이를 규범 오류로 단정하지 않는다. 실행 보고서에는 선택 소스·실제로 가져온 주요 모듈의 해시와 고정 manifest를 함께 보존한다.

원본 고정 자료는 실행 후 수정하지 않는다. 결함이 발견되면 원본 기대값과 결과를 보존하고 별도 버전·수정 이유·실행 전후 경계를 기록한다. 이 자료는 문법·소비자·공개 API의 제한된 독립 검증이며 전체 언어 규범 정확도나 비공개 회귀 집합 성능을 주장하지 않는다.
