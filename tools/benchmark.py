"""CPU 전용 릴리스 후보의 재현 가능한 기본 성능 측정 도구다."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc
from typing import Any, Callable


_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
_SIZES = (100, 1_000, 10_000)
_KOREAN_SAMPLE = "국물이 좋아요. 아기가 웃어요. 공백은 그대로 둬요. "
_MORPHOLOGY_SAMPLE = "우리의 맑게 앉고 넓게 할 것을 정확히 읽습니다. "
_MORPHOLOGY_ACTIVATION_TEXT = "우리의 맑게"
_TTS_NORMALIZER_SAMPLE = "사과 3개는 ₩1,200이고 정확도는 12.50%입니다. "
_SCENARIO_NAMES = ("default", "kiwi_morphology", "tts_normalizer")
_SCENARIO_DESCRIPTIONS = {
    "default": "일반 한국어 정규화와 기본 발음 규칙 경로",
    "kiwi_morphology": "형태소 근거가 필요한 후보를 반복해 Kiwi.split 경로를 실행",
    "tts_normalizer": "독립형 TTS written-to-spoken 노멀라이저의 문자열 빠른 경로",
}


@dataclass(frozen=True, slots=True)
class Scenario:
    """동일한 측정 규칙으로 실행할 G2P 구성 하나다."""

    name: str
    factory: Callable[[], Any]
    sample: str
    description: str = ""
    cold_workloads: bool = True
    activation_text: str | None = None


@dataclass(frozen=True, slots=True)
class _IsolatedMeasurement:
    """공개 표본과 이를 만든 작업자 호출 계약을 함께 보관한다."""

    sample: dict[str, float | int]
    worker_pids: tuple[int, int]
    call_counts: tuple[int, int]


@dataclass(frozen=True, slots=True)
class _ScenarioExecution:
    """격리된 시나리오 결과와 작업자 PID를 부모에 전달한다."""

    result: dict[str, Any]
    worker_pid: int


class _WorkerFailure(RuntimeError):
    """격리 작업자가 정상적인 측정 결과를 반환하지 못했다."""


class _TTSNormalizerAdapter:
    """공통 workload 호출 규격에 문자열 전용 노멀라이저를 맞춘다."""

    def __init__(self, normalizer: Any) -> None:
        self._normalizer = normalizer

    def __call__(self, text: str) -> str:
        """상세 trace를 만들지 않는 대량 처리 경로만 측정한다."""

        return self._normalizer(text)


def _measurement(call: Callable[[], Any]) -> dict[str, float | int]:
    """시간과 Python 할당량을 서로 다른 호출에서 측정한다.

    ``tracemalloc``의 추적 비용이 경과 시간에 섞이지 않게 시간 호출을 먼저
    실행한다.
    """

    started = time.perf_counter()
    call()
    elapsed = time.perf_counter() - started

    tracemalloc.start()
    try:
        before_current, _ = tracemalloc.get_traced_memory()
        memory_value = call()
        after_current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    del memory_value
    return {
        "seconds": elapsed,
        "allocated_bytes": max(0, after_current - before_current),
        "peak_bytes": peak,
    }


def _summary(samples: list[dict[str, float | int]]) -> dict[str, Any]:
    """개별 반복 값을 남기면서 비교에 쓸 요약 통계를 만든다."""

    seconds = [float(item["seconds"]) for item in samples]
    peaks = [int(item["peak_bytes"]) for item in samples]
    allocations = [int(item["allocated_bytes"]) for item in samples]
    return {
        "status": "ok",
        "iterations": len(samples),
        "samples": samples,
        "seconds": {
            "min": min(seconds),
            "mean": statistics.fmean(seconds),
            "median": statistics.median(seconds),
            "max": max(seconds),
        },
        "memory": {
            "peak_bytes_max": max(peaks),
            "allocated_bytes_mean": statistics.fmean(allocations),
        },
    }


def _exception_result(error: Exception) -> dict[str, Any]:
    """측정 실패를 예외 형식과 함께 JSON에 기록한다."""

    name = type(error).__name__
    return {"status": "error", "exception": name, "reason": str(error)}


def _corpus(sample: str, size: int) -> str:
    """Python code point 수가 정확히 요청 크기인 결정적 입력을 만든다."""

    return (sample * ((size // len(sample)) + 1))[:size]


def _ensure_src_path() -> None:
    """소스 checkout에서도 작업자가 현재 패키지를 가져오게 한다."""

    source = str(_SRC)
    if source not in sys.path:
        sys.path.insert(0, source)


def _worker_command(*arguments: str) -> list[str]:
    """사용자 환경을 상속하지 않는 내부 작업자 명령을 만든다."""

    return [
        sys.executable,
        "-I",
        str(Path(__file__).resolve()),
        "--worker",
        *arguments,
    ]


def _run_worker(arguments: list[str]) -> dict[str, Any]:
    """내부 작업자 JSON을 읽고 프로세스·형식 실패를 한 예외로 정리한다."""

    completed = subprocess.run(
        _worker_command(*arguments),
        cwd=_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, ValueError) as error:
        reason = completed.stderr.strip() or completed.stdout.strip()
        raise _WorkerFailure(
            f"작업자 JSON을 읽을 수 없습니다: {reason or '출력이 없습니다.'}"
        ) from error
    if not isinstance(payload, dict):
        raise _WorkerFailure("작업자 결과의 최상위 값이 객체가 아닙니다.")
    if completed.returncode or payload.get("status") != "ok":
        exception = payload.get("exception", "BenchmarkWorkerFailed")
        reason = payload.get("reason") or completed.stderr.strip() or "이유가 없습니다."
        raise _WorkerFailure(f"{exception}: {reason}")
    return payload


def _fresh_import(repeats: int) -> dict[str, Any]:
    """별도 Python 프로세스에서 cold import 시간과 메모리를 분리 측정한다."""

    script = """
