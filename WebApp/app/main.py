"""WSIC portfolio backend.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8000

Endpoints
  GET  /                          the club website (frontend/index.html)
  GET  /api/portfolio             latest holdings, summary and recent trades (JSON)
  GET  /api/stream                Server-Sent Events: pushes a new snapshot whenever the sheet changes
  POST /api/webhook/sheet-changed called by the Apps Script trigger when someone edits the sheet
  POST /api/refresh               same as the webhook, for manual use (needs the secret)
  GET  /api/health                status for monitoring
  GET  /api/research/analyze      company analysis for one ticker (JSON)
  GET  /api/research/report       the same analysis as an Excel workbook
  GET  /api/research/health       whether the server has its own analyzer keys
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import hmac
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from . import config
from .portfolio import build_snapshot
from .research import router as research_router
from .sources import Source, make_source

log = logging.getLogger("wsic")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class PortfolioState:
    """Holds the latest good snapshot, re-reads the sheet on a timer or on demand,
    and fans changes out to every connected browser."""

    def __init__(self, source: Source) -> None:
        self.source = source
        self.snapshot: dict | None = None
        self.version: str | None = None
        self.last_checked: str | None = None
        self.last_changed: str | None = None
        self.last_error: str | None = None
        self._wake = asyncio.Event()
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    async def refresh(self, reason: str) -> bool:
        """Read the sheet; returns True if anything changed."""
        async with self._lock:
            try:
                rows = await asyncio.to_thread(self.source.fetch)
                data = build_snapshot(*rows)
            except Exception as exc:  # keep serving the last good data
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.warning("Refresh (%s) failed: %s", reason, self.last_error)
                return False
            self.last_error = None
            self.last_checked = _now()
            version = hashlib.sha1(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]
            if version == self.version:
                return False
            self.version = version
            self.last_changed = self.last_checked
            self.snapshot = data
            log.info("Portfolio changed (%s) -> version %s", reason, version)
        await self._broadcast()
        return True

    def payload(self) -> dict:
        return {
            **(self.snapshot or {"holdings": [], "summary": None, "transactions": []}),
            "meta": {
                "version": self.version,
                "source": self.source.name,
                "last_checked": self.last_checked,
                "last_changed": self.last_changed,
                "poll_seconds": config.POLL_SECONDS,
                "error": self.last_error,
            },
        }

    def poke(self) -> None:
        self._wake.set()

    async def run_poller(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=config.POLL_SECONDS)
                # Woken by the webhook: give new GOOGLEFINANCE formulas a moment to calculate.
                self._wake.clear()
                await asyncio.sleep(config.WEBHOOK_DELAY_SECONDS)
                self._wake.clear()  # collapse a burst of edits into one read
                changed = await self.refresh("sheet edited")
                if not changed:
                    # Formulas can lag a few seconds behind the edit; look once more.
                    await asyncio.sleep(10)
                    await self.refresh("sheet edited, follow-up")
            except asyncio.TimeoutError:
                await self.refresh("scheduled poll")

    # --- Server-Sent Events fan-out ---
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    async def _broadcast(self) -> None:
        for q in list(self._subscribers):
            if q.full():  # slow client: drop the stale snapshot, keep only the newest
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(True)


state: PortfolioState | None = None


class UnavailableSource:
    """Stands in when the configured sheet source can't be set up (e.g. no
    Google credentials yet), so the server still starts: the Portfolio tab
    reports the problem and the Research tab keeps working."""

    name = "unavailable"

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def fetch(self):
        raise RuntimeError(self._reason)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global state
    try:
        source = make_source()
    except Exception as exc:
        log.error("Portfolio source could not be set up: %s", exc)
        source = UnavailableSource(f"{type(exc).__name__}: {exc}")
    state = PortfolioState(source)
    await state.refresh("startup")
    task = asyncio.create_task(state.run_poller())
    log.info("Reading from %s every %ss", state.source.name, config.POLL_SECONDS)
    yield
    task.cancel()


app = FastAPI(title="WSIC Portfolio API", lifespan=lifespan)

if config.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

app.include_router(research_router)


def _check_secret(supplied: str | None) -> None:
    if not config.WEBHOOK_SECRET:
        raise HTTPException(503, "WEBHOOK_SECRET is not configured on the server")
    if not supplied or not hmac.compare_digest(supplied, config.WEBHOOK_SECRET):
        raise HTTPException(401, "Bad or missing secret")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(config.FRONTEND_FILE, headers={"Cache-Control": "no-cache"})


@app.get("/api/portfolio")
async def get_portfolio():
    if state.snapshot is None:
        return JSONResponse(state.payload(), status_code=503)
    return JSONResponse(state.payload(), headers={"Cache-Control": "no-store"})


@app.get("/api/stream")
async def stream(request: Request):
    queue = state.subscribe()

    async def events():
        try:
            if state.snapshot is not None:
                yield f"event: portfolio\ndata: {json.dumps(state.payload())}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    await asyncio.wait_for(queue.get(), timeout=25)
                    yield f"event: portfolio\ndata: {json.dumps(state.payload())}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"  # stops proxies from closing an idle connection
        finally:
            state.unsubscribe(queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.post("/api/webhook/sheet-changed")
async def sheet_changed(request: Request, x_webhook_secret: str | None = Header(default=None)):
    supplied = x_webhook_secret
    if supplied is None:  # also accept {"secret": "..."} in the JSON body
        try:
            supplied = (await request.json()).get("secret")
        except Exception:
            supplied = None
    _check_secret(supplied)
    state.poke()
    return {"ok": True, "message": f"Refreshing in ~{config.WEBHOOK_DELAY_SECONDS}s"}


@app.post("/api/refresh")
async def manual_refresh(x_webhook_secret: str | None = Header(default=None)):
    _check_secret(x_webhook_secret)
    changed = await state.refresh("manual")
    return {"ok": state.last_error is None, "changed": changed, "error": state.last_error}


@app.get("/api/health")
async def health():
    ok = state.snapshot is not None
    return JSONResponse(
        {"ok": ok, **state.payload()["meta"], "listeners": len(state._subscribers)},
        status_code=200 if ok else 503,
    )
