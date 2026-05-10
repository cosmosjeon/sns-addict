"""sns-addict dashboard FastAPI application."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import aiofiles
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from sns_addict.dashboard.routes import allowlist, control, monitoring, persona, alerts, conversations

logger = logging.getLogger(__name__)

app = FastAPI(title="sns-addict dashboard")

# Static files
_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

@app.get("/")
async def index() -> FileResponse:
    return FileResponse(str(_STATIC_DIR / "index.html"))

# Include routers
app.include_router(allowlist.router, prefix="/api/allowlist")
app.include_router(control.router, prefix="/api/control")
app.include_router(monitoring.router, prefix="/api/monitoring")
app.include_router(persona.router, prefix="/api/persona")
app.include_router(alerts.router, prefix="/api/alerts")
app.include_router(conversations.router, prefix="/api/conversations")

# WebSocket events endpoint
_EVENTS_PATH = Path.home() / ".hermes" / "sns-addict" / "logs" / "events.jsonl"

@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        # Tail events.jsonl and push new lines to client
        last_size = 0
        while True:
            try:
                if _EVENTS_PATH.exists():
                    current_size = _EVENTS_PATH.stat().st_size
                    if current_size > last_size:
                        async with aiofiles.open(_EVENTS_PATH, "r") as f:
                            await f.seek(last_size)
                            new_content = await f.read()
                        last_size = current_size
                        for line in new_content.strip().splitlines():
                            if line.strip():
                                await websocket.send_text(line)
            except Exception as exc:
                logger.debug("WebSocket events read error: %s", exc)
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        logger.debug("WebSocket client disconnected")
