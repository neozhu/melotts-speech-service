import asyncio
import threading
from unittest.mock import Mock

import pytest

from app.config import Settings
from app.errors import ServiceError
from app.services.inference import InferenceService


async def wait_event(event):
    assert await asyncio.to_thread(event.wait, 5)


@pytest.mark.parametrize("max_queue", [0, 4])
async def test_bounded_queue_and_cancelled_running_work(max_queue):
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def synthesize(text, *args):
        calls.append(text)
        entered.set()
        assert release.wait(5)
        return b"audio"

    engine = Mock(synthesize=synthesize)
    service = InferenceService(Settings(tts_max_queue=max_queue), engine)
    service.start()
    await service.wait_startup()
    active = asyncio.create_task(service.synthesize("active", "zh", 1, "wav"))
    await wait_event(entered)
    waiting = [
        asyncio.create_task(service.synthesize(str(i), "zh", 1, "wav")) for i in range(max_queue)
    ]
    await asyncio.sleep(0)
    try:
        with pytest.raises(ServiceError) as error:
            await service.synthesize("excess", "zh", 1, "wav")
        assert error.value.status == 429
        active.cancel()
        with pytest.raises(asyncio.CancelledError):
            await active
        assert service.pending == max_queue + 1
        with pytest.raises(ServiceError) as error:
            await service.synthesize("still full", "zh", 1, "wav")
        assert error.value.status == 429
    finally:
        release.set()
        await asyncio.gather(*waiting)
        await service.close()
    assert len(calls) == max_queue + 1
    assert service.pending == 0


async def test_queue_deadline_never_cancels_native_inference():
    entered = threading.Event()
    release = threading.Event()
    engine = Mock()

    def synthesize(*args):
        entered.set()
        assert release.wait(5)
        return b"audio"

    engine.synthesize.side_effect = synthesize
    service = InferenceService(Settings(tts_queue_timeout_seconds=0.03), engine)
    service.start()
    await service.wait_startup()
    active = asyncio.create_task(service.synthesize("a", "zh", 1, "wav"))
    await wait_event(entered)
    try:
        with pytest.raises(ServiceError) as error:
            await service.synthesize("expired", "zh", 1, "wav")
        assert error.value.code == "queue_timeout"
        assert not active.done()
    finally:
        release.set()
        assert await active == b"audio"
        await service.close()
    assert engine.synthesize.call_count == 1


async def test_cancelled_queued_request_is_not_synthesized():
    entered = threading.Event()
    release = threading.Event()
    engine = Mock()

    def synthesize(*args):
        entered.set()
        assert release.wait(5)
        return b"audio"

    engine.synthesize.side_effect = synthesize
    service = InferenceService(Settings(), engine)
    service.start()
    await service.wait_startup()
    active = asyncio.create_task(service.synthesize("a", "zh", 1, "wav"))
    await wait_event(entered)
    queued = asyncio.create_task(service.synthesize("b", "zh", 1, "wav"))
    await asyncio.sleep(0)
    queued.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued
    release.set()
    await active
    await service.close()
    assert engine.synthesize.call_count == 1


async def test_worker_recovers_after_request_failure():
    engine = Mock()
    engine.synthesize.side_effect = [RuntimeError("failed"), b"audio"]
    service = InferenceService(Settings(), engine)
    service.start()
    await service.wait_startup()
    try:
        with pytest.raises(RuntimeError):
            await service.synthesize("a", "zh", 1, "wav")
        assert await service.synthesize("b", "zh", 1, "wav") == b"audio"
    finally:
        await service.close()


async def test_shutdown_during_warmup_cannot_leave_ready():
    entered = threading.Event()
    release = threading.Event()

    def warmup():
        entered.set()
        assert release.wait(5)

    service = InferenceService(Settings(), Mock(warmup=warmup))
    service.start()
    await wait_event(entered)
    closing = asyncio.create_task(service.close())
    await asyncio.sleep(0)
    release.set()
    await closing
    assert not service.ready
