# 통짜 원형에 필요한 최소 제17항 구조 사실

작성일: 2026-10-28. 기존 두 R42 계약은 그대로 유지한다. 함께 둔 `Opaque_Canonical_Lexical_Structure_Facts.json`은 공식 규범의 유한 표제에서 필요한 원형 구조만 추출한다. 완성 발음·활용 표면·새 평가 입력/정답은 포함하지 않는다.

| 사전 표제 / 원형 소유 | 구현상 호환 범주 | 원형 경계와 확인한 관계 | 일차 근거 |
|---|---|---|---|
| 붙이다 / 붙이 | VV | 붙 + 사동 이 | [맞춤법 제6항 해설 재현](https://korean.go.kr/front/onlineQna/onlineQnaView.do?mn_id=98&pageIndex=1&qna_seq=324560), [공식 상담 318232](https://www.korean.go.kr/front/onlineQna/onlineQnaView.do?mn_id=&pageIndex=1&qna_seq=318232), [상담이 연결한 사전 표제](https://opendict.korean.go.kr/dictionary/view?sense_no=31751&viewType=confirm) |
| 굳히다 / 굳히 | VV | 굳 + 사동 히 | 위 제6항 해설, [공식 상담 336018의 제17항 붙임 설명](https://www.korean.go.kr/front/onlineQna/onlineQnaView.do?mn_id=216&pageIndex=1&qna_seq=336018&searchCondition=&searchKeyword=) |
| 닫히다 / 닫히 | VV | 닫 + 피동 히 | 위 제6항 해설, [국립국어원 새국어생활의 파생 관계 설명](https://www.korean.go.kr/nkview/nklife/1992_3/3_19.html) |
| 묻히다 / 묻히 | VV | 묻 + 히. 덮어 넣는 묻다의 피동과 다른 물체에 들러붙는 묻다의 사동을 구별 | 위 제6항 해설의 실제 접미사 확인, [의미별 관계 316918](https://m.korean.go.kr/front/onlineQna/onlineQnaView.do?mn_id=216&pageIndex=1&qna_seq=316918), [사동 관계 확인 335457](https://www.korean.go.kr/front/onlineQna/onlineQnaView.do?mn_id=&pageIndex=1&qna_seq=335457) |
| 굳이 / 굳이 | MAG | 굳 어근 + 부사 파생 이 | [정확 구조를 확인한 323107](https://www.korean.go.kr/front/onlineQna/onlineQnaView.do?mn_id=&pageIndex=1&qna_seq=323107&searchCondition=&searchKeyword=), [기저 품사 등의 한계를 밝힌 319604](https://www.korean.go.kr/front/onlineQna/onlineQnaView.do?mn_id=73&pageIndex=1&qna_seq=319604) |

모든 경계는 표시한 원형 소유 문자열의 문자 offset 1이며, 앞 범위 `[0,1)`, 이/히 범위 `[1,2)`다. 이 위치는 결과 발음에서 역산하지 않았다. VV/MAG는 이 프로젝트에 전달할 호환 범주이며 공식 사전의 세부 분석 태그를 그대로 인용한 것이 아니다. 사전 표제와 공급된 정규 원형은 별도 필드로 보존한다.

굳이의 굳-은 **어근이라는 사실까지만** 확정한다. 그 기저의 정확 품사·의미·동형 표제 ID는 미확정이므로 굳히다의 굳다 신원을 가져와 채우지 않는다. 묻히다의 두 확인된 관계는 형식 히의 같은 원형 경계 권한을 공유하지만 사동·피동이라는 문법 신원을 서로 바꾸지 않는다. 의미가 없는 분석에는 확인된 관계의 대안을 남기며, 질문 의미의 묻다에서 새 사동·피동을 생성하지 않는다.

이 자료는 통짜 분석이 숨긴 **정확 어휘 소유의 내부 파생 사실**만 보충한다. 통짜 원형·합법적인 여러 토큰의 구성·승인 축약 표면 사이의 투영에는 기존 전체 문법·소유·표면 증명이 필요하다. 끝 철자나 품사만으로 접미사 신원을 추정하지 않는다. 표제의 합법적인 E 활용 가족에는 같은 사실을 재사용하며 활용 표면별 등록을 하지 않는다. 제36항의 이+아 금지 가드와 공급 원형 보존 조건도 유지한다.

정확 서술격 이는 일반 문법으로 처리하므로 명사별 행을 만들지 않았다. 기존 정책의 같이·곧이·명사 파생 사실을 되풀이하지 않았다. 붙이다의 사동 이 사실은 명사 성분/접미 경계로 등록된 붙이 문자열의 범위를 동사 전체로 넓히는 방법과 구별한다. 그 밖의 표제는 이번 공식 유한 근거 밖이므로 추가하지 않았다.

후속 조사에서는 공식 도메인 검색과 공식 본문만 사용했다. 분석기·G2P·시험·평가·실행 결과·기억 자료에 접근하지 않았다. 선행 조사 초기에 인접 함수 문맥과 비공식 검색 스니펫이 우연히 반환되었고 비공식 원문은 열거나 근거로 사용하지 않았다는 공개를 유지한다. 구현과 결과 검증을 완료했다는 보고가 아니다.
