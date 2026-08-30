# 숫자 읽기 모델 provenance와 생성 방법

이 문서는 패키지에 포함된
`src/g2p_ko/data/number_reading_model.json`의 기술적 provenance를 설명합니다.
원 데이터의 출처와 이용 조건은 [NOTICE](../NOTICE)가 우선합니다.

## 배포 artifact

- 구성 요소: `g2p_ko.normalizer.number_context.NumberReadingClassifier`
- 모델: 희소 자질 다항 로지스틱 회귀
- schema version: 2
- feature version: 3
- 클래스: `native`, `sino`, `digitwise`
- SHA-256: `ac89148158235c3e537e6c28d676e3a4e62aaa29c46bc470f012f54ec8fc4a24`

JSON에는 클래스별 bias·희소 자질 weight·적용 위치별 confidence threshold와 아래
학습 provenance가 들어 있습니다. 런타임은 이 파일을 읽어 순수 Python으로 추론하며
원 코퍼스나 학습 framework를 필요로 하지 않습니다.

## 입력 자료와 분할

AIHub 159 버전 1.1의 Training·Validation 라벨 JSON에서 다음 필드만 사용했습니다.

- `script.scriptITN`: 숫자가 포함된 문어형
- `script.scriptTN`: 검수된 발화형과 숫자 읽기 근거
- `script.patternTheme`, `script.scriptId`: 분할과 감사 metadata

`scriptITN` 완전 일치 중복을 제거하고 문장 text hash로 train 133,667문장, dev
7,473문장, 봉인 test 7,518문장으로 분할했습니다. 원본 오디오와 화자 metadata는
사용하지 않았습니다.

## 생성 절차

1. AIHub에서 각 사용자가 자신의 이용 권한으로 원본 라벨 JSON을 준비합니다.
2. 위 필드를 추출하고 `scriptITN` 완전 일치 중복을 제거합니다.
3. 문장 hash 분할을 고정하여 같은 문장이 여러 분할에 들어가지 않게 합니다.
4. 현재 노멀라이저를 실행하고 규칙만으로 읽기를 확정하지 못한 숫자 판별 지점만
   수집합니다.
5. 학습과 추론이 함께 사용하는
   `g2p_ko.normalizer.number_context.extract_features()`로 숫자 길이·값·단위와
   주변 Kiwi 형태소의 표면형·품사 자질을 만듭니다.
6. train의 63,501개 판별 지점으로 다항 로지스틱 회귀를 학습합니다.
7. dev의 2,513개로 클래스·위치별 적용 threshold를 보정하고, 별도 dev 1,095개로
   규칙 대비 회귀가 제한 안에 있는지 확인합니다.
8. 계수는 소수점 넷째 자리로 반올림하고, schema·feature version과 provenance를
   함께 JSON으로 내보냅니다.

배포 모델에 기록된 학습 설정은 epochs 6, learning rate 0.25, decay 0.4, seed
20260808, minimum feature count 4, class weight 0.5, pruning threshold 0.5입니다.
학습·dev feature artifact SHA-256도 JSON의 `provenance.feature_artifacts`에 기록되어
있습니다.

AIHub 다운로드·압축 해제·라벨 추출 코드는 원 데이터 경로와 계정 환경에 종속되며 이
저장소에 포함하지 않습니다. 원문, 발화형, label, split 파일과 학습 feature 행도
재배포하지 않습니다. 이 문서는 배포 artifact가 만들어진 절차를 감사할 수 있게 하는
기술 설명이며 원 데이터의 재배포 수단이 아닙니다.

---

# Number-reading model provenance and generation

This document describes the technical provenance of
`src/g2p_ko/data/number_reading_model.json`. [NOTICE](../NOTICE) remains the
authoritative source for the dataset origin and terms.

## Distributed artifact

- Component: `g2p_ko.normalizer.number_context.NumberReadingClassifier`
- Model: sparse-feature multinomial logistic regression
- Schema version: 2
- Feature version: 3
- Classes: `native`, `sino`, `digitwise`
- SHA-256: `ac89148158235c3e537e6c28d676e3a4e62aaa29c46bc470f012f54ec8fc4a24`

The JSON contains per-class biases, sparse feature weights, per-site confidence
thresholds, and training provenance. Runtime inference is pure Python and needs
neither the source corpus nor a training framework.

## Generation outline

The source labels are deduplicated by exact `scriptITN`, then split by a stable
text hash so one sentence cannot cross splits. Only numeric decision sites that
the deterministic normalizer cannot settle become examples. Training and runtime
both use `g2p_ko.normalizer.number_context.extract_features()` for number, unit,
and neighboring Kiwi morphology features.

The regression is fitted on 63,501 train sites. Thresholds are calibrated on
2,513 dev sites and checked on a separate 1,095-site dev subset. Coefficients are
rounded to four decimal places and exported with schema, feature, hyperparameter,
and feature-artifact hash metadata. Exact settings are stored under `provenance`
in the distributed JSON.

AIHub download, extraction, and label preparation depend on each user's account
and local dataset paths and are not included. Original texts, spoken forms,
labels, split files, and feature rows are not redistributed.
