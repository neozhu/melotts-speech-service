import json
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import health, models, speech
from app.config import Settings
from app.errors import ServiceError
from app.services.inference import InferenceService

logger = logging.getLogger("speech")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        fields = {"level": record.levelname, "event": record.getMessage()}
        for name in (
            "request_id",
            "voice",
            "status",
            "elapsed_ms",
            "synthesis_ms",
            "encoded_bytes",
            "error_type",
            "hint",
            "language",
            "asset",
        ):
            if hasattr(record, name):
                fields[name] = getattr(record, name)
        return json.dumps(fields, ensure_ascii=True)


def create_app(settings: Settings | None = None, *, engine=None) -> FastAPI:
    settings = settings or Settings()
    if engine is None:
        from app.services.melo_engine import MeloEngine

        engine = MeloEngine(settings)

    service = InferenceService(settings, engine)

    @asynccontextmanager
    async def lifespan(app):
        service.start()
        try:
            yield
        finally:
            await service.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.service = service

    @app.exception_handler(ServiceError)
    async def service_error(request, exc):
        headers = {"Retry-After": "5"} if exc.status == 429 else {}
        if exc.status == 401:
            headers["WWW-Authenticate"] = "Bearer"
        return JSONResponse(exc.body(), status_code=exc.status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Never serialize Pydantic's input/context fields; they can contain user text.
        loc = exc.errors()[0].get("loc", ())
        param = str(loc[1]) if len(loc) > 1 and isinstance(loc[1], str) else None
        known = {"model", "input", "voice", "speed", "response_format"}
        code = f"invalid_{param}" if param in known else "invalid_request"
        return JSONResponse(
            ServiceError(400, "Invalid request field.", code, param).body(), status_code=400
        )

    @app.middleware("http")
    async def diagnostics(request: Request, call_next):
        request_id = uuid.uuid4().hex
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error(
                "request_failed",
                extra={
                    "request_id": request_id,
                    "error_type": type(exc).__name__,
                },
            )
            response = JSONResponse(
                ServiceError(500, "Speech generation failed.", "internal_error").body(),
                status_code=500,
            )
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_completed",
            extra={
                "request_id": request_id,
                "status": response.status_code,
                "voice": getattr(request.state, "voice", None),
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                "synthesis_ms": getattr(request.state, "synthesis_ms", None),
                "encoded_bytes": getattr(request.state, "encoded_bytes", 0),
            },
        )
        return response

    app.include_router(health.router)
    app.include_router(models.router)
    app.include_router(speech.router)
    return app


def run():
    import uvicorn

    settings = Settings()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.handlers = [handler]
    logger.setLevel(settings.log_level)
    logger.propagate = False
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        workers=1,
        access_log=False,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()
