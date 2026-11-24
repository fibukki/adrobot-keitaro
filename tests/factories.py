"""Keitaro API payloads for tests, shaped like the real stand responses (scripts/samples)."""

from typing import Any

DOMAIN_ID = 1813
GROUP_ID = 10332
SOURCE_ID = 836

DOMAINS = [
    {"id": DOMAIN_ID, "name": "tracker.example.com", "is_ssl": True, "network_status": "active"},
    {"id": 1900, "name": "other.example.com", "is_ssl": False, "state": "active"},
]
GROUPS = [{"id": GROUP_ID, "name": "FORTESTS", "type": "campaigns", "position": 1}]
SOURCES = [{"id": SOURCE_ID, "name": "FORTESTS", "state": "active"}]

OFFERS = [
    {"id": 3749, "name": "Miaflow [BEAUTY-RO-BE_0009]", "state": "active", "payout_value": 10},
    {"id": 18001, "name": "Keto Slim [DIET-MX]", "state": "active"},
    {"id": 18002, "name": "Hair Pro [BEAUTY-AU]", "state": "active"},
    {"id": 18003, "name": "Joint Flex [HEALTH-RO]", "state": "disabled"},
    {"id": 374, "name": "Old offer 100%_promo", "state": "active"},
    # Real stand offers carry their id at the start of the name.
    {"id": 18004, "name": "18004 Hepatix [PROSTATE-DE] [quiz de -] ADNOVA v3", "state": "active"},
]


def campaign(campaign_id: int = 501, **overrides: Any) -> dict[str, Any]:
    data = {
        "id": campaign_id,
        "alias": "aBcD12",
        "name": "Test campaign",
        "type": "position",
        "state": "active",
        "cost_type": "CPC",
        "cost_value": 0,
        "cost_auto": True,
        "group_id": GROUP_ID,
        "traffic_source_id": SOURCE_ID,
        "domain_id": DOMAIN_ID,
        "token": "secret-token",
        "updated_at": "2026-11-24 10:00:00",
    }
    return data | overrides


def stream_offer(offer_id: int, share: int, **overrides: Any) -> dict[str, Any]:
    data = {
        "id": offer_id * 10,
        "stream_id": 0,
        "offer_id": offer_id,
        "state": "active",
        "share": share,
        "created_at": "2026-11-24 10:00:00",
        "updated_at": "2026-11-24 10:00:00",
    }
    return data | overrides


def stream(
    stream_id: int,
    campaign_id: int = 501,
    *,
    position: int = 1,
    type_: str = "default",
    schema: str = "landings",
    offers: list[dict[str, Any]] | None = None,
    filters: list[dict[str, Any]] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    data = {
        "id": stream_id,
        "campaign_id": campaign_id,
        "type": type_,
        "name": f"Stream {stream_id}",
        "position": position,
        "weight": 0,
        "action_options": None,
        "comments": None,
        "state": "active",
        "action_type": "http" if schema == "redirect" else None,
        "action_payload": "https://google.com" if schema == "redirect" else None,
        "schema": schema,
        "collect_clicks": True,
        "filter_or": False,
        "filters": filters or [],
        "landings": [],
        "offers": [o | {"stream_id": stream_id} for o in (offers or [])],
    }
    return data | overrides
