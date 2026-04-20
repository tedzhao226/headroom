import asyncio

import pytest

from headroom.services.capacity_gate import InMemoryCapacityGate


@pytest.fixture
def gate() -> InMemoryCapacityGate:
    return InMemoryCapacityGate(total_capacity_tps=10_000)


def test_can_fit_returns_true_when_space_available(gate: InMemoryCapacityGate) -> None:
    assert gate.can_fit(5_000) is True


def test_can_fit_returns_true_at_exact_capacity(gate: InMemoryCapacityGate) -> None:
    assert gate.can_fit(10_000) is True


def test_can_fit_returns_false_when_over_capacity(gate: InMemoryCapacityGate) -> None:
    assert gate.can_fit(10_001) is False


def test_can_fit_false_after_reserve(gate: InMemoryCapacityGate) -> None:
    gate.reserve(8_000)
    assert gate.can_fit(3_000) is False


def test_reserve_reduces_available(gate: InMemoryCapacityGate) -> None:
    gate.reserve(3_000)
    assert gate.available == 7_000


async def test_release_restores_available(gate: InMemoryCapacityGate) -> None:
    gate.reserve(3_000)
    await gate.release(3_000)
    assert gate.available == 10_000


async def test_release_partial(gate: InMemoryCapacityGate) -> None:
    gate.reserve(6_000)
    await gate.release(2_000)
    assert gate.available == 6_000


async def test_update_usage_reduces_available(gate: InMemoryCapacityGate) -> None:
    await gate.update_usage(4_000)
    assert gate.available == 6_000


async def test_update_usage_replaces_previous_value(gate: InMemoryCapacityGate) -> None:
    await gate.update_usage(4_000)
    await gate.update_usage(2_000)
    assert gate.available == 8_000


async def test_report_actual_usage_adjusts_reserved_upward(gate: InMemoryCapacityGate) -> None:
    gate.reserve(1_000)
    await gate.report_actual_usage(actual_tokens=1_500, estimated_tokens=1_000)
    assert gate.available == 10_000 - 1_500


async def test_report_actual_usage_adjusts_reserved_downward(gate: InMemoryCapacityGate) -> None:
    gate.reserve(1_000)
    await gate.report_actual_usage(actual_tokens=600, estimated_tokens=1_000)
    assert gate.available == 10_000 - 600


async def test_report_actual_usage_no_delta(gate: InMemoryCapacityGate) -> None:
    gate.reserve(1_000)
    await gate.report_actual_usage(actual_tokens=1_000, estimated_tokens=1_000)
    assert gate.available == 9_000


async def test_wait_for_capacity_returns_immediately_when_space_available(
    gate: InMemoryCapacityGate,
) -> None:
    await asyncio.wait_for(gate.wait_for_capacity(5_000), timeout=1.0)


async def test_wait_for_capacity_unblocks_on_release(gate: InMemoryCapacityGate) -> None:
    gate.reserve(9_000)

    unblocked = asyncio.Event()

    async def waiter() -> None:
        await gate.wait_for_capacity(2_000)
        unblocked.set()

    task = asyncio.create_task(waiter())
    await asyncio.sleep(0.01)
    assert not unblocked.is_set()

    await gate.release(5_000)
    await asyncio.sleep(0.01)
    assert unblocked.is_set()
    task.cancel()


async def test_wait_for_capacity_unblocks_on_update_usage(gate: InMemoryCapacityGate) -> None:
    await gate.update_usage(9_000)

    unblocked = asyncio.Event()

    async def waiter() -> None:
        await gate.wait_for_capacity(2_000)
        unblocked.set()

    task = asyncio.create_task(waiter())
    await asyncio.sleep(0.01)
    assert not unblocked.is_set()

    await gate.update_usage(1_000)
    await asyncio.sleep(0.01)
    assert unblocked.is_set()
    task.cancel()


async def test_multiple_waiters_unblock_when_capacity_freed(gate: InMemoryCapacityGate) -> None:
    gate.reserve(10_000)

    events = [asyncio.Event() for _ in range(3)]

    async def waiter(event: asyncio.Event) -> None:
        await gate.wait_for_capacity(100)
        event.set()

    tasks = [asyncio.create_task(waiter(e)) for e in events]
    await asyncio.sleep(0.01)
    assert not any(e.is_set() for e in events)

    await gate.release(10_000)
    await asyncio.sleep(0.01)
    assert all(e.is_set() for e in events)

    for t in tasks:
        t.cancel()


async def test_over_release_makes_available_exceed_total(gate: InMemoryCapacityGate) -> None:
    gate.reserve(1_000)
    await gate.release(2_000)
    assert gate.available == 11_000


async def test_wait_for_capacity_claim_is_atomic_across_waiters() -> None:
    gate = InMemoryCapacityGate(total_capacity_tps=100)
    gate.reserve(100)

    claimed = [asyncio.Event(), asyncio.Event()]

    async def waiter(index: int) -> None:
        await gate.wait_for_capacity(60)
        gate.reserve(60)
        claimed[index].set()

    tasks = [asyncio.create_task(waiter(0)), asyncio.create_task(waiter(1))]
    await asyncio.sleep(0.01)

    await gate.release(100)
    await asyncio.sleep(0.01)

    assert claimed[0].is_set() != claimed[1].is_set()
    assert gate._reserved_tokens == 60
    assert gate.available == 40

    await gate.release(60)
    await asyncio.sleep(0.01)

    assert claimed[0].is_set() and claimed[1].is_set()
    assert gate._reserved_tokens == 60
    assert gate.available == 40

    await gate.release(60)
    for task in tasks:
        await task
