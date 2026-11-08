import asyncio
import logging
from dataclasses import dataclass

from app.config import Settings
from app.errors import ServiceError

logger = logging.getLogger("speech")


@dataclass
class Job:
    arguments: tuple
    future: asyncio.Future
    started: bool = False


class InferenceService:
    """One consumer owns all native work, including startup and lazy model loads."""

    def __init__(self, settings: Settings, engine):
        self.settings = settings
        self.engine = engine
        self.ready = False
        self.accepting = True
        self.pending = 0
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=settings.tts_max_queue + 1)
        self.startup_done = asyncio.Event()
        self.worker: asyncio.Task | None = None

    def start(self):
        self.worker = asyncio.create_task(self._run())

    async def wait_startup(self):
        await self.startup_done.wait()

    async def _run(self):
        try:
            await asyncio.to_thread(self.engine.warmup)
        except Exception as exc:
            logger.error(
                "startup_failed",
                extra={
                    "error_type": type(exc).__name__,
                    "hint": "Check outbound Hugging Face access, model checksums and cache "
                    "permissions; restart after correcting the cause.",
                },
            )
            self.startup_done.set()
            return
        self.ready = self.accepting
        self.startup_done.set()
        logger.info("models_ready")
        while True:
            job = await self.queue.get()
            if job is None:
                return
            try:
                if job.future.done():
                    continue
                job.started = True
                result = await asyncio.to_thread(self.engine.synthesize, *job.arguments)
                if not job.future.done():
                    job.future.set_result(result)
            except Exception as exc:
                if not job.future.done():
                    job.future.set_exception(exc)
            finally:
                self.pending -= 1

    async def synthesize(self, text: str, voice: str, speed: float, fmt: str) -> bytes:
        if not self.ready or not self.accepting:
            raise ServiceError(503, "Models are not ready.", "model_not_ready")
        # No await between admission check and insertion: atomic on the event loop.
        if self.pending >= self.settings.tts_max_queue + 1:
            raise ServiceError(
                429, "Inference capacity is full. Retry later.", "rate_limit_exceeded"
            )
        loop = asyncio.get_running_loop()
        job = Job((text, voice, speed, fmt), loop.create_future())
        self.pending += 1
        self.queue.put_nowait(job)

        def expire():
            if not job.started and not job.future.done():
                job.future.set_exception(
                    ServiceError(
                        503, "Request expired while waiting for inference.", "queue_timeout"
                    )
                )

        timer = loop.call_later(self.settings.tts_queue_timeout_seconds, expire)
        try:
            return await job.future
        finally:
            timer.cancel()

    async def close(self):
        self.accepting = False
        self.ready = False
        while not self.queue.empty():
            job = self.queue.get_nowait()
            self.pending -= 1
            if not job.future.done():
                job.future.set_exception(
                    ServiceError(503, "Service is stopping.", "model_not_ready")
                )
        if self.worker and not self.worker.done():
            await self.queue.put(None)
            # Native inference is not cancelled; the slot stays occupied until completion.
            await self.worker
