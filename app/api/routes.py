"""JSON API. The web UI uses /api/offers for autocomplete; the rest mirrors the UI
actions for scripting and integration."""

from typing import Any

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from app.deps import ActorDep, CreatorDep, EditorDep, OffersDep, SettingsDep
from app.keitaro.schemas import Stream
from app.models import OfferCache
from app.services.campaign_creator import CampaignRequest
from app.services.offers_catalog import SEARCH_LIMIT

router = APIRouter(prefix="/api", tags=["api"])


class OfferOut(BaseModel):
    id: int
    name: str
    state: str | None
    label: str

    @classmethod
    def of(cls, offer: OfferCache) -> "OfferOut":
        return cls(id=offer.id, name=offer.name, state=offer.state, label=offer.label)


class CampaignIn(BaseModel):
    name: str
    geo: list[str]
    offer_id: int
    domain_id: int | None = Field(default=None, description="defaults to DEFAULT_DOMAIN_ID")
    group_id: int | None = Field(default=None, description="defaults to DEFAULT_GROUP_ID")
    traffic_source_id: int | None = Field(default=None, description="defaults to DEFAULT_SOURCE_ID")


class OfferIn(BaseModel):
    offer_id: int = Field(gt=0)


@router.get("/offers", response_model=list[OfferOut])
async def search_offers(
    offers: OffersDep, q: str = "", limit: int = Query(SEARCH_LIMIT, ge=1, le=SEARCH_LIMIT)
) -> list[OfferOut]:
    return [OfferOut.of(o) for o in await offers.search(q, limit)]


@router.post("/offers/refresh")
async def refresh_offers(offers: OffersDep) -> dict[str, int]:
    return {"count": await offers.refresh()}


@router.post("/campaigns", status_code=status.HTTP_201_CREATED)
async def create_campaign(
    body: CampaignIn, creator: CreatorDep, settings: SettingsDep, actor: ActorDep
) -> dict[str, Any]:
    request = CampaignRequest.build(
        name=body.name,
        geo=body.geo,
        offer_id=body.offer_id,
        domain_id=body.domain_id or settings.default_domain_id,
        group_id=body.group_id or settings.default_group_id,
        traffic_source_id=body.traffic_source_id or settings.default_source_id,
    )
    created = await creator.create(request, actor=actor)
    return {
        "id": created.campaign.id,
        "name": created.campaign.name,
        "alias": created.campaign.alias,
        "url": created.record.url,
        "admin_url": settings.campaign_admin_link(created.campaign.id),
        "streams": [_stream_out(s, {}) for s in created.streams],
        "ignored_fields": created.ignored_fields,
    }


@router.get("/campaigns/{campaign_id}")
async def get_campaign(campaign_id: int, editor: EditorDep) -> dict[str, Any]:
    view = await editor.view(campaign_id)
    return {
        "campaign": view.campaign.model_dump(),
        "streams": [_stream_out(s, view.offer_names) for s in view.streams],
    }


@router.post("/campaigns/{campaign_id}/streams/{stream_id}/offers")
async def add_offer(
    campaign_id: int, stream_id: int, body: OfferIn, editor: EditorDep, actor: ActorDep
) -> dict[str, Any]:
    stream = await editor.add_offer(
        campaign_id=campaign_id, stream_id=stream_id, offer_id=body.offer_id, actor=actor
    )
    return _stream_out(stream, await editor.offer_names([stream]))


@router.delete("/campaigns/{campaign_id}/streams/{stream_id}/offers/{offer_id}")
async def remove_offer(
    campaign_id: int, stream_id: int, offer_id: int, editor: EditorDep, actor: ActorDep
) -> dict[str, Any]:
    stream = await editor.remove_offer(
        campaign_id=campaign_id, stream_id=stream_id, offer_id=offer_id, actor=actor
    )
    return _stream_out(stream, await editor.offer_names([stream]))


def _stream_out(stream: Stream, names: dict[int, str]) -> dict[str, Any]:
    data = stream.model_dump(mode="json", by_alias=True, exclude={"offers"})
    data["offers"] = [
        {"offer_id": o.offer_id, "name": names.get(o.offer_id), "share": o.share, "state": o.state}
        for o in stream.offers
    ]
    return data
