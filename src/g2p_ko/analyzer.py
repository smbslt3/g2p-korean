"""공유 Kiwi 형태소 분석기를 필요할 때 한 번만 만든다."""

from __future__ import annotations

from threading import Lock

from .errors import BackendUnavailableError
from .model import AnalysisToken


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

    def analyze(self, text: str) -> tuple[AnalysisToken, ...]:
        tokenize = getattr(_get_kiwi(), "tokenize", None)
        if tokenize is None:
            raise BackendUnavailableError(
                "설치된 kiwipiepy에는 Kiwi.tokenize가 없습니다. "
                "지원되는 배포 버전을 설치하세요."
            )

        # 활용형을 분해한 형태소들은 원문 좌표가 서로 겹칠 수 있다. 겹치는
        # 구간의 태그를 합치고 표면형은 원문에서 복원해 비중첩 annotation을 만든다.
        결과: list[AnalysisToken] = []
        대기_태그: dict[int, list[str]] = {}
        for part in tokenize(text):
            시작 = int(part.start)
            길이 = int(part.len)
            태그 = str(part.tag)
            if 시작 < 0 or 시작 > len(text) or 길이 < 0:
                raise ValueError("Kiwi token offset이 입력 범위를 벗어났습니다.")
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
        return tuple(결과)

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
