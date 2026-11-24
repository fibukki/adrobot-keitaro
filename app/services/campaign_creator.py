"""Creates a campaign with a geo-redirect stream and an offer stream, atomically.

Keitaro has no transactions, so atomicity is emulated: campaign -> geo stream ->
offer stream -> order check, and if any step after the campaign fails, the campaign
is deleted (DELETE /campaigns/{id} removes its streams too).
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import ValidationFailed
from app.keitaro.client import KeitaroClient
from app.keitaro.errors import KeitaroError
from app.keitaro.schemas import (
    Campaign,
    CampaignCreate,
    Domain,
    Stream,
    StreamCreate,
    StreamFilter,
)
from app.models import Campaign as CampaignRecord
from app.services import audit
from app.services.countries import is_country_code
from app.services.offers_catalog import OffersCatalog
from app.services.references import ReferenceCache, References

logger = logging.getLogger(__name__)

GEO_STREAM_POSITION = 1
OFFER_STREAM_POSITION = 2


class CampaignRequest(BaseModel):
    """Validated input of the creation form / API."""

    name: str = Field(min_length=1, max_length=255)
    geo: list[str] = Field(min_length=1)
    offer_id: int = Field(gt=0)
    domain_id: int = Field(gt=0)
    group_id: int = Field(gt=0)
    traffic_source_id: int = Field(gt=0)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("geo")
    @classmethod
    def _validate_geo(cls, value: list[str]) -> list[str]:
        codes: list[str] = []
        for raw in value:
            code = raw.strip().upper()
            if not is_country_code(code):
                raise ValueError(f"{raw!r} is not an ISO 3166-1 alpha-2 country code")
            if code not in codes:
                codes.append(code)
        if not codes:
            raise ValueError("select at least one country")
        return codes

    @classmethod
    def build(cls, **data: Any) -> "CampaignRequest":
        """Validate, turning pydantic errors into a message fit for the user."""
        try:
            return cls(**data)
        except ValidationError as exc:
            raise ValidationFailed(_format_errors(exc)) from exc


@dataclass
class CreatedCampaign:
    record: CampaignRecord
    campaign: Campaign
    streams: list[Stream]
    # Settings we sent that Keitaro did not apply (it silently ignored them).
    ignored_fields: dict[str, object] = field(default_factory=dict)


class CampaignCreationFailed(KeitaroError):
    """Creation failed; the partially created campaign was rolled back (or not)."""


class CampaignCreator:
    def __init__(
        self,
        *,
        session: AsyncSession,
        client: KeitaroClient,
        offers: OffersCatalog,
        references: ReferenceCache,
        settings: Settings,
    ) -> None:
        self._session = session
        self._client = client
        self._offers = offers
        self._references = references
        self._settings = settings

    async def create(self, request: CampaignRequest, *, actor: str) -> CreatedCampaign:
        refs = await self._validate(request)

        payload = CampaignCreate(
            name=request.name,
            domain_id=request.domain_id,
            group_id=request.group_id,
            traffic_source_id=request.traffic_source_id,
        )
        campaign = await self._client.create_campaign(payload)
        logger.info("created campaign %s (%s)", campaign.id, campaign.name)

        try:
            streams = await self._create_streams(campaign.id, request)
            record = self._store(campaign, streams, request, refs.domain(request.domain_id), actor)
            await self._session.commit()
        except BaseException as exc:
            # Also on cancellation or a DB failure: never leave a half-built campaign behind.
            await self._session.rollback()
            await asyncio.shield(self._rollback(campaign, request, exc, actor=actor))
            if isinstance(exc, KeitaroError):
                raise CampaignCreationFailed(
                    f"Campaign was not created: {exc.message}. Changes were rolled back."
                ) from exc
            raise

        ignored = _ignored_fields(payload, campaign)
        if ignored:
            logger.warning(
                "Keitaro ignored campaign fields %s for campaign %s", ignored, campaign.id
            )
        return CreatedCampaign(
            record=record, campaign=campaign, streams=streams, ignored_fields=ignored
        )

    def _store(
        self,
        campaign: Campaign,
        streams: list[Stream],
        request: CampaignRequest,
        domain: Domain | None,
        actor: str,
    ) -> CampaignRecord:
        record = CampaignRecord(
            keitaro_id=campaign.id,
            name=campaign.name,
            alias=campaign.alias,
            url=campaign_url(domain, campaign.alias),
            geo=request.geo,
            offer_id=request.offer_id,
            domain_id=request.domain_id,
            group_id=request.group_id,
            traffic_source_id=request.traffic_source_id,
            status="created",
        )
        self._session.add(record)
        audit.record(
            self._session,
            actor=actor,
            action="campaign.create",
            entity_type="campaign",
            entity_id=campaign.id,
            after={
                "request": request.model_dump(),
                "campaign": campaign.model_dump(mode="json"),
                "streams": [s.model_dump(mode="json", by_alias=True) for s in streams],
            },
        )
        return record

    async def _validate(self, request: CampaignRequest) -> References:
        refs = await self._references.get()
        errors = []
        if refs.domain(request.domain_id) is None:
            errors.append(f"unknown domain #{request.domain_id}")
        if not refs.has_group(request.group_id):
            errors.append(f"unknown campaign group #{request.group_id}")
        if not refs.has_traffic_source(request.traffic_source_id):
            errors.append(f"unknown traffic source #{request.traffic_source_id}")
        if await self._offers.get(request.offer_id) is None:
            errors.append(f"unknown offer #{request.offer_id}")
        if errors:
            message = "; ".join(errors)
            raise ValidationFailed(message[0].upper() + message[1:])
        return refs

    async def _create_streams(self, campaign_id: int, request: CampaignRequest) -> list[Stream]:
        geo_stream = await self._client.create_stream(
            StreamCreate(
                campaign_id=campaign_id,
                name=f"Geo {' '.join(request.geo)}",
                type="regular",
                schema="redirect",
                position=GEO_STREAM_POSITION,
                action_type="http",
                action_payload=self._settings.geo_redirect_url,
                filters=[StreamFilter(name="country", mode="accept", payload=request.geo)],
            )
        )
        offer_stream = await self._client.create_stream(
            StreamCreate(
                campaign_id=campaign_id,
                name="Offers",
                type="default",
                schema="landings",
                position=OFFER_STREAM_POSITION,
                offers=[{"offer_id": request.offer_id, "share": 100, "state": "active"}],
            )
        )

        # Read back what Keitaro actually stored: the geo stream must be evaluated first.
        streams = await self._client.list_campaign_streams(campaign_id)
        order = [s.id for s in streams]
        if order[:2] != [geo_stream.id, offer_stream.id]:
            raise KeitaroError(
                f"unexpected stream order {order}, expected geo stream {geo_stream.id} first"
            )
        return streams

    async def _rollback(
        self, campaign: Campaign, request: CampaignRequest, exc: BaseException, *, actor: str
    ) -> None:
        logger.warning("rolling back campaign %s after error: %r", campaign.id, exc)
        rollback_error: str | None = None
        try:
            await self._client.delete_campaign(campaign.id)
        except KeitaroError as delete_exc:
            rollback_error = delete_exc.message
            logger.error(
                "ROLLBACK FAILED: campaign %s is left half-built in Keitaro: %s",
                campaign.id,
                delete_exc.message,
            )

        if rollback_error is not None:
            # Remember the orphan so it can be found and cleaned up.
            self._session.add(
                CampaignRecord(
                    keitaro_id=campaign.id,
                    name=campaign.name,
                    alias=campaign.alias,
                    geo=request.geo,
                    offer_id=request.offer_id,
                    domain_id=request.domain_id,
                    group_id=request.group_id,
                    traffic_source_id=request.traffic_source_id,
                    status="rollback_failed",
                )
            )
        audit.record(
            self._session,
            actor=actor,
            action="campaign.create_failed",
            entity_type="campaign",
            entity_id=campaign.id,
            before=None,
            after={"request": request.model_dump(), "rolled_back": rollback_error is None},
            error=str(getattr(exc, "message", None) or repr(exc))
            + (f"; rollback failed: {rollback_error}" if rollback_error else ""),
        )
        try:
            await self._session.commit()
        except Exception:
            # The original error matters more; do not mask it with a DB failure.
            logger.exception("could not store the failed creation of campaign %s", campaign.id)
            await self._session.rollback()


def campaign_url(domain: Domain | None, alias: str | None) -> str | None:
    """Public URL of a campaign: <scheme>://<domain>/<alias>."""
    if domain is None or not alias:
        return None
    scheme = "http" if domain.is_ssl is False else "https"
    return f"{scheme}://{domain.name.strip('/')}/{alias}"


def _ignored_fields(sent: CampaignCreate, got: Campaign) -> dict[str, object]:
    ignored: dict[str, object] = {}
    returned = got.model_dump()
    for key, value in sent.to_api().items():
        if key in returned and returned[key] is not None and returned[key] != value:
            ignored[key] = {"sent": value, "stored": returned[key]}
    return ignored


_FIELD_LABELS = {
    "name": "Name",
    "geo": "Geo",
    "offer_id": "Offer",
    "domain_id": "Domain",
    "group_id": "Group",
    "traffic_source_id": "Traffic source",
}


def _format_errors(exc: ValidationError) -> str:
    messages = []
    for error in exc.errors():
        field_name = str(error["loc"][0]) if error["loc"] else ""
        message = error["msg"].removeprefix("Value error, ")
        messages.append(f"{_FIELD_LABELS.get(field_name, field_name)}: {message}")
    return "; ".join(messages)
