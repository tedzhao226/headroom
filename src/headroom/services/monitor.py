import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol

import structlog
from google.cloud import monitoring_v3

from headroom.core.config import EndpointConfig
from headroom.repository.monitor_samples import MonitorSampleRecord
from headroom.services.capacity_gate import InMemoryCapacityGate

logger = structlog.get_logger()

OnSample = Callable[[MonitorSampleRecord], Awaitable[None]]


class Monitor(Protocol):
    async def refresh_loop(self) -> None: ...
    def stop(self) -> None: ...


@dataclass
class _EndpointState:
    gate: InMemoryCapacityGate
    model: str
    region: str
    capacity_tps: int
    last_known_usage: int = 0
    consecutive_failures: int = 0


class VertexMonitor:
    def __init__(
        self,
        gates: dict[str, InMemoryCapacityGate],
        project: str,
        endpoint_configs: list[EndpointConfig],
        credentials,
        interval: int = 60,
        failure_threshold: int = 5,
        on_sample: OnSample | None = None,
    ) -> None:
        self._project = project
        self._credentials = credentials
        self._interval = interval
        self._failure_threshold = failure_threshold
        self._on_sample = on_sample
        self._stopped = False
        self._client = monitoring_v3.MetricServiceClient(credentials=credentials)

        self._endpoints: dict[str, _EndpointState] = {}
        for ep in endpoint_configs:
            self._endpoints[ep.name] = _EndpointState(
                gate=gates[ep.name],
                model=ep.model,
                region=ep.region,
                capacity_tps=ep.capacity_tps,
            )

    def _query_usage(self, model: str, region: str) -> int:
        now = time.time()
        interval = monitoring_v3.TimeInterval(
            {
                "end_time": {"seconds": int(now)},
                "start_time": {"seconds": int(now) - self._interval * 2},
            }
        )
        aggregation = monitoring_v3.Aggregation(
            {
                "alignment_period": {"seconds": 60},
                "per_series_aligner": monitoring_v3.Aggregation.Aligner.ALIGN_RATE,
            }
        )
        metric_filter = (
            'metric.type="aiplatform.googleapis.com/publisher/online_serving/token_count"'
            f' AND resource.labels.model_user_id="{model}"'
            f' AND resource.labels.location="{region}"'
            ' AND metric.labels.request_type="dedicated"'
        )
        results = self._client.list_time_series(
            request={
                "name": f"projects/{self._project}",
                "filter": metric_filter,
                "interval": interval,
                "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
                "aggregation": aggregation,
            }
        )
        total = 0.0
        for series in results:
            if series.points:
                total += series.points[-1].value.double_value
        return int(total)

    async def refresh_loop(self) -> None:
        while not self._stopped:
            for name, state in self._endpoints.items():
                try:
                    usage = await asyncio.to_thread(
                        self._query_usage, state.model, state.region
                    )
                    state.last_known_usage = usage
                    state.consecutive_failures = 0
                    await state.gate.update_usage(usage)
                except Exception as exc:
                    state.consecutive_failures += 1
                    logger.warning(
                        "monitor_query_failed",
                        endpoint=name,
                        error=str(exc),
                        consecutive_failures=state.consecutive_failures,
                    )
                    if state.consecutive_failures >= self._failure_threshold:
                        conservative_usage = min(
                            state.capacity_tps,
                            max(state.last_known_usage, int(state.capacity_tps * 0.9)),
                        )
                        logger.warning(
                            "monitor_conservative_mode",
                            endpoint=name,
                            conservative_usage=conservative_usage,
                        )
                        await state.gate.update_usage(conservative_usage)
                await self._emit_sample(name, state)
            await asyncio.sleep(self._interval)

    async def _emit_sample(self, name: str, state: _EndpointState) -> None:
        if self._on_sample is None:
            return
        stale = state.consecutive_failures >= self._failure_threshold
        record = MonitorSampleRecord(
            endpoint=name,
            usage_tps=state.gate.current_usage_tps,
            reserved_tokens=state.gate.reserved_tokens,
            available=state.gate.available,
            total_tps=state.capacity_tps,
            status="stale" if stale else "ok",
            consecutive_failures=state.consecutive_failures,
        )
        try:
            await self._on_sample(record)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("monitor_sample_write_failed", endpoint=name, error=str(exc))

    def stop(self) -> None:
        self._stopped = True


class MockMonitor:
    """Scripted monitor for tests. Interpolates (elapsed, usage) pairs per endpoint."""

    def __init__(
        self,
        gates: dict[str, InMemoryCapacityGate],
        scripts: dict[str, list[tuple[float, int]]],
        tick_interval: float = 1.0,
        capacities: dict[str, int] | None = None,
        on_sample: OnSample | None = None,
    ) -> None:
        self._gates = gates
        self._scripts = scripts
        self._tick_interval = tick_interval
        self._capacities = capacities or {name: gate.total_capacity for name, gate in gates.items()}
        self._on_sample = on_sample
        self._stopped = False

    @staticmethod
    def _interpolate(script: list[tuple[float, int]], elapsed: float) -> int:
        if not script:
            return 0
        if elapsed <= script[0][0]:
            return script[0][1]
        if elapsed >= script[-1][0]:
            return script[-1][1]
        for i in range(len(script) - 1):
            t0, v0 = script[i]
            t1, v1 = script[i + 1]
            if t0 <= elapsed <= t1:
                ratio = (elapsed - t0) / (t1 - t0)
                return int(v0 + ratio * (v1 - v0))
        return script[-1][1]

    async def refresh_loop(self) -> None:
        start = time.monotonic()
        while not self._stopped:
            elapsed = time.monotonic() - start
            for name, gate in self._gates.items():
                script = self._scripts.get(name, [])
                usage = self._interpolate(script, elapsed)
                await gate.update_usage(usage)
                await self._emit_sample(name, gate)
            await asyncio.sleep(self._tick_interval)

    async def _emit_sample(self, name: str, gate: InMemoryCapacityGate) -> None:
        if self._on_sample is None:
            return
        record = MonitorSampleRecord(
            endpoint=name,
            usage_tps=gate.current_usage_tps,
            reserved_tokens=gate.reserved_tokens,
            available=gate.available,
            total_tps=self._capacities.get(name, gate.total_capacity),
            status="ok",
            consecutive_failures=0,
        )
        try:
            await self._on_sample(record)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("monitor_sample_write_failed", endpoint=name, error=str(exc))

    def stop(self) -> None:
        self._stopped = True