import importlib
import json
import sys
import time
import tracemalloc
sys.path.insert(0, sys.argv[1])
phase = sys.argv[2]
if phase == 'seconds':
    started = time.perf_counter()
    importlib.import_module('g2p_ko')
    print(json.dumps({'seconds': time.perf_counter() - started}))
elif phase == 'memory':
    tracemalloc.start()
    importlib.import_module('g2p_ko')
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(json.dumps({'peak_bytes': peak}))
else:
    raise ValueError(f'알 수 없는 측정 단계: {phase}')
"""
    samples: list[dict[str, float | int]] = []
    for _ in range(repeats):
        try:
            values: dict[str, float | int] = {"allocated_bytes": 0}
            for phase in ("seconds", "memory"):
                completed = subprocess.run(
                    [sys.executable, "-I", "-c", script, str(_SRC), phase],
                    cwd=_ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if completed.returncode:
                    return {
                        "status": "error",
                        "exception": "FreshImportFailed",
                        "reason": completed.stderr.strip() or completed.stdout.strip(),
                    }
                value = json.loads(completed.stdout)
                if phase == "seconds":
                    values["seconds"] = float(value["seconds"])
                else:
                    values["peak_bytes"] = int(value["peak_bytes"])
            samples.append(values)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            return _exception_result(error)
    return _summary(samples)


def _default_scenario() -> Scenario:
    _ensure_src_path()
    from g2p_ko import G2P

    return Scenario(
        "default",
        G2P,
        _KOREAN_SAMPLE,
        _SCENARIO_DESCRIPTIONS["default"],
    )


def _morphology_scenario() -> Scenario:
    _ensure_src_path()
    from g2p_ko import G2P

    return Scenario(
        "kiwi_morphology",
        G2P,
        _MORPHOLOGY_SAMPLE,
        _SCENARIO_DESCRIPTIONS["kiwi_morphology"],
        cold_workloads=False,
        activation_text=_MORPHOLOGY_ACTIVATION_TEXT,
    )


def _tts_normalizer_scenario() -> Scenario:
    _ensure_src_path()
    from g2p_ko import KoreanTTSNormalizer

    def factory() -> _TTSNormalizerAdapter:
        return _TTSNormalizerAdapter(KoreanTTSNormalizer())

    return Scenario(
        "tts_normalizer",
        factory,
        _TTS_NORMALIZER_SAMPLE,
        _SCENARIO_DESCRIPTIONS["tts_normalizer"],
    )


def _scenario_by_name(name: str) -> Scenario:
    """직렬화 가능한 이름을 실제 시나리오 구성으로 바꾼다."""

    factories: dict[str, Callable[[], Scenario]] = {
        "default": _default_scenario,
        "kiwi_morphology": _morphology_scenario,
        "tts_normalizer": _tts_normalizer_scenario,
    }
    try:
        factory = factories[name]
    except KeyError as error:
        raise ValueError(f"알 수 없는 benchmark 시나리오입니다: {name}") from error
    return factory()


def _cold_text(scenario: Scenario, operation: str, size: int | None) -> str:
    """격리 작업자가 측정할 입력을 직렬화된 인자에서 복원한다."""

    if operation == "activation":
        if scenario.activation_text is None:
            raise ValueError(f"{scenario.name} 시나리오에는 activation 입력이 없습니다.")
        return scenario.activation_text
    if operation == "workload":
        if size is None or size <= 0:
            raise ValueError("workload 크기는 양의 정수여야 합니다.")
        return _corpus(scenario.sample, size)
    raise ValueError(f"알 수 없는 cold 측정 종류입니다: {operation}")


def _cold_phase_payload(
    scenario_name: str,
    operation: str,
    phase: str,
    size: int | None,
) -> dict[str, Any]:
    """새 프로세스에서 cold 호출을 정확히 한 번 실행한다."""

    scenario = _scenario_by_name(scenario_name)
    text = _cold_text(scenario, operation, size)
    call_count = 0

    def call() -> Any:
        nonlocal call_count
        call_count += 1
        return scenario.factory()(text)

    if phase == "seconds":
        started = time.perf_counter()
        call()
        sample: dict[str, float | int] = {
            "seconds": time.perf_counter() - started,
        }
    elif phase == "memory":
        tracemalloc.start()
        try:
            before_current, _ = tracemalloc.get_traced_memory()
            memory_value = call()
            after_current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        del memory_value
        sample = {
            "allocated_bytes": max(0, after_current - before_current),
            "peak_bytes": peak,
        }
    else:
        raise ValueError(f"알 수 없는 cold 측정 단계입니다: {phase}")
    return {
        "status": "ok",
        "pid": os.getpid(),
        "call_count": call_count,
        "sample": sample,
    }


def _run_isolated_measurement(
    scenario_name: str,
    operation: str,
    *,
    size: int | None = None,
) -> _IsolatedMeasurement:
    """cold 시간·메모리를 각각 새 작업자의 단일 호출로 측정한다."""

    sample: dict[str, float | int] = {}
    worker_pids: list[int] = []
    call_counts: list[int] = []
    for phase in ("seconds", "memory"):
        arguments = [
            "cold",
            "--scenario",
            scenario_name,
            "--operation",
            operation,
            "--phase",
            phase,
        ]
        if size is not None:
            arguments.extend(("--size", str(size)))
        payload = _run_worker(arguments)
        worker_pid = payload.get("pid")
        call_count = payload.get("call_count")
        phase_sample = payload.get("sample")
        if (
            not isinstance(worker_pid, int)
            or isinstance(worker_pid, bool)
            or worker_pid == os.getpid()
        ):
            raise _WorkerFailure("cold 측정이 새 작업자 프로세스에서 실행되지 않았습니다.")
        if call_count != 1:
            raise _WorkerFailure("cold 작업자는 측정 단계마다 변환을 한 번 호출해야 합니다.")
        if not isinstance(phase_sample, dict):
            raise _WorkerFailure("cold 작업자의 표본이 객체가 아닙니다.")
        try:
            if phase == "seconds":
                sample["seconds"] = float(phase_sample["seconds"])
            else:
                sample["allocated_bytes"] = int(phase_sample["allocated_bytes"])
                sample["peak_bytes"] = int(phase_sample["peak_bytes"])
        except (KeyError, TypeError, ValueError) as error:
            raise _WorkerFailure("cold 작업자의 표본 필드가 올바르지 않습니다.") from error
        worker_pids.append(worker_pid)
        call_counts.append(call_count)
    return _IsolatedMeasurement(
        sample,
        (worker_pids[0], worker_pids[1]),
        (call_counts[0], call_counts[1]),
    )


def _run_activation(scenario: Scenario, repeats: int) -> dict[str, Any] | None:
    """Kiwi 지연 초기화를 반복마다 완전히 새 프로세스에서 측정한다."""

    text = scenario.activation_text
    if text is None:
        return None
    samples: list[dict[str, float | int]] = []
    for _ in range(repeats):
        try:
            isolated = _run_isolated_measurement(scenario.name, "activation")
        except Exception as error:
            return _exception_result(error)
        samples.append(isolated.sample)
    result = _summary(samples)
    result["input_code_points"] = len(text)
    return result


def _run_warm_workload(
    scenario: Scenario,
    text: str,
    repeats: int,
) -> dict[str, Any]:
    """한 프로세스의 한 인스턴스를 준비한 뒤 모든 warm 표본을 얻는다."""

    try:
        instance = scenario.factory()
    except Exception as error:
        return _exception_result(error)
    try:
        # 준비 호출은 측정하지 않으며 이후에도 같은 인스턴스만 사용한다.
        instance(text)
    except Exception as error:
        warm_error = _exception_result(error)
        warm_error["phase"] = "warmup"
        return warm_error

    warm_samples: list[dict[str, float | int]] = []
    for _ in range(repeats):
        try:
            sample = _measurement(lambda: instance(text))
        except Exception as error:
            return _exception_result(error)
        warm_samples.append(sample)
    return _summary(warm_samples)


def _run_workload(
    scenario: Scenario,
    text: str,
    repeats: int,
    *,
    size: int,
) -> dict[str, Any]:
    """격리된 cold와 준비된 동일 프로세스의 warm 성능을 측정한다."""

    if scenario.cold_workloads:
        cold_samples: list[dict[str, float | int]] = []
        for _ in range(repeats):
            try:
                isolated = _run_isolated_measurement(
                    scenario.name,
                    "workload",
                    size=size,
                )
            except Exception as error:  # 공개 API 구성 실패도 JSON으로 남긴다.
                return {"cold": _exception_result(error), "warm": {"status": "not_run"}}
            cold_samples.append(isolated.sample)
        cold_result: dict[str, Any] = _summary(cold_samples)
    else:
        cold_result = {
            "status": "not_measured",
            "reason": "Kiwi 지연 초기화는 scenario activation에서 분리 측정합니다.",
        }
    return {
        "cold": cold_result,
        "warm": _run_warm_workload(scenario, text, repeats),
    }


def _run_scenario_measurements(
    scenario_name: str,
    repeats: int,
    sizes: tuple[int, ...],
) -> dict[str, Any]:
    """한 시나리오의 construction과 warm을 전용 프로세스에서 측정한다."""

    scenario = _scenario_by_name(scenario_name)
    try:
        construction = _measurement(scenario.factory)
        construction_result: dict[str, Any] = _summary([construction])
    except Exception as error:
        construction_result = _exception_result(error)
    scenario_result: dict[str, Any] = {
        "description": scenario.description,
        "construction": construction_result,
        "workloads": {},
    }
    activation = _run_activation(scenario, repeats)
    if activation is not None:
        scenario_result["activation"] = activation
    for size in sizes:
        text = _corpus(scenario.sample, size)
        workload_result = {"input_code_points": len(text)}
        workload_result.update(
            _run_workload(scenario, text, repeats, size=size)
        )
        scenario_result["workloads"][str(size)] = workload_result
    return scenario_result


def _run_scenario_process(
    scenario_name: str,
    repeats: int,
    sizes: tuple[int, ...],
) -> _ScenarioExecution:
    """시나리오 전체를 부모와 다른 새 Python 프로세스에서 실행한다."""

    payload = _run_worker(
        [
            "scenario",
            "--scenario",
            scenario_name,
            "--repeats",
            str(repeats),
            "--sizes",
            ",".join(str(size) for size in sizes),
        ]
    )
    worker_pid = payload.get("pid")
    scenario_result = payload.get("result")
    if (
        not isinstance(worker_pid, int)
        or isinstance(worker_pid, bool)
        or worker_pid == os.getpid()
    ):
        raise _WorkerFailure("시나리오가 새 작업자 프로세스에서 실행되지 않았습니다.")
    if not isinstance(scenario_result, dict):
        raise _WorkerFailure("시나리오 작업자의 결과가 객체가 아닙니다.")
    return _ScenarioExecution(scenario_result, worker_pid)


def run_benchmark(*, repeats: int) -> dict[str, Any]:
    """CLI와 테스트가 공용으로 쓸 전체 benchmark 결과를 만든다."""

    if repeats <= 0:
        raise ValueError("repeats는 양의 정수여야 합니다.")
    result: dict[str, Any] = {
        "schema_version": 3,
        "metadata": {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "python": sys.version,
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "logical_cpu_count": os.cpu_count(),
            "code_point_sizes": list(_SIZES),
            "repeats": repeats,
            "clock": "time.perf_counter",
            "memory": "tracemalloc Python allocation peak; native RSS는 포함하지 않음",
            "measurement_phases": {
                "seconds": "tracemalloc을 끈 호출에서 측정합니다.",
                "memory": "tracemalloc을 켠 별도 호출에서 측정하며 해당 호출의 시간은 seconds에 포함하지 않습니다.",
            },
            "warmup": "warm workload는 같은 입력으로 1회 비측정 priming 뒤에 측정합니다.",
            "process_isolation": {
                "scenario": "각 시나리오는 부모 및 다른 시나리오와 다른 새 Python 프로세스에서 실행합니다.",
                "cold": "각 반복의 시간·메모리 호출을 서로 다른 새 Python 프로세스에서 한 번씩 실행합니다.",
                "warm": "시나리오 작업자에서 준비한 같은 인스턴스와 프로세스를 재사용합니다.",
            },
            "cold_scope": "Python 프로세스 시작과 g2p_ko import는 workload 시간 밖이며 운영체제 파일 캐시는 공유합니다.",
            "semantics": {
                "construction": "격리된 시나리오 작업자에서 처리 인스턴스를 생성합니다. G2P의 지연 자산은 아직 만들지 않습니다.",
                "activation": "반복·측정 단계마다 새 프로세스에서 새 G2P의 첫 형태소 처리와 Kiwi 생성을 측정합니다.",
                "cold": "반복·측정 단계마다 새 프로세스에서 새 처리 인스턴스 생성과 변환을 함께 측정하며 Kiwi 시나리오에서는 activation으로 대체합니다.",
                "warm": "격리된 시나리오 작업자에서 같은 처리 인스턴스를 준비 호출한 뒤 모든 표본에 재사용합니다.",
            },
        },
        "baseline": {"cold_import": _fresh_import(repeats)},
        "scenarios": {},
    }

    for scenario_name in _SCENARIO_NAMES:
        try:
            execution = _run_scenario_process(scenario_name, repeats, _SIZES)
            scenario_result = execution.result
        except Exception as error:
            scenario_result = {
                "description": _SCENARIO_DESCRIPTIONS[scenario_name],
                "construction": _exception_result(error),
                "workloads": {},
            }
        result["scenarios"][scenario_name] = scenario_result
    return result


def _parse_sizes(value: str) -> tuple[int, ...]:
    """내부 시나리오 작업자의 쉼표 구분 크기를 검증한다."""

    try:
        sizes = tuple(int(item) for item in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("sizes는 쉼표로 구분한 정수여야 합니다.") from error
    if not sizes or any(size <= 0 for size in sizes):
        raise argparse.ArgumentTypeError("sizes의 모든 값은 양의 정수여야 합니다.")
    return sizes


def _worker_payload(args: argparse.Namespace) -> dict[str, Any]:
    """명령행 인자를 격리 작업자의 단일 JSON 응답으로 바꾼다."""

    if args.scenario is None:
        raise ValueError("내부 작업자에는 scenario가 필요합니다.")
    _ensure_src_path()
    if args.worker == "scenario":
        if args.repeats <= 0:
            raise ValueError("repeats는 양의 정수여야 합니다.")
        return {
            "status": "ok",
            "pid": os.getpid(),
            "result": _run_scenario_measurements(
                args.scenario,
                args.repeats,
                args.sizes,
            ),
        }
    if args.worker == "cold":
        if args.operation is None or args.phase is None:
            raise ValueError("cold 작업자에는 operation과 phase가 필요합니다.")
        return _cold_phase_payload(
            args.scenario,
            args.operation,
            args.phase,
            args.size,
        )
    raise ValueError(f"알 수 없는 내부 작업자입니다: {args.worker}")


def main(argv: list[str] | None = None) -> int:
    """명시한 옵션만 사용해 network 없는 benchmark JSON을 출력한다."""

    parser = argparse.ArgumentParser(description="g2p-ko CPU benchmark를 JSON으로 출력합니다.")
    parser.add_argument("--repeats", type=int, default=5, help="cold/warm 반복 횟수 (기본값: 5)")
    parser.add_argument("--output", type=Path, help="stdout 대신 결과를 쓸 JSON 파일")
    parser.add_argument(
        "--worker",
        choices=("scenario", "cold"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--scenario", choices=_SCENARIO_NAMES, help=argparse.SUPPRESS)
    parser.add_argument(
        "--operation",
        choices=("activation", "workload"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--phase",
        choices=("seconds", "memory"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--size", type=int, help=argparse.SUPPRESS)
    parser.add_argument(
        "--sizes",
        type=_parse_sizes,
        default=_SIZES,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)
    if args.worker is not None:
        try:
            result = _worker_payload(args)
        except Exception as error:
            result = _exception_result(error)
            result["pid"] = os.getpid()
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 0 if result["status"] == "ok" else 1
    try:
        result = run_benchmark(repeats=args.repeats)
    except ValueError as error:
        parser.error(str(error))
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(payload, end="")
    else:
        args.output.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
