import asyncio

import pytest

from deerflow.runtime.keyed_lock import AsyncKeyedLockTable


@pytest.mark.asyncio
async def test_reclaims_idle_keys() -> None:
    table = AsyncKeyedLockTable[str]()

    for index in range(100):
        async with table.hold(f"thread-{index}"):
            assert table._entry_count() == 1

    assert table._entry_count() == 0


@pytest.mark.asyncio
async def test_waiter_keeps_the_same_entry_until_it_finishes() -> None:
    table = AsyncKeyedLockTable[str]()
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    order: list[str] = []

    async def first() -> None:
        async with table.hold("thread"):
            order.append("first-enter")
            first_entered.set()
            await release_first.wait()
            order.append("first-exit")

    async def second() -> None:
        await first_entered.wait()
        async with table.hold("thread"):
            order.append("second-enter")

    first_task = asyncio.create_task(first())
    second_task = asyncio.create_task(second())
    await first_entered.wait()
    await asyncio.sleep(0)
    assert table._entry_count() == 1

    release_first.set()
    await asyncio.gather(first_task, second_task)

    assert order == ["first-enter", "first-exit", "second-enter"]
    assert table._entry_count() == 0


@pytest.mark.asyncio
async def test_cancelled_waiter_releases_its_participant_reference() -> None:
    table = AsyncKeyedLockTable[str]()
    release_holder = asyncio.Event()
    holder_entered = asyncio.Event()

    async def holder() -> None:
        async with table.hold("thread"):
            holder_entered.set()
            await release_holder.wait()

    async def waiter() -> None:
        async with table.hold("thread"):
            raise AssertionError("cancelled waiter entered the lock")

    holder_task = asyncio.create_task(holder())
    await holder_entered.wait()
    waiter_task = asyncio.create_task(waiter())
    await asyncio.sleep(0)
    waiter_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter_task

    assert table._entry_count() == 1
    release_holder.set()
    await holder_task
    assert table._entry_count() == 0


@pytest.mark.asyncio
async def test_different_keys_do_not_block_each_other() -> None:
    table = AsyncKeyedLockTable[str]()
    both_entered = asyncio.Event()
    entered = 0

    async def hold(key: str) -> None:
        nonlocal entered
        async with table.hold(key):
            entered += 1
            if entered == 2:
                both_entered.set()
            await both_entered.wait()

    await asyncio.wait_for(asyncio.gather(hold("a"), hold("b")), timeout=1)
    assert table._entry_count() == 0
