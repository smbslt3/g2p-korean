"""기본 배포 경로가 network·경쟁 조건에 의존하지 않음을 검사한다."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import http.client
from pathlib import Path
import socket
import subprocess
import sys
import textwrap
import urllib.request

import pytest

from g2p_ko import G2P


_SAMPLE = "한국어 기본 경로는 여러 스레드에서도 같은 결과를 반환합니다."


@pytest.mark.parametrize("workers", [1, 4, 16])
def test_default_g2p_is_deterministic_under_concurrent_calls(workers: int) -> None:
    g2p = G2P()
    expected = g2p(_SAMPLE)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        actual = list(executor.map(lambda _: g2p(_SAMPLE), range(workers)))

    assert actual == [expected] * workers


@pytest.mark.parametrize("workers", [1, 4, 16])
def test_detailed_g2p_is_deterministic_under_concurrent_calls(workers: int) -> None:
    g2p = G2P()
    expected = g2p.convert(_SAMPLE)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        actual = list(executor.map(lambda _: g2p.convert(_SAMPLE), range(workers)))

    assert actual == [expected] * workers


def test_default_runtime_does_not_call_network_apis(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: object, **kwargs: object) -> object:
        raise AssertionError("기본 런타임은 네트워크 API를 호출하면 안 됩니다.")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    monkeypatch.setattr(http.client.HTTPConnection, "connect", blocked)
    monkeypatch.setattr(http.client.HTTPSConnection, "connect", blocked)

    assert G2P()(_SAMPLE)


def test_first_concurrent_calls_share_lazy_backends_and_isolate_results(tmp_path: Path) -> None:
    """새 프로세스의 동시 첫 호출에서도 초기화와 호출별 상태를 분리한다."""

    source_root = Path(__file__).resolve().parents[1] / "src"
    script = textwrap.dedent(
        """
        import sys
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier, Lock

        sys.path.insert(0, sys.argv[1])
        from g2p_ko import G2P
        from g2p_ko import analyzer

        assert analyzer._runtime_kiwi is None
        counts = {"kiwi": 0}
        count_lock = Lock()
        create_kiwi = analyzer._create_kiwi

        def counted_kiwi():
            with count_lock:
                counts["kiwi"] += 1
            return create_kiwi()

        analyzer._create_kiwi = counted_kiwi
        g2p = G2P()
        texts = [
            "3번 창구에서 우리의 맑게 읽습니다.",
            "영화를 3번 봤다. 앉고 넓게 할 것을 읽습니다.",
            "우편번호는 54130입니다. 국물과 같이 읽습니다.",
            "3번 창구로 가세요. A-1 😀",
        ] * 2
        barrier = Barrier(len(texts))

        def convert(text):
            barrier.wait(timeout=30)
            return g2p.convert(text).to_dict()

        with ThreadPoolExecutor(max_workers=len(texts)) as executor:
            actual = list(executor.map(convert, texts))
        expected = [g2p.convert(text).to_dict() for text in texts]
        assert actual == expected
        assert counts == {"kiwi": 1}, counts
        """
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-X", "utf8", "-c", script, str(source_root)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
