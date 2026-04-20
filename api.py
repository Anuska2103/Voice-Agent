from __future__ import annotations

import datetime
import re
import secrets
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from livekit import api as livekit_api

from config import settings


app = FastAPI(title="NewVoice API", version="1.0.0")


def _parse_cors_origins(cors_origins: str) -> list[str]:
    if cors_origins.strip() == "*":
        return ["*"]
    return [origin.strip() for origin in cors_origins.split(",") if origin.strip()]


origins = _parse_cors_origins(settings.cors_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TokenRequest(BaseModel):
    identity: str = Field(..., min_length=2, max_length=64)
    room: Optional[str] = Field(default=None, min_length=2, max_length=128)
    name: Optional[str] = Field(default=None, max_length=64)
    access_key: Optional[str] = Field(default=None, max_length=128)


class TokenResponse(BaseModel):
    token: str
    room: str
    identity: str
    ws_url: str


def _sanitize_room_name(room: str) -> str:
    # Keep room names browser and LiveKit friendly.
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "-", room).strip("-")
    return cleaned[:128] or "newvoice-room"


def _generate_private_room_name() -> str:
    suffix = secrets.token_urlsafe(8)
    suffix = re.sub(r"[^a-zA-Z0-9_-]", "", suffix)
    return f"nv-{suffix[:14]}"


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(f"{settings.api_prefix}/livekit/token", response_model=TokenResponse)
async def create_livekit_token(payload: TokenRequest) -> TokenResponse:
    if not settings.livekit_api_key or not settings.livekit_api_secret:
        raise HTTPException(status_code=500, detail="LiveKit credentials are not configured on server")

    if not settings.livekit_url:
        raise HTTPException(status_code=500, detail="LIVEKIT_URL is not configured on server")

    if settings.join_access_key and payload.access_key != settings.join_access_key:
        raise HTTPException(status_code=403, detail="Invalid access key")

    room_name = _sanitize_room_name(payload.room) if payload.room else _generate_private_room_name()

    grants = livekit_api.VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
    )

    token = (
        livekit_api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(payload.identity)
        .with_name(payload.name or payload.identity)
        .with_ttl(datetime.timedelta(hours=4))
        .with_grants(grants)
        .to_jwt()
    )

    return TokenResponse(
        token=token,
        room=room_name,
        identity=payload.identity,
        ws_url=settings.livekit_url,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
