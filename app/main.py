"""FastAPI entrypoint. Wires config, logging, request auditing, and routers.

The API is the only way in: the UI, agents, and management layer are all clients
of these same endpoints (TRD principle 1). No domain logic lives here.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger

from app import __version__
from app.api import (
    agents,
    clock,
    events,
    halt,
    marketdata,
    messages,
    metrics,
    orders,
    reporting,
)
from app.clock import get_clock
from app.config import get_settings
from app.finite import json_safe
from app.logging_setup import setup_logging
from app.scheduler import shutdown_scheduler, start_scheduler


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Own the background jobs for exactly as long as the server runs."""
    start_scheduler()
    try:
        yield
    finally:
        shutdown_scheduler()


def create_app() -> FastAPI:
    setup_logging()
    settings = get_settings()

    app = FastAPI(
        title="AI Fund Environment",
        version=__version__,
        summary="Deterministic environment/bus for a simulated multi-agent fund.",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def audit_requests(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Structured per-request log: who (best-effort), what, when, result.
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.bind(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
            clock_time=get_clock().now().isoformat(),
            client=request.client.host if request.client else None,
        ).info("request")
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's own handler echoes the bad input; a NaN there made the 422
        # unrenderable (500, red-team 0001), and so did a ~1000-deep input
        # (red-team 0004). Same body, spelled as standard JSON, depth-bounded.
        return JSONResponse(
            status_code=422, content={"detail": jsonable_encoder(json_safe(exc.errors()))}
        )

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, object]:
        return {"status": "ok", "version": __version__, "clock_mode": get_clock().mode}

    app.include_router(agents.router)
    app.include_router(events.router)
    app.include_router(clock.router)
    app.include_router(halt.router)
    app.include_router(marketdata.router)
    app.include_router(orders.router)
    app.include_router(messages.router)
    app.include_router(reporting.router)
    app.include_router(metrics.router)

    logger.info("app created (env database_url={})", settings.database_url)
    return app


app = create_app()
