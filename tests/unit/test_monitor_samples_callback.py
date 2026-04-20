import asyncio
from unittest.mock import MagicMock, patch

import pytest

from headroom.core.config import EndpointConfig
from headroom.repository.monitor_samples import MonitorSampleRecord
from headroom.services.capacity_gate import InMemoryCapacityGate
from headroom.services.monitor import MockMonitor, VertexMonitor

EP = EndpointConfig(name="ep-a", model="model-a", region="us-central1", capacity_tps=10_000)


class SampleCollector:
    def __init__(self, fail: bool = False) -> None:
        self.records: list[MonitorSampleRecord] = []
        self._fail = fail

    async def __call__(self, record: MonitorSampleRecord) -> None:
        if self._fail:
            raise RuntimeError("boom")
        self.records.append(record)


async def _spin(monitor, seconds: float) -> None:
    task = asyncio.create_task(monitor.refresh_loop())
    await asyncio.sleep(seconds)
    monitor.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def test_mock_monitor_emits_sample_per_tick_per_endpoint() -> None:
    gates = {
        "ep-a": InMemoryCapacityGate(total_capacity_tps=10_000),
        "ep-b": InMemoryCapacityGate(total_capacity_tps=5_000),
    }
    collector = SampleCollector()
    monitor = MockMonitor(
        gates=gates,
        scripts={"ep-a": [(0.0, 2_000)], "ep-b": [(0.0, 1_000)]},
        tick_interval=0.02,
        capacities={"ep-a": 10_000, "ep-b": 5_000},
        on_sample=collector,
    )

    await _spin(monitor, 0.08)

    endpoints = {r.endpoint for r in collector.records}
    assert endpoints == {"ep-a", "ep-b"}
    ep_a = next(r for r in collector.records if r.endpoint == "ep-a")
    assert ep_a.usage_tps == 2_000
    assert ep_a.total_tps == 10_000
    assert ep_a.status == "ok"
    assert ep_a.consecutive_failures == 0


async def test_callback_errors_do_not_kill_loop() -> None:
    gates = {"ep-a": InMemoryCapacityGate(total_capacity_tps=10_000)}
    failing = SampleCollector(fail=True)
    monitor = MockMonitor(
        gates=gates,
        scripts={"ep-a": [(0.0, 100)]},
        tick_interval=0.02,
        on_sample=failing,
    )

    await _spin(monitor, 0.1)
    # loop should have ticked multiple times without raising
    assert gates["ep-a"].current_usage_tps == 100


async def test_vertex_monitor_emits_ok_sample_on_success() -> None:
    gate = InMemoryCapacityGate(total_capacity_tps=10_000)
    collector = SampleCollector()

    with patch("headroom.services.monitor.monitoring_v3.MetricServiceClient") as mock_client:
        instance = MagicMock()
        point = MagicMock()
        point.value.double_value = 1_234.0
        series = MagicMock()
        series.points = [point]
        instance.list_time_series.side_effect = lambda *a, **k: iter([series])
        mock_client.return_value = instance

        monitor = VertexMonitor(
            gates={"ep-a": gate},
            project="proj",
            endpoint_configs=[EP],
            credentials=MagicMock(),
            interval=0,
            failure_threshold=5,
            on_sample=collector,
        )
        await _spin(monitor, 0.05)

    assert any(r.endpoint == "ep-a" and r.status == "ok" for r in collector.records)
    record = collector.records[0]
    assert record.usage_tps == 1_234
    assert record.total_tps == 10_000
    assert record.consecutive_failures == 0


async def test_vertex_monitor_emits_stale_status_after_failure_threshold() -> None:
    gate = InMemoryCapacityGate(total_capacity_tps=10_000)
    collector = SampleCollector()

    with patch("headroom.services.monitor.monitoring_v3.MetricServiceClient") as mock_client:
        instance = MagicMock()
        instance.list_time_series.side_effect = RuntimeError("gcp down")
        mock_client.return_value = instance

        monitor = VertexMonitor(
            gates={"ep-a": gate},
            project="proj",
            endpoint_configs=[EP],
            credentials=MagicMock(),
            interval=0,
            failure_threshold=2,
            on_sample=collector,
        )
        await _spin(monitor, 0.1)

    # later records (after threshold hit) should carry status=stale
    assert any(r.status == "stale" for r in collector.records)
    stale = next(r for r in collector.records if r.status == "stale")
    assert stale.consecutive_failures >= 2
