"""FastAPI entrypoint: static UI, health check, config API and the voice WebSocket."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from google import genai

from app import __version__
from app.config import Settings, get_settings
from app.live_session import CallBridge
from app.logging_setup import configure_logging
from app.progress import sanitize_previous_case
from app.prompts import LANGUAGES, MODES
from app.seller_data import SELLER, brief_metrics_table, public_profile

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' https://fonts.googleapis.com",
        "font-src https://fonts.gstatic.com",
        "connect-src 'self' ws: wss:",
        "img-src 'self' data:",
        "media-src 'self' blob:",
        "worker-src 'self' blob:",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ]
)


def create_genai_client(settings: Settings) -> genai.Client:
    """Vertex AI with ADC by default; Gemini API key (AI Studio) if provided."""
    if settings.use_vertex_ai:
        return genai.Client(
            vertexai=True,
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
        )
    return genai.Client(api_key=settings.gemini_api_key)


START_MESSAGE_TIMEOUT_S = 5
MAX_START_MESSAGE_BYTES = 64_000


async def read_previous_case(websocket: WebSocket) -> dict | None:
    """Follow-up calls start with {"type": "start", "previous_case": {...}} from the browser (optional)."""
    try:
        message = await asyncio.wait_for(websocket.receive(), timeout=START_MESSAGE_TIMEOUT_S)
    except TimeoutError:
        return None
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(message.get("code", 1000))
    text = message.get("text")
    if not text or len(text) > MAX_START_MESSAGE_BYTES:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict) and payload.get("type") == "start":
        return sanitize_previous_case(payload.get("previous_case"))
    return None


def origin_allowed(websocket: WebSocket, settings: Settings) -> bool:
    """Block cross-site WebSocket hijacking: browsers must connect from our own origin."""
    origin = websocket.headers.get("origin")
    if not origin:
        return True  # non-browser clients (e.g. the scripted end-to-end test)
    origin = origin.rstrip("/")
    if origin in settings.allowed_origins:
        return True
    return urlsplit(origin).netloc == websocket.headers.get("host", "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    configure_logging(settings.log_level)
    if getattr(app.state, "genai_client", None) is None:  # tests inject a fake client
        app.state.genai_client = create_genai_client(settings)
    logger.info(
        "startup",
        extra={
            "json_fields": {
                "event": "startup",
                "version": __version__,
                "model": settings.live_model,
                "backend": "vertex_ai" if settings.use_vertex_ai else "gemini_api",
                "location": settings.google_cloud_location,
            }
        },
    )
    yield


def create_app(settings: Settings | None = None, genai_client: genai.Client | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="Disha - AI Virtual KAM for Snapdeal sellers",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.genai_client = genai_client
    app.state.active_calls = 0

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "microphone=(self), camera=(), geolocation=()")
        return response

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    @app.get("/", include_in_schema=False)
    async def index(request: Request) -> HTMLResponse:
        # Absolute URLs for link previews (WhatsApp, Slack, email) when the demo link is shared.
        html = index_html.replace("__BASE_URL__", str(request.base_url))
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/api/config")
    async def config() -> dict:
        return {
            "seller": public_profile(SELLER),
            "metrics": brief_metrics_table(SELLER),
            "assumptions": list(SELLER.assumptions),
            "model": settings.live_model,
            "voice": settings.voice_name,
            "max_call_seconds": settings.max_call_seconds,
        }

    @app.websocket("/ws/call")
    async def call_socket(websocket: WebSocket) -> None:
        mode = websocket.query_params.get("mode", "inbound")
        language = websocket.query_params.get("lang", "en")
        mode = mode if mode in MODES else "inbound"
        language = language if language in LANGUAGES else "en"

        if not origin_allowed(websocket, settings):
            logger.warning("Rejected WebSocket from origin %s", websocket.headers.get("origin"))
            await websocket.close(code=1008)
            return

        await websocket.accept()
        if app.state.active_calls >= settings.max_concurrent_calls:
            await websocket.send_json(
                {"type": "error", "message": "All lines are busy right now. Please try again in a minute."}
            )
            await websocket.close(code=1013)
            return

        app.state.active_calls += 1
        try:
            previous_case = await read_previous_case(websocket) if mode == "followup" else None
            bridge = CallBridge(
                websocket,
                app.state.genai_client,
                settings,
                mode=mode,
                language=language,
                previous_case=previous_case,
            )
            await bridge.run()
        except WebSocketDisconnect:
            pass
        finally:
            app.state.active_calls -= 1
            with suppress(Exception):
                await websocket.close()

    return app


app = create_app()
