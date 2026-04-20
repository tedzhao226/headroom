import asyncio
from unittest.mock import MagicMock, patch

import pytest

from headroom.core.config import EndpointConfig
from headroom.services.capacity_gate import InMemoryCapacityGate
from headroom.services.monitor import MockMonitor, VertexMonitor

EP_A = EndpointConfig(name="ep-a", model="model-a", region="us-central1", capacity_tps=10_000)
EP_B = EndpointConfig(name="ep-b", model="model-b", region="europe-west1", capacity_tps=5_000)


def make_mock_series(value: float) -> MagicMock:
    point = MagicMock()
    point.value.double_value = value
    series = MagicMock()
    series.points = [point]
    return series


def make_single_gate_and_config():
    gate = InMemoryCapacityGate(total_capacity_tps=10_000)
    return {"ep-a": gate}, [EP_A]


async def test_mock_monitor_single_point_sets_constant_usage() -> None:
    gate = InMemoryCapacityGate(total_capacity_tps=10_000)
    monitor = MockMonitor(
        gates={"ep-a": gate},
        scripts={"ep-a": [(0.0, 3_000)]},
        tick_interval=0.01,
    )

    task = asyncio.create_task(monitor.refresh_loop())
    await asyncio.sleep(0.05)
    monitor.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert gate._current_usage_tps == 3_000


async def test_mock_monitor_multiple_points_interpolates() -> None:
    gate = InMemoryCapacityGate(total_capacity_tps=10_000)
    monitor = MockMonitor(
        gates={"ep-a": gate},
        scripts={"ep-a": [(0.0, 0), (1.0, 1_000)]},
        tick_interval=0.01,
    )

    task = asyncio.create_task(monitor.refresh_loop())
    await asyncio.sleep(0.05)
    monitor.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert 0 <= gate._current_usage_tps < 500


async def test_mock_monitor_stop_terminates_loop() -> None:
    gate = InMemoryCapacityGate(total_capacity_tps=10_000)
    monitor = MockMonitor(
        gates={"ep-a": gate},
        scripts={"ep-a": [(0.0, 5_000)]},
        tick_interval=0.01,
    )

    task = asyncio.create_task(monitor.refresh_loop())
    await asyncio.sleep(0.03)
    monitor.stop()

    try:
        await asyncio.wait_for(task, timeout=0.1)
    except asyncio.TimeoutError:
        task.cancel()
        pytest.fail("refresh_loop did not stop after stop() was called")
    except asyncio.CancelledError:
        pass

    assert monitor._stopped is True


async def test_mock_monitor_holds_final_value_after_last_script_point() -> None:
    gate = InMemoryCapacityGate(total_capacity_tps=10_000)
    monitor = MockMonitor(
        gates={"ep-a": gate},
        scripts={"ep-a": [(0.0, 2_000), (0.02, 8_000)]},
        tick_interval=0.01,
    )

    task = asyncio.create_task(monitor.refresh_loop())
    await asyncio.sleep(0.1)
    monitor.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert gate._current_usage_tps == 8_000


async def test_mock_monitor_two_endpoints_independent_scripts() -> None:
    gate_a = InMemoryCapacityGate(total_capacity_tps=10_000)
    gate_b = InMemoryCapacityGate(total_capacity_tps=5_000)
    monitor = MockMonitor(
        gates={"ep-a": gate_a, "ep-b": gate_b},
        scripts={
            "ep-a": [(0.0, 1_000)],
            "ep-b": [(0.0, 4_000)],
        },
        tick_interval=0.01,
    )

    task = asyncio.create_task(monitor.refresh_loop())
    await asyncio.sleep(0.05)
    monitor.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert gate_a._current_usage_tps == 1_000
    assert gate_b._current_usage_tps == 4_000


@patch("headroom.services.monitor.monitoring_v3.MetricServiceClient")
async def test_vertex_monitor_successful_refresh_calls_update_usage(mock_client_cls) -> None:
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.list_time_series.return_value = [make_mock_series(5_000.0)]

    gates, configs = make_single_gate_and_config()
    creds = MagicMock()
    monitor = VertexMonitor(
        gates=gates, project="test", endpoint_configs=configs, credentials=creds, interval=1,
    )

    task = asyncio.create_task(monitor.refresh_loop())
    await asyncio.sleep(0.05)
    monitor.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert gates["ep-a"]._current_usage_tps == 5_000


