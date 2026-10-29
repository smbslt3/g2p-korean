"""공유 Kiwi 형태소 분석기를 필요할 때 한 번만 만든다."""

from __future__ import annotations

from threading import Lock
from operator import index as integer_index

from .errors import BackendUnavailableError
from .model import AnalysisToken
from .analysis_features import align_morphemes


_runtime_kiwi: object | None = None
_kiwi_lock = Lock()


def _create_kiwi() -> object:
    """첫 형태소 후보에서만 고정된 Kiwi 구현을 가져온다."""

    try:
        from kiwipiepy import Kiwi
    except ImportError as error:
        raise BackendUnavailableError(
            "kiwipiepy가 설치되어 있지 않습니다. 프로젝트 의존성을 설치하세요."
        ) from error
    return Kiwi()


def _get_kiwi() -> object:
    """프로세스 안에서 노멀라이저와 G2P가 같은 Kiwi를 재사용한다."""

    global _runtime_kiwi
    kiwi = _runtime_kiwi
    if kiwi is not None:
        return kiwi
    with _kiwi_lock:
        if _runtime_kiwi is None:
            _runtime_kiwi = _create_kiwi()
        return _runtime_kiwi


class KiwiAnalyzer:
    """공개 ``Kiwi.tokenize`` 결과를 원문 정렬 분석 token으로 옮긴다."""

    __slots__ = ()

    def analyze_components(self, text: str) -> tuple[AnalysisToken, ...]:
        """복합 용언과 사이시옷을 함께 분해해 한 번의 분석으로 경계를 제공한다."""

        return self.analyze(text, split_complex=True, saisiot=True)

    def analyze(self, text: str, *, split_complex: bool = False, saisiot: bool = False) -> tuple[AnalysisToken, ...]:
        tokenize = getattr(_get_kiwi(), "tokenize", None)
        if tokenize is None:
            raise BackendUnavailableError(
                "설치된 kiwipiepy에는 Kiwi.tokenize가 없습니다. "
                "지원되는 배포 버전을 설치하세요."
            )

        # 활용형을 분해한 형태소들은 원문 좌표가 서로 겹칠 수 있다. 겹치는
        # 구간의 태그를 합치고 표면형은 원문에서 복원해 비중첩 annotation을 만든다.
        결과: list[AnalysisToken] = []
        원시_형태소: list[tuple[str | None, str, int, int]] = []
        대기_태그: dict[int, list[str]] = {}
        if saisiot:
            parts = tokenize(text, split_complex=True, saisiot=True)
        else:
            parts = tokenize(text, split_complex=True) if split_complex else tokenize(text)
        for part in parts:
            # 문자열·실수·불리언을 좌표나 품사로 묵시 변환하면 잘못된 분석을 숨긴다.
            if isinstance(part.start, bool) or isinstance(part.len, bool):
                raise ValueError("Kiwi token offset에는 불리언을 사용할 수 없습니다.")
            시작 = integer_index(part.start)
            길이 = integer_index(part.len)
            태그 = part.tag
            if not isinstance(태그, str) or not 태그:
                raise ValueError("Kiwi token tag는 비어 있지 않은 문자열이어야 합니다.")
            if 시작 < 0 or 시작 > len(text) or 길이 < 0:
                raise ValueError("Kiwi token offset이 입력 범위를 벗어났습니다.")
            원시_형태소.append((getattr(part, "form", None), 태그, 시작, 길이))
            if 길이 == 0:
                if (
                    결과
                    and 결과[-1].normalized_start <= 시작 < 결과[-1].normalized_end
                ):
                    기존 = 결과[-1]
                    결과[-1] = AnalysisToken(
                        기존.form,
                        f"{기존.tag}+{태그}",
                        기존.normalized_start,
                        기존.normalized_end,
                    )
                else:
                    대기_태그.setdefault(시작, []).append(태그)
                continue
            끝 = 시작 + 길이
            if 끝 > len(text):
                raise ValueError("Kiwi token offset이 입력 범위를 벗어났습니다.")

            앞선_태그 = 대기_태그.pop(시작, [])
            if 앞선_태그:
                태그 = "+".join((*앞선_태그, 태그))
            if 결과 and 시작 < 결과[-1].normalized_end:
                기존 = 결과[-1]
                if 시작 < 기존.normalized_start:
                    raise ValueError("Kiwi token 순서가 원문 좌표와 맞지 않습니다.")
                병합_끝 = max(기존.normalized_end, 끝)
                결과[-1] = AnalysisToken(
                    text[기존.normalized_start:병합_끝],
                    f"{기존.tag}+{태그}",
                    기존.normalized_start,
                    병합_끝,
                )
            else:
                결과.append(AnalysisToken(text[시작:끝], 태그, 시작, 끝))
        # 표면형 병합 후에도 한 번 받은 분석의 기본형과 원래 품사를 보존한다.
        형태소들 = align_morphemes(
            원시_형태소, ((item.normalized_start, item.normalized_end) for item in 결과),
        )
        원시_범위들 = tuple(tuple((start, start + length)
            for form, _, start, length in 원시_형태소
            if form is not None and item.normalized_start <= start < item.normalized_end)
            for item in 결과)
        return tuple(
            AnalysisToken(item.form, item.tag, item.normalized_start, item.normalized_end, 형태소, 원시범위)
            for item, 형태소, 원시범위 in zip(결과, 형태소들, 원시_범위들)
        )

    def saisiot_positions(self, text: str) -> tuple[int, ...]:
        """Kiwi가 분해한 사이시옷이 들어 있는 음절의 offset을 반환한다."""

        tokenize = getattr(_get_kiwi(), "tokenize", None)
        if tokenize is None:
            raise BackendUnavailableError(
                "설치된 kiwipiepy에는 Kiwi.tokenize가 없습니다. "
                "지원되는 배포 버전을 설치하세요."
            )
        positions = {
            part.start + part.len - 1
            for part in tokenize(text, split_complex=True, saisiot=True)
            if part.tag == "Z_SIOT" and part.len > 0
        }
        if any(position < 0 or position >= len(text) for position in positions):
            raise ValueError("Kiwi 사이시옷 offset이 입력 범위를 벗어났습니다.")
        return tuple(sorted(positions))
