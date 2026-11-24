"""FastAPI dependencies: per-request DB session and services built on app state."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.keitaro.client import KeitaroClient
from app.services.campaign_creator import CampaignCreator
from app.services.campaign_editor import CampaignEditor
from app.services.offers_catalog import OffersCatalog
from app.services.references import ReferenceCache


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_keitaro(request: Request) -> KeitaroClient:
    return request.app.state.keitaro


def get_references(request: Request) -> ReferenceCache:
    return request.app.state.references


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def get_actor(request: Request) -> str:
    """Who is making the change. There is no auth in this service; an auth proxy in
    front of it can pass the user in `X-User`, otherwise the client address is used."""
    user = request.headers.get("x-user")
    if user:
        return user[:128]
    return f"anonymous@{request.client.host if request.client else 'unknown'}"


SettingsDep = Annotated[Settings, Depends(get_settings)]
KeitaroDep = Annotated[KeitaroClient, Depends(get_keitaro)]
ReferencesDep = Annotated[ReferenceCache, Depends(get_references)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ActorDep = Annotated[str, Depends(get_actor)]


def get_offers(
    request: Request, session: SessionDep, client: KeitaroDep, settings: SettingsDep
) -> OffersCatalog:
    return OffersCatalog(
        session,
        client,
        ttl_seconds=settings.offers_cache_ttl,
        refresh_lock=request.app.state.offers_refresh_lock,
    )


OffersDep = Annotated[OffersCatalog, Depends(get_offers)]


def get_creator(
    session: SessionDep,
    client: KeitaroDep,
    offers: OffersDep,
    references: ReferencesDep,
    settings: SettingsDep,
) -> CampaignCreator:
    return CampaignCreator(
        session=session, client=client, offers=offers, references=references, settings=settings
    )


def get_editor(session: SessionDep, client: KeitaroDep, offers: OffersDep) -> CampaignEditor:
    return CampaignEditor(session=session, client=client, offers=offers)


CreatorDep = Annotated[CampaignCreator, Depends(get_creator)]
EditorDep = Annotated[CampaignEditor, Depends(get_editor)]
