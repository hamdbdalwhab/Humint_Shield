"""FastAPI application factory and lifespan management."""
from __future__ import annotations

import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.api.v1.router import api_router
from app.api.v1.training import router as training_router
from app.config import Settings, get_settings
from app.database import Base, dispose_engine, get_engine, get_session_factory
from app.logging_config import configure_logging, get_logger
from app.services.seed import ensure_bootstrap_data

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage startup and shutdown.

    On startup the logging pipeline is configured, the schema is created when
    :attr:`Settings.auto_create_schema` is enabled, and bootstrap data (org,
    admin, 8 built-in templates, training catalogue) is seeded idempotently.

    Args:
        app: The FastAPI application.

    Yields:
        Control back to the server while it runs.
    """
    settings: Settings = get_settings()
    configure_logging(settings)
    logger.info(
        "startup",
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        base_url=settings.base_url,
    )

    if settings.auto_create_schema:
        from app import models  # noqa: F401  (register metadata)

        engine = get_engine()
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        logger.info("schema_ready", tables=len(Base.metadata.tables))

    if settings.auto_seed:
        try:
            async with get_session_factory()() as session:
                summary = await ensure_bootstrap_data(session)
            logger.info("bootstrap_complete", **summary)
        except Exception as exc:  # noqa: BLE001 - never block startup on seeding
            logger.error("bootstrap_failed", error=str(exc))

    yield

    await dispose_engine()
    logger.info("shutdown")


def _resolve_frontend_dist(settings: Settings) -> Path | None:
    """Return the built frontend directory, or ``None`` when it is unavailable.

    Args:
        settings: Active application settings.

    Returns:
        The directory that contains ``index.html``, or ``None`` when the
        dashboard is disabled or has not been built.
    """
    if not settings.serve_frontend:
        return None
    if settings.frontend_dist:
        candidate = Path(settings.frontend_dist)
    else:
        candidate = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    return candidate if (candidate / "index.html").is_file() else None


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built SPA and its hashed assets from the API process.

    The catch-all route is registered last, so every API, tracking, docs and
    health route keeps precedence.  Unknown ``/api`` or ``/training`` paths are
    answered with 404 instead of the SPA shell so clients never receive HTML
    where they expect JSON.

    Args:
        app: The FastAPI application.
        dist: Directory containing ``index.html`` and ``assets/``.
    """
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    index_file = dist / "index.html"
    reserved = {"api", "training", "metrics", "healthz"}

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        """Return static files when present, otherwise the SPA shell."""
        if full_path.split("/", 1)[0] in reserved:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(index_file)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application.

    Args:
        settings: Optional settings override (used by tests).

    Returns:
        A fully configured :class:`FastAPI` instance.
    """
    settings = settings or get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "HUMINT Shield — consent-based security awareness training platform. "
            "Admins run authorized email simulations against company addresses, "
            "track engagement, and deliver immediate micro-learning."
        ),
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )

    # --- request id + access logging ------------------------------------- #
    @app.middleware("http")
    async def add_request_context(request: Request, call_next):  # noqa: ANN001, ANN202
        """Attach a correlation id and log request latency."""
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = str(elapsed_ms)
        if not request.url.path.startswith(("/api/v1/track", "/training", "/metrics")):
            logger.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=elapsed_ms,
            )
        return response

    # --- exception handlers ---------------------------------------------- #
    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Return a normalised 422 payload."""
        return JSONResponse(
            status_code=422,
            content={"detail": "Validation error", "errors": exc.errors()},
        )

    @app.exception_handler(IntegrityError)
    async def integrity_handler(request: Request, exc: IntegrityError) -> JSONResponse:
        """Map database integrity errors to 409."""
        logger.warning("integrity_error", error=str(exc.orig))
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "The request conflicts with an existing record"},
        )

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        """Map unexpected database errors to 500 without leaking internals."""
        logger.error("database_error", error=str(exc))
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "A database error occurred"},
        )

    # --- routers ---------------------------------------------------------- #
    app.include_router(api_router)
    app.include_router(training_router)

    # --- plain health endpoints ------------------------------------------ #
    @app.get("/healthz", tags=["health"], include_in_schema=False)
    async def healthz() -> dict:
        """Liveness probe."""
        return {"status": "ok", "version": settings.app_version}

    frontend_dist = _resolve_frontend_dist(settings)

    @app.get("/", tags=["health"], include_in_schema=False, response_model=None)
    async def root() -> dict | FileResponse:
        """Serve the dashboard when built, otherwise a JSON service banner."""
        if frontend_dist is not None:
            return FileResponse(frontend_dist / "index.html")
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": "/api/docs",
            "health": "/healthz",
        }

    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    if frontend_dist is not None:
        _mount_frontend(app, frontend_dist)
        logger.info("frontend_served", directory=str(frontend_dist))

    return app


app = create_app()
