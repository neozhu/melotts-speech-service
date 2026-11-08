from dataclasses import asdict

from fastapi import APIRouter, Depends, Request

from app.api.auth import require_api_key
from app.services.voice_map import available_voices

router = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])


@router.get("/models")
async def models():
    return {
        "object": "list",
        "data": [
            {"id": model, "object": "model", "owned_by": "local"} for model in ("melotts", "tts-1")
        ],
    }


@router.get("/audio/voices")
async def voices(request: Request):
    languages = set(request.app.state.settings.tts_languages.split(","))
    return {"voices": [asdict(voice) for voice in available_voices(languages)]}
