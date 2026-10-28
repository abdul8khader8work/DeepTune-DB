"""FastAPI application factory: lifespan, CORS, rate limits, error envelope."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api.deps import AppState
from src.api.legacy import router as legacy_router
from src.api.v1.router import router as v1_router
from src.core.config import Settings, get_settings
from src.core.errors import ApiError
from src.core.logging import configure_logging
from src.core.ratelimit import limiter
from src.db.metadata import create_connection_store
from src.db.run_archive import create_run_archive
from src.services.engine import load_engine
from src.services.runs import AppliedRegistry, RunRegistry

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    configure_logging()
    store = await create_connection_store(settings)
    archive = await create_run_archive(settings.metadata_dsn)
    # The GATv2 checkpoint is loaded exactly once, off the event loop. A failure
    # here must not stop the API: the pipeline degrades to heuristics.
    engine = await asyncio.to_thread(load_engine, settings)
    app.state.deeptune = AppState(
        settings=settings,
        store=store,
        runs=RunRegistry(settings, archive),
        applied=AppliedRegistry(),
        engine=engine,
    )
    logger.info(
        "DeepTune API %s ready (%s) — engine=%s",
        settings.app_version,
        settings.app_env,
        engine.status.backend,
    )
    try:
        yield
    finally:
        await app.state.deeptune.applied.close_all()
        await archive.close()
        await store.close()
        logger.info("DeepTune API stopped")


def _error(
    status_code: int,
    error_code: str,
    message: str,
    suggestion: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    detail: dict[str, str] = {"error_code": error_code, "message": message}
    if suggestion:
        detail["suggestion"] = suggestion
    return JSONResponse(status_code=status_code, content={"detail": detail}, headers=headers)


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_body(),
        headers=exc.headers,
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    parts: list[str] = []
    for error in exc.errors()[:3]:
        location = ".".join(str(item) for item in error.get("loc", ()))
        parts.append(f"{location}: {error.get('msg', 'invalid value')}")
    return _error(
        422,
        "VALIDATION_ERROR",
        "; ".join(parts) or "Request body failed validation.",
        "Check field types and allowed values in the OpenAPI schema.",
    )


async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return _error(
        429,
        "RATE_LIMITED",
        f"Analyze rate limit exceeded ({exc.detail}).",
        "Wait before retrying; the limit is per client IP.",
        headers={"Retry-After": "60"},
    )


async def http_error_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    try:
        code = HTTPStatus(exc.status_code).phrase.upper().replace(" ", "_")
    except ValueError:
        code = "HTTP_ERROR"
    return _error(exc.status_code, code, str(exc.detail))


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="DeepTune API",
        version=settings.app_version,
        description=(
            "Read-only PostgreSQL plan analysis, hypothetical index validation "
            "with hypopg, and reviewable index recommendations."
        ),
        lifespan=lifespan,
    )
    app.state.limiter = limiter
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(v1_router, prefix=settings.api_v1_prefix)
    app.include_router(legacy_router)
    return app


app = create_app()
