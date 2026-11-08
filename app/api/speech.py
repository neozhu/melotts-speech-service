import time

from fastapi import APIRouter, Depends, Request, Response

from app.api.auth import require_api_key
from app.errors import ServiceError
from app.schemas.speech import SpeechRequest
from app.services.voice_map import resolve_voice

router = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])


@router.post("/audio/speech")
async def speech(body: SpeechRequest, request: Request):
    settings = request.app.state.settings
    if body.model not in {"melotts", "tts-1"}:
        raise ServiceError(400, "Unsupported model.", "invalid_model", "model")
    if body.response_format not in {"wav", "mp3"}:
        raise ServiceError(400, "Use wav or mp3.", "invalid_response_format", "response_format")
    if len(body.input) > settings.tts_max_text_length:
        raise ServiceError(
            400, "Input exceeds the configured text limit.", "invalid_input", "input"
        )
    try:
        voice = resolve_voice(
            body.voice or settings.tts_default_voice, set(settings.tts_languages.split(","))
        )
    except ValueError as exc:
        raise ServiceError(400, "Unsupported voice.", "invalid_voice", "voice") from exc
    request.state.voice = voice.id
    started = time.perf_counter()
    audio = await request.app.state.service.synthesize(
        body.input, voice.id, body.speed, body.response_format
    )
    request.state.synthesis_ms = round((time.perf_counter() - started) * 1000, 2)
    request.state.encoded_bytes = len(audio)
    return Response(
        audio,
        media_type="audio/wav" if body.response_format == "wav" else "audio/mpeg",
        headers={"Content-Disposition": "inline", "Cache-Control": "no-store"},
    )
