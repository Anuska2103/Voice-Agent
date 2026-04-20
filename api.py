from __future__ import annotations

import logging
import sys
import time
import datetime
import re
import secrets
import traceback
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from livekit import api as livekit_api

from config import settings


def configure_logging() -> None:
    """Configure stdout logging for Render-friendly debug visibility."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        stream=sys.stdout,
        force=True,
    )


configure_logging()
LOGGER = logging.getLogger(__name__)


@asynccontextmanager
async def app_lifespan(_: FastAPI):
    LOGGER.info("🚀 Server started successfully")
    try:
        yield
    except Exception:
        LOGGER.exception("❌ Error occurred during application lifespan")
        raise
    finally:
        LOGGER.info("🛑 Server shutdown initiated")
        LOGGER.info("Server shut down cleanly")


app = FastAPI(title="NewVoice API", version="1.0.0", lifespan=app_lifespan)


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


def _safe_decode_request_body(body_bytes: bytes) -> str:
    if not body_bytes:
        return ""
    return body_bytes.decode("utf-8", errors="replace")


@app.middleware("http")
async def request_response_logging_middleware(request: Request, call_next):
    start_time = time.perf_counter()
    request_body = await request.body()
    request_body_text = _safe_decode_request_body(request_body)

    LOGGER.info("📩 Incoming request")
    LOGGER.debug("Request method=%s url=%s", request.method, str(request.url))
    LOGGER.debug("Request headers=%s", dict(request.headers))
    LOGGER.debug("Request body=%s", request_body_text)

    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        LOGGER.error(
            "Error occurred while processing request method=%s url=%s processing_time_ms=%.2f",
            request.method,
            str(request.url),
            elapsed_ms,
        )
        LOGGER.error("Exception traceback:\n%s", traceback.format_exc())
        raise

    elapsed_ms = (time.perf_counter() - start_time) * 1000
    LOGGER.info(" Sending response")
    LOGGER.debug(
        "Response status=%s method=%s url=%s processing_time_ms=%.2f",
        response.status_code,
        request.method,
        str(request.url),
        elapsed_ms,
    )

    if response.status_code >= 400:
        LOGGER.warning(
            "Request finished with error status=%s method=%s url=%s",
            response.status_code,
            request.method,
            str(request.url),
        )

    return response


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


@app.get("/")
async def root() -> dict[str, str]:
    LOGGER.info("Root endpoint accessed")
    return {"status": "running", "message": "NewVoice FastAPI server is running"}


@app.get("/health")
async def health() -> dict[str, str]:
    LOGGER.info("Health check endpoint accessed")
    return {"status": "OK"}


@app.post(f"{settings.api_prefix}/livekit/token", response_model=TokenResponse)
async def create_livekit_token(payload: TokenRequest) -> TokenResponse:
    LOGGER.info("LiveKit token endpoint accessed")
    LOGGER.debug("Token request identity=%s room=%s", payload.identity, payload.room)

    if not settings.livekit_api_key or not settings.livekit_api_secret:
        LOGGER.error("LiveKit API credentials missing on server")
        raise HTTPException(status_code=500, detail="LiveKit credentials are not configured on server")

    if not settings.livekit_url:
        LOGGER.error("LIVEKIT_URL is not configured on server")
        raise HTTPException(status_code=500, detail="LIVEKIT_URL is not configured on server")

    if settings.join_access_key and payload.access_key != settings.join_access_key:
        LOGGER.warning("Invalid join access key for identity=%s", payload.identity)
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

    LOGGER.debug("Token generated successfully for identity=%s room=%s", payload.identity, room_name)

    return TokenResponse(
        token=token,
        room=room_name,
        identity=payload.identity,
        ws_url=settings.livekit_url,
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    LOGGER.warning(
        "HTTPException raised method=%s url=%s status=%s detail=%s",
        request.method,
        str(request.url),
        exc.status_code,
        exc.detail,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "type": "HTTPException",
                "message": str(exc.detail),
                "status_code": exc.status_code,
                "path": request.url.path,
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    LOGGER.warning(
        "Validation error method=%s url=%s errors=%s",
        request.method,
        str(request.url),
        exc.errors(),
    )
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "type": "ValidationError",
                "message": "Request validation failed",
                "status_code": 422,
                "path": request.url.path,
                "details": exc.errors(),
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    LOGGER.error(
        "❌ Error occurred method=%s url=%s error=%s",
        request.method,
        str(request.url),
        repr(exc),
    )
    LOGGER.error("Full traceback:\n%s", traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "type": exc.__class__.__name__,
                "message": "Internal server error",
                "status_code": 500,
                "path": request.url.path,
            }
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
