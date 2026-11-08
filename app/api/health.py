from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health/live")
async def live():
    return {"status": "live"}


@router.get("/health/ready")
async def ready(request: Request):
    is_ready = request.app.state.service.ready
    return JSONResponse(
        {"status": "ready" if is_ready else "not_ready"}, status_code=200 if is_ready else 503
    )
