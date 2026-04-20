import asyncio
from typing import Protocol


class CapacityGate(Protocol):
    def can_fit(self, estimated_tokens: int) -> bool: ...
    async def wait_for_capacity(self, estimated_tokens: int) -> None: ...
    def reserve(self, estimated_tokens: int) -> None: ...
    async def release(self, estimated_tokens: int) -> None: ...
    async def report_actual_usage(self, actual_tokens: int, estimated_tokens: int) -> None: ...
    async def update_usage(self, current_usage_tokens_per_sec: int) -> None: ...


class InMemoryCapacityGate:
    """Per-endpoint capacity tracker.

    Accounting is intentionally unclamped: over-releases and negative balances
    stay visible so accounting bugs surface in tests and health output.
    """

    def __init__(self, total_capacity_tps: int) -> None:
        self._total_capacity = total_capacity_tps
        self._current_usage_tps = 0
        self._reserved_tokens = 0
        self._provisional_tokens = 0
        self._condition = asyncio.Condition()

    @property
    def total_capacity(self) -> int:
        return self._total_capacity

    @property
    def current_usage_tps(self) -> int:
        return self._current_usage_tps

    @property
    def reserved_tokens(self) -> int:
        return self._reserved_tokens

    @property
    def available(self) -> int:
        return self._total_capacity - self._current_usage_tps - self._reserved_tokens

    def can_fit(self, estimated_tokens: int) -> bool:
        return self.available >= estimated_tokens

    async def wait_for_capacity(self, estimated_tokens: int) -> None:
        async with self._condition:
            while not self.can_fit(estimated_tokens):
                await self._condition.wait()
            self._reserved_tokens += estimated_tokens
            self._provisional_tokens += estimated_tokens

    def reserve(self, estimated_tokens: int) -> None:
        if self._provisional_tokens >= estimated_tokens:
            self._provisional_tokens -= estimated_tokens
            return
        self._reserved_tokens += estimated_tokens

    async def release(self, estimated_tokens: int) -> None:
        self._reserved_tokens -= estimated_tokens
        self._provisional_tokens = min(self._provisional_tokens, self._reserved_tokens)
        async with self._condition:
            self._condition.notify_all()

    async def report_actual_usage(self, actual_tokens: int, estimated_tokens: int) -> None:
        delta = actual_tokens - estimated_tokens
        self._reserved_tokens += delta
        async with self._condition:
            self._condition.notify_all()

    async def update_usage(self, current_usage_tokens_per_sec: int) -> None:
        self._current_usage_tps = current_usage_tokens_per_sec
        async with self._condition:
            self._condition.notify_all()
