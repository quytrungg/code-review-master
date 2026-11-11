from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router
from app.core.config import get_settings
from app.core.crypto import CredentialError
from app.db.encryption import log_startup_report
from app.db.init_db import fail_orphaned_reviews, init_db
from app.services import watch_service

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
# In-process Alembic runs reset the root logger to WARN (alembic.ini); keep our own namespaces
# at INFO so startup and credential reports are visible.
logging.getLogger("app").setLevel(logging.INFO)
logger = logging.getLogger(__name__)


class SPAStaticFiles(StaticFiles):
    """Static files with a history fallback for client-side routes.

    React Router owns paths like `/reviews/12`; only requests that look like a
    file (an extension in the last segment) are allowed to 404.
    """

    async def get_response(self, path: str, scope):
        is_client_route = "." not in Path(path).name
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and is_client_route:
                return await super().get_response("index.html", scope)
            raise
        if response.status_code == 404 and is_client_route:
            return await super().get_response("index.html", scope)
        return response


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    logger.info("Database: %s", settings.resolved_database_url)
    logger.info("Skills: %s", settings.resolved_skills_dir)
    if settings.serverless:
        # A release step runs migrations, and another instance may own a `running` review, so
        # startup must neither upgrade the schema nor sweep rows. Reads mark stale ones instead.
        # The watch loop is replaced by POST /api/watches/tick on a schedule.
        logger.info("Serverless mode: startup migrations and the orphan sweep are disabled")
    else:
        init_db()
        fail_orphaned_reviews()
        watch_service.start_loop()
    log_startup_report()
    try:
        yield
    finally:
        # Await the cancellation so shutdown does not leave a pending task behind.
        loop = watch_service.stop_loop()
        if loop is not None:
            with suppress(asyncio.CancelledError):
                await loop


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="AI Code Review Assistant",
        version="0.1.0",
        description="Local-first interactive code review over GitHub pull requests.",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(api_router, prefix="/api")

    @application.exception_handler(CredentialError)
    async def credential_error(_: Request, exc: CredentialError) -> JSONResponse:
        # A configuration state the operator can fix, not a bug: keep it a 503 so the UI can
        # explain itself. The detail never carries a secret or ciphertext.
        logger.error("Credential error: %s", exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @application.get("/api/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # Mounted last so /api, /docs and /openapi.json keep their handlers.
    frontend_dir = settings.resolved_frontend_dir
    if frontend_dir is not None:
        if frontend_dir.is_dir():
            application.mount("/", SPAStaticFiles(directory=frontend_dir, html=True), name="ui")
        else:
            logger.warning("FRONTEND_DIR %s is not a directory; serving the API only", frontend_dir)

    return application


app = create_app()
