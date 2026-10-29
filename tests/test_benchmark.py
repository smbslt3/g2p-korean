"""성능 측정 도구의 통계와 측정 단계를 검증한다."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import statistics
import sys
import tracemalloc
from types import SimpleNamespace

import pytest


_BENCHMARK_PATH = Path(__file__).resolve().parents[1] / "tools" / "benchmark.py"
_SPEC = importlib.util.spec_from_file_location("_g2p_ko_benchmark", _BENCHMARK_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
_BENCHMARK = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _BENCHMARK
_SPEC.loader.exec_module(_BENCHMARK)


@pytest.mark.parametrize("seconds", [(0.9, 0.1, 0.4), (0.8, 0.2, 0.4, 0.6)])
def test_summary_keeps_existing_statistics_and_adds_odd_even_median(seconds: tuple[float, ...]) -> None:
    samples = [
        {"seconds": value, "allocated_bytes": index + 1, "peak_bytes": (index + 1) * 10}
        for index, value in enumerate(seconds)
    ]

    summary = _BENCHMARK._summary(samples)

    assert summary["seconds"] == {
        "min": min(seconds),
        "mean": statistics.fmean(seconds),
        "median": statistics.median(seconds),
        "max": max(seconds),
    }


def test_measurement_separates_timing_and_memory_calls() -> None:
    tracing_states: list[bool] = []

    def call() -> object:
        tracing_states.append(tracemalloc.is_tracing())
        return object()

    sample = _BENCHMARK._measurement(call)

    assert tracing_states == [False, True]
    assert set(sample) == {"seconds", "allocated_bytes", "peak_bytes"}


def test_cold_import_uses_separate_subprocesses_for_time_and_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    phases: list[str] = []

    def run(command: list[str], **_: object) -> SimpleNamespace:
        phase = command[-1]
        phases.append(phase)
        stdout = '{"seconds": 0.125}' if phase == "seconds" else '{"peak_bytes": 4096}'
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(_BENCHMARK.subprocess, "run", run)

    result = _BENCHMARK._fresh_import(2)

    assert phases == ["seconds", "memory", "seconds", "memory"]
    assert result["status"] == "ok"
    assert result["iterations"] == 2
    assert result["seconds"]["median"] == 0.125
    assert result["memory"]["peak_bytes_max"] == 4096


def test_cold_is_delegated_and_warm_reuses_one_prepared_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances: list[object] = []
    isolated_calls: list[tuple[str, str, int | None]] = []

    class RecordingG2P:
        def __init__(self) -> None:
            self.calls: list[tuple[int, str, bool]] = []

        def __call__(self, text: str) -> str:
            self.calls.append((os.getpid(), text, tracemalloc.is_tracing()))
            return text

    def factory() -> RecordingG2P:
        instance = RecordingG2P()
        instances.append(instance)
        return instance

    def isolated(
        scenario_name: str,
        operation: str,
        *,
        size: int | None = None,
    ) -> object:
        isolated_calls.append((scenario_name, operation, size))
        index = len(isolated_calls)
        return _BENCHMARK._IsolatedMeasurement(
            {"seconds": 0.1, "allocated_bytes": 10, "peak_bytes": 20},
            (1_000 + index * 2, 1_001 + index * 2),
            (1, 1),
        )

    monkeypatch.setattr(_BENCHMARK, "_run_isolated_measurement", isolated)
    scenario = _BENCHMARK.Scenario("test", factory, "입력")
    result = _BENCHMARK._run_workload(scenario, "입력", repeats=3, size=2)

    assert result["cold"]["iterations"] == 3
    assert result["warm"]["iterations"] == 3
    assert isolated_calls == [("test", "workload", 2)] * 3
    assert len(instances) == 1
    assert instances[0].calls == [
        (os.getpid(), "입력", False),
        (os.getpid(), "입력", False),
        (os.getpid(), "입력", True),
        (os.getpid(), "입력", False),
        (os.getpid(), "입력", True),
        (os.getpid(), "입력", False),
        (os.getpid(), "입력", True),
    ]


def test_cold_phases_use_worker_processes_and_one_call_each() -> None:
    measurements = [
        _BENCHMARK._run_isolated_measurement(
            "tts_normalizer",
            "workload",
            size=1,
        )
        for _ in range(2)
    ]

    worker_pids = [pid for item in measurements for pid in item.worker_pids]

    assert all(item.call_counts == (1, 1) for item in measurements)
    assert all(
        set(item.sample) == {"seconds", "allocated_bytes", "peak_bytes"}
        for item in measurements
    )
    assert len(worker_pids) == 4
    assert os.getpid() not in worker_pids


def test_scenario_runs_use_worker_processes() -> None:
    executions = [
        _BENCHMARK._run_scenario_process("tts_normalizer", 1, (1,))
        for _ in range(2)
    ]

    worker_pids = [execution.worker_pid for execution in executions]

    assert len(worker_pids) == 2
    assert os.getpid() not in worker_pids
    assert all(
        execution.result["workloads"]["1"]["warm"]["iterations"] == 1
        for execution in executions
    )
    assert all(
        set(execution.result["workloads"]["1"]["cold"]["samples"][0])
        == {"seconds", "allocated_bytes", "peak_bytes"}
        for execution in executions
    )


def test_morphology_scenario_has_candidates_and_separate_activation() -> None:
    scenario = _BENCHMARK._morphology_scenario()
    corpus = _BENCHMARK._corpus(scenario.sample, 100)

    assert scenario.name == "kiwi_morphology"
    assert scenario.cold_workloads is False
    assert scenario.activation_text == "우리의 맑게"
    assert "맑게" in corpus
    assert "할 것을" in corpus


def test_default_scenario_avoids_the_morphology_analyzer(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    import g2p_ko.analyzer as analyzer_module
    from g2p_ko import G2P

    calls = 0

    class CountingKiwi:
        def tokenize(self, _text: str) -> tuple[object, ...]:
            nonlocal calls
            calls += 1
            return ()

    scenario = _BENCHMARK._default_scenario()
    text = _BENCHMARK._corpus(scenario.sample, 10_000)

    monkeypatch.setattr(analyzer_module, "_runtime_kiwi", CountingKiwi())
    G2P()(text)

    assert calls == 0


def test_tts_normalizer_scenario_uses_only_the_string_fast_path() -> None:
    scenario = _BENCHMARK._tts_normalizer_scenario()
    instance = scenario.factory()

    assert instance("3개에 ₩1,200") == "세 개에 천이백 원"


def test_scenario_can_skip_repeated_cold_workloads() -> None:
    instances: list[object] = []

    class RecordingG2P:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def __call__(self, text: str) -> str:
            self.calls.append(text)
            return text

    def factory() -> RecordingG2P:
        instance = RecordingG2P()
        instances.append(instance)
        return instance

    scenario = _BENCHMARK.Scenario(
        "test",
        factory,
        "입력",
        cold_workloads=False,
    )
    result = _BENCHMARK._run_workload(scenario, "입력", repeats=2, size=2)

    assert result["cold"]["status"] == "not_measured"
    assert result["warm"]["iterations"] == 2
    assert len(instances) == 1
    assert instances[0].calls == ["입력"] * 5


def test_activation_delegates_every_repeat_to_isolated_measurement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances: list[object] = []
    isolated_calls: list[tuple[str, str]] = []

    class RecordingG2P:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def __call__(self, text: str) -> str:
            self.calls.append(text)
            return text

    def factory() -> RecordingG2P:
        instance = RecordingG2P()
        instances.append(instance)
        return instance

    def isolated(scenario_name: str, operation: str) -> object:
        isolated_calls.append((scenario_name, operation))
        index = len(isolated_calls)
        return _BENCHMARK._IsolatedMeasurement(
            {"seconds": 0.1, "allocated_bytes": 10, "peak_bytes": 20},
            (2_000 + index * 2, 2_001 + index * 2),
            (1, 1),
        )

    monkeypatch.setattr(_BENCHMARK, "_run_isolated_measurement", isolated)

    scenario = _BENCHMARK.Scenario(
        "test",
        factory,
        "입력",
        activation_text="우리의 맑게",
    )
    result = _BENCHMARK._run_activation(scenario, repeats=2)

    assert result is not None
    assert result["iterations"] == 2
    assert result["input_code_points"] == len("우리의 맑게")
    assert isolated_calls == [("test", "activation")] * 2
    assert instances == []


def test_benchmark_schema_exposes_default_and_morphology_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario_calls: list[tuple[str, int, tuple[int, ...]]] = []

    monkeypatch.setattr(_BENCHMARK, "_SIZES", (10,))
    monkeypatch.setattr(_BENCHMARK, "_fresh_import", lambda _repeats: {"status": "ok"})

    def scenario_process(
        scenario_name: str,
        repeats: int,
        sizes: tuple[int, ...],
    ) -> object:
        scenario_calls.append((scenario_name, repeats, sizes))
        scenario_result = {
            "description": _BENCHMARK._SCENARIO_DESCRIPTIONS[scenario_name],
            "construction": {"status": "ok"},
            "workloads": {
                "10": {
                    "input_code_points": 10,
                    "cold": {"status": "ok"},
                    "warm": {"status": "ok"},
                }
            },
        }
        if scenario_name == "kiwi_morphology":
            scenario_result["activation"] = {
                "status": "ok",
                "input_code_points": len("우리의 맑게"),
            }
        return _BENCHMARK._ScenarioExecution(
            scenario_result,
            3_000 + len(scenario_calls),
        )

    monkeypatch.setattr(_BENCHMARK, "_run_scenario_process", scenario_process)

    result = _BENCHMARK.run_benchmark(repeats=2)

    assert result["schema_version"] == 3
    assert set(result["scenarios"]) == {"default", "kiwi_morphology", "tts_normalizer"}
    assert "activation" not in result["scenarios"]["default"]
    assert result["scenarios"]["kiwi_morphology"]["activation"]["status"] == "ok"
    assert result["metadata"]["semantics"]["warm"].startswith("격리된 시나리오 작업자")
    assert "서로 다른 새 Python 프로세스" in result["metadata"]["process_isolation"]["cold"]
    assert scenario_calls == [
        ("default", 2, (10,)),
        ("kiwi_morphology", 2, (10,)),
        ("tts_normalizer", 2, (10,)),
    ]


@pytest.mark.parametrize(
    ("cold_status", "expected_status", "expected_exit"),
    (("ok", "ok", 0), ("not_measured", "ok", 0), ("error", "error", 1)),
)
def test_main_reports_nested_measurement_status_and_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    cold_status: str,
    expected_status: str,
    expected_exit: int,
) -> None:
    result = {
        "baseline": {"cold_import": {"status": "ok"}},
        "scenarios": {
            "default": {"workloads": {"10": {"cold": {"status": cold_status}}}}
        },
    }
    monkeypatch.setattr(_BENCHMARK, "run_benchmark", lambda *, repeats: result)
    output = tmp_path / "benchmark.json"

    assert _BENCHMARK.main(["--repeats", "1", "--output", str(output)]) == expected_exit
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == expected_status
    assert capsys.readouterr().err == ""


def test_main_reports_output_write_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(_BENCHMARK, "run_benchmark", lambda *, repeats: {"baseline": {}})
    output = tmp_path / "missing" / "benchmark.json"

    assert _BENCHMARK.main(["--output", str(output)]) == 1
    failure = json.loads(capsys.readouterr().err)
    assert failure["status"] == "error"
    assert failure["error"] == "output_failed"
    assert not output.exists()


def test_main_preserves_worker_failure_in_json_and_returns_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(_BENCHMARK, "_SIZES", (1,))
    monkeypatch.setattr(_BENCHMARK, "_fresh_import", lambda _repeats: {"status": "ok"})

    def failed_worker(*_args: object) -> object:
        raise RuntimeError("테스트용 작업자 실패")

    monkeypatch.setattr(_BENCHMARK, "_run_scenario_process", failed_worker)
    output = tmp_path / "benchmark.json"

    assert _BENCHMARK.main(["--repeats", "1", "--output", str(output)]) == 1
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "error"
    assert all(
        scenario["construction"]["status"] == "error"
        for scenario in result["scenarios"].values()
    )
