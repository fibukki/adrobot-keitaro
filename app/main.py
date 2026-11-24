import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.config import Settings, get_settings
from app.db import make_engine, make_sessionmaker
from app.errors import AppError
from app.keitaro.client import KeitaroClient
from app.services.references import ReferenceCache
from app.web.routes import router as web_router
from app.web.templating import templates

STATIC_DIR = Path(__file__).parent / "web" / "static"

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(settings.database_url)
        http = KeitaroClient.build_http(
            settings.keitaro_url,
            settings.keitaro_api_key.get_secret_value(),
            settings.keitaro_timeout,
        )
        keitaro = KeitaroClient(http)
        app.state.settings = settings
        app.state.engine = engine
        app.state.sessionmaker = make_sessionmaker(engine)
        app.state.keitaro = keitaro
        app.state.references = ReferenceCache(keitaro, settings.reference_cache_ttl)
        app.state.offers_refresh_lock = asyncio.Lock()
        try:
            yield
        finally:
            await http.aclose()
            await engine.dispose()

    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx logs every request at INFO, our client already does it with timings.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    app = FastAPI(title="Adrobot · Keitaro campaign tool", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(api_router)
    app.include_router(web_router)

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> Response:
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": exc.message}, status_code=exc.status_code)
        template = "partials/error.html" if request.headers.get("hx-request") else "error.html"
        return templates.TemplateResponse(
            request, template, {"message": exc.message}, status_code=exc.status_code
        )

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
