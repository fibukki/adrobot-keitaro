import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import Base, make_engine, make_sessionmaker
from app.keitaro.client import KeitaroClient
from app.main import create_app
from app.services.offers_catalog import OffersCatalog
from app.services.references import ReferenceCache
from tests import factories as f

KEITARO_URL = "https://keitaro.test/admin_api/v1"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,  # never pick up the developer's .env in tests
        keitaro_url=KEITARO_URL,
        keitaro_api_key="test-key",
        keitaro_admin_url="https://keitaro.test/admin",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        default_domain_id=f.DOMAIN_ID,
        default_group_id=f.GROUP_ID,
        default_source_id=f.SOURCE_ID,
    )


@pytest.fixture
def keitaro() -> respx.MockRouter:
    """Mock of the Keitaro API. Any request that is not explicitly mocked fails the test."""
    with respx.mock(base_url=KEITARO_URL, assert_all_called=False) as router:
        yield router


@pytest.fixture
async def session(settings) -> AsyncIterator[AsyncSession]:
    engine = make_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with make_sessionmaker(engine)() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def client(keitaro) -> AsyncIterator[KeitaroClient]:
    http = KeitaroClient.build_http(KEITARO_URL, "test-key", timeout=5)
    yield KeitaroClient(http)
    await http.aclose()


@pytest.fixture
def offers(session, client) -> OffersCatalog:
    return OffersCatalog(session, client, ttl_seconds=3600, refresh_lock=asyncio.Lock())


@pytest.fixture
def references(client) -> ReferenceCache:
    return ReferenceCache(client, ttl_seconds=3600)


@pytest.fixture
def mock_references(keitaro) -> dict[str, respx.Route]:
    return {
        "domains": keitaro.get("/domains").respond(json=f.DOMAINS),
        "groups": keitaro.get("/groups", params={"type": "campaigns"}).respond(json=f.GROUPS),
        "sources": keitaro.get("/traffic_sources").respond(json=f.SOURCES),
    }


@pytest.fixture
def mock_offers(keitaro) -> respx.Route:
    return keitaro.get("/offers").respond(json=f.OFFERS)


@pytest.fixture
async def web(settings, keitaro) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP client for the full app (lifespan included) on a fresh SQLite DB."""
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with app.state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://app.test") as http:
            yield http
