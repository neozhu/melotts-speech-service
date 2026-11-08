import secrets

from fastapi import Request

from app.errors import ServiceError


async def require_api_key(request: Request):
    key = request.app.state.settings.api_key.get_secret_value()
    if not key:
        return
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(token.encode(), key.encode()):
        raise ServiceError(401, "Invalid API key.", "invalid_api_key")