@patch("headroom.services.monitor.monitoring_v3.MetricServiceClient")
async def test_vertex_monitor_api_failure_keeps_last_known_value(mock_client_cls, capfd) -> None:
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    call_count = 0

    def side_effect(request, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [make_mock_series(4_000.0)]
        raise RuntimeError("GCP unavailable")

    mock_client.list_time_series.side_effect = side_effect

    gates, configs = make_single_gate_and_config()
    creds = MagicMock()
    monitor = VertexMonitor(
        gates=gates, project="test", endpoint_configs=configs, credentials=creds, interval=1,
    )

    task = asyncio.create_task(monitor.refresh_loop())
    await asyncio.sleep(1.05)
    monitor.stop()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.TimeoutError:
        task.cancel()
        pytest.fail("refresh_loop did not stop after stop() was called")
    except asyncio.CancelledError:
        pass

    assert gates["ep-a"]._current_usage_tps == 4_000
    assert "monitor_query_failed" in capfd.readouterr().out


@patch("headroom.services.monitor.monitoring_v3.MetricServiceClient")
async def test_vertex_monitor_consecutive_failures_enter_conservative_mode(mock_client_cls, capfd) -> None:
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.list_time_series.side_effect = RuntimeError("GCP unavailable")

    gates, configs = make_single_gate_and_config()
    creds = MagicMock()
    monitor = VertexMonitor(
        gates=gates, project="test", endpoint_configs=configs, credentials=creds,
        interval=1, failure_threshold=2,
    )
    task = asyncio.create_task(monitor.refresh_loop())
    await asyncio.sleep(0.05)
    assert gates["ep-a"]._current_usage_tps == 0

    await asyncio.sleep(1.05)
    monitor.stop()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.TimeoutError:
        task.cancel()
        pytest.fail("refresh_loop did not stop after stop() was called")
    except asyncio.CancelledError:
        pass

    assert gates["ep-a"]._current_usage_tps == 9_000
    assert "monitor_conservative_mode" in capfd.readouterr().out


@patch("headroom.services.monitor.monitoring_v3.MetricServiceClient")
async def test_vertex_monitor_stop_terminates_loop(mock_client_cls) -> None:
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.list_time_series.return_value = []

    gates, configs = make_single_gate_and_config()
    creds = MagicMock()
    monitor = VertexMonitor(
        gates=gates, project="test", endpoint_configs=configs, credentials=creds, interval=1,
    )

    task = asyncio.create_task(monitor.refresh_loop())
    await asyncio.sleep(0.05)
    monitor.stop()

    try:
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.TimeoutError:
        task.cancel()
        pytest.fail("refresh_loop did not stop after stop() was called")
    except asyncio.CancelledError:
        pass


@patch("headroom.services.monitor.monitoring_v3.MetricServiceClient")
async def test_vertex_monitor_creates_client_once(mock_client_cls) -> None:
    creds = MagicMock()
    gates, configs = make_single_gate_and_config()
    VertexMonitor(
        gates=gates, project="test", endpoint_configs=configs, credentials=creds,
    )
    assert mock_client_cls.call_count == 1


@patch("headroom.services.monitor.monitoring_v3.MetricServiceClient")
async def test_vertex_monitor_two_endpoints_isolated_failure(mock_client_cls) -> None:
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    gate_a = InMemoryCapacityGate(total_capacity_tps=10_000)
    gate_b = InMemoryCapacityGate(total_capacity_tps=5_000)
    gates = {"ep-a": gate_a, "ep-b": gate_b}
    configs = [EP_A, EP_B]
    creds = MagicMock()

    def side_effect(request, **kwargs):
        if "model-a" in request["filter"]:
            return [make_mock_series(3_000.0)]
        raise RuntimeError("GCP unavailable for ep-b")

    mock_client.list_time_series.side_effect = side_effect

    monitor = VertexMonitor(
        gates=gates, project="test", endpoint_configs=configs, credentials=creds, interval=1,
    )

    task = asyncio.create_task(monitor.refresh_loop())
    await asyncio.sleep(0.05)
    monitor.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert gate_a._current_usage_tps == 3_000
    assert gate_b._current_usage_tps == 0
    assert monitor._endpoints["ep-a"].consecutive_failures == 0
    assert monitor._endpoints["ep-b"].consecutive_failures == 1
