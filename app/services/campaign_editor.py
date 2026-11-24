"""Editing offers of an existing campaign's streams.

Every change is read-modify-write against Keitaro: the stream is re-read right
before the PUT (so concurrent edits made in the admin are not lost), all offer
fields except `share` are sent back as Keitaro returned them, and shares are
redistributed evenly so they always sum to 100. What we show afterwards is the
PUT response, i.e. the state Keitaro actually stored.
"""

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import Conflict, NotFound, ValidationFailed
from app.keitaro.client import KeitaroClient
from app.keitaro.schemas import Campaign, Stream, StreamOffer
from app.services import audit
from app.services.offers_catalog import OffersCatalog
from app.services.shares import distribute_shares

logger = logging.getLogger(__name__)


@dataclass
class CampaignView:
    campaign: Campaign
    streams: list[Stream]
    offer_names: dict[int, str]


class CampaignEditor:
    def __init__(
        self, *, session: AsyncSession, client: KeitaroClient, offers: OffersCatalog
    ) -> None:
        self._session = session
        self._client = client
        self._offers = offers

    async def view(self, campaign_id: int) -> CampaignView:
        campaign = await self._client.get_campaign(campaign_id)
        streams = await self._client.list_campaign_streams(campaign_id)
        return CampaignView(campaign, streams, await self.offer_names(streams))

    async def offer_names(self, streams: list[Stream]) -> dict[int, str]:
        return await self._offers.names(o.offer_id for s in streams for o in s.offers)

    async def add_offer(
        self, *, campaign_id: int, stream_id: int, offer_id: int, actor: str
    ) -> Stream:
        if await self._offers.get(offer_id) is None:
            raise NotFound(f"Offer #{offer_id} does not exist")
        stream = await self._load_stream(campaign_id, stream_id)
        if any(o.offer_id == offer_id for o in stream.offers):
            raise Conflict(f"Offer #{offer_id} is already in stream “{stream.name}”")

        new_offer = StreamOffer(offer_id=offer_id, state="active")
        return await self._save_offers(
            stream, [*stream.offers, new_offer], action="stream.offer_add", actor=actor
        )

    async def remove_offer(
        self, *, campaign_id: int, stream_id: int, offer_id: int, actor: str
    ) -> Stream:
        stream = await self._load_stream(campaign_id, stream_id)
        remaining = [o for o in stream.offers if o.offer_id != offer_id]
        if len(remaining) == len(stream.offers):
            raise NotFound(f"Offer #{offer_id} is not in stream “{stream.name}”")
        if not remaining:
            # A landings stream without offers sends traffic nowhere.
            raise ValidationFailed(
                "Cannot remove the last offer of a stream: add another offer first"
            )
        return await self._save_offers(stream, remaining, action="stream.offer_remove", actor=actor)

    async def _load_stream(self, campaign_id: int, stream_id: int) -> Stream:
        stream = await self._client.get_stream(stream_id)
        if stream.campaign_id != campaign_id:
            raise NotFound(f"Stream #{stream_id} does not belong to campaign #{campaign_id}")
        if not stream.uses_offers:
            raise ValidationFailed(f"Stream “{stream.name}” does not use offers")
        return stream

    async def _save_offers(
        self, stream: Stream, offers: list[StreamOffer], *, action: str, actor: str
    ) -> Stream:
        shares = distribute_shares(len(offers))
        payload = [offer.to_api(share=share) for offer, share in zip(offers, shares, strict=True)]
        updated = await self._client.update_stream(stream.id, {"offers": payload})

        total = sum(o.share for o in updated.offers)
        if updated.offers and total != 100:
            logger.error("stream %s: Keitaro stored shares summing to %s", stream.id, total)

        audit.record(
            self._session,
            actor=actor,
            action=action,
            entity_type="stream",
            entity_id=stream.id,
            before=[o.model_dump(mode="json") for o in stream.offers],
            after=[o.model_dump(mode="json") for o in updated.offers],
        )
        await self._session.commit()
        return updated
