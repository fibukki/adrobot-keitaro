"""Pydantic models for Keitaro Admin API payloads.

Response models describe only the fields this service uses; everything else is
ignored (`extra="ignore"`), so new fields in Keitaro do not break us.
"""

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field


class KeitaroModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


# --- references ----------------------------------------------------------------------


class Offer(KeitaroModel):
    id: int
    name: str
    state: str | None = None


class Domain(KeitaroModel):
    id: int
    name: str
    is_ssl: bool | None = None
    state: str | None = None


class CampaignGroup(KeitaroModel):
    id: int
    name: str


class TrafficSource(KeitaroModel):
    id: int
    name: str
    state: str | None = None


# --- campaigns -----------------------------------------------------------------------


class Campaign(KeitaroModel):
    id: int
    name: str
    alias: str | None = None
    type: str | None = None
    state: str | None = None
    cost_type: str | None = None
    cost_value: float | None = None
    cost_auto: bool | None = None
    domain_id: int | None = None
    group_id: int | None = None
    traffic_source_id: int | None = None
    updated_at: str | None = None


class CampaignCreate(KeitaroModel):
    """POST /campaigns body. Field names follow the Keitaro Admin API docs."""

    name: str
    type: Literal["position", "weight"] = "position"  # stream rotation: by position
    cost_type: str = "CPC"
    cost_auto: bool = True  # take cost from the `cost` parameter of the click
    domain_id: int | None = None
    group_id: int | None = None
    traffic_source_id: int | None = None

    def to_api(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


# --- streams -------------------------------------------------------------------------


class StreamFilter(KeitaroModel):
    name: str
    mode: str
    payload: Any = None


class StreamOffer(BaseModel):
    """An offer attached to a stream.

    Unlike other models this keeps unknown fields: `PUT /streams/{id}` replaces the
    whole `offers` collection, so whatever Keitaro returned for an offer has to be
    sent back unchanged, except for the share we recalculate.
    """

    model_config = ConfigDict(extra="allow")

    offer_id: int
    share: int = 0
    state: str | None = None

    # Server-managed fields that must not be echoed back on PUT.
    READ_ONLY_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"id", "stream_id", "created_at", "updated_at"}
    )

    def to_api(self, *, share: int) -> dict[str, Any]:
        data = self.model_dump(exclude_none=True)
        for key in self.READ_ONLY_FIELDS:
            data.pop(key, None)
        data["share"] = share
        return data


class Stream(KeitaroModel):
    id: int
    campaign_id: int
    name: str | None = None
    type: str | None = None
    schema_: str | None = Field(default=None, alias="schema")
    position: int | None = None
    state: str | None = None
    action_type: str | None = None
    action_payload: Any = None
    filters: list[StreamFilter] = Field(default_factory=list)
    offers: list[StreamOffer] = Field(default_factory=list)

    @property
    def uses_offers(self) -> bool:
        return self.schema_ == "landings"


class StreamCreate(KeitaroModel):
    campaign_id: int
    name: str
    type: Literal["regular", "forced", "default"]
    schema_: Literal["redirect", "landings", "action"] = Field(alias="schema")
    position: int | None = None
    action_type: str | None = None
    action_payload: str | None = None
    filters: list[StreamFilter] | None = None
    offers: list[dict[str, Any]] | None = None

    def to_api(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=True)
