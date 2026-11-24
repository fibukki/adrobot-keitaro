import json

import httpx
import pytest
from sqlalchemy import select

from app.errors import ValidationFailed
from app.models import AuditLog, Campaign
from app.services.campaign_creator import (
    CampaignCreationFailed,
    CampaignCreator,
    CampaignRequest,
)
from tests import factories as f

CAMPAIGN_ID = 501
GEO_STREAM_ID = 9001
OFFER_STREAM_ID = 9002


@pytest.fixture
def creator(session, client, offers, references, settings) -> CampaignCreator:
    return CampaignCreator(
        session=session, client=client, offers=offers, references=references, settings=settings
    )


def make_request(**overrides) -> CampaignRequest:
    data = {
        "name": "  Summer MX  ",
        "geo": ["mx", "AU", "MX", "ro"],
        "offer_id": 18001,
        "domain_id": f.DOMAIN_ID,
        "group_id": f.GROUP_ID,
        "traffic_source_id": f.SOURCE_ID,
    }
    return CampaignRequest.build(**(data | overrides))


GEO_STREAM = f.stream(
    GEO_STREAM_ID,
    CAMPAIGN_ID,
    position=1,
    type_="regular",
    schema="redirect",
    filters=[{"name": "country", "mode": "accept", "payload": ["MX", "AU", "RO"]}],
)
OFFER_STREAM = f.stream(
    OFFER_STREAM_ID, CAMPAIGN_ID, position=2, offers=[f.stream_offer(18001, 100)]
)


@pytest.fixture
def happy_path(keitaro, mock_references, mock_offers):
    stream_responses = iter([GEO_STREAM, OFFER_STREAM])
    return {
        "create": keitaro.post("/campaigns").respond(
            json=f.campaign(CAMPAIGN_ID, name="Summer MX")
        ),
        "streams": keitaro.post("/streams").mock(
            side_effect=lambda request: httpx.Response(200, json=next(stream_responses))
        ),
        "list": keitaro.get(f"/campaigns/{CAMPAIGN_ID}/streams").respond(
            json=[GEO_STREAM, OFFER_STREAM]
        ),
        "delete": keitaro.delete(f"/campaigns/{CAMPAIGN_ID}").respond(json={"success": True}),
    }


def test_request_normalises_geo_and_name() -> None:
    request = make_request()
    assert request.name == "Summer MX"
    assert request.geo == ["MX", "AU", "RO"]


@pytest.mark.parametrize("geo", [[], ["XX"], ["MEX"], ["M1"], [" "]])
def test_request_rejects_bad_geo(geo) -> None:
    with pytest.raises(ValidationFailed, match="Geo"):
        make_request(geo=geo)


def test_request_rejects_blank_name() -> None:
    with pytest.raises(ValidationFailed, match="Name"):
        make_request(name="   ")


async def test_creates_campaign_then_geo_stream_then_offer_stream(
    creator, session, happy_path, keitaro
) -> None:
    result = await creator.create(make_request(), actor="tester")

    campaign_body = json.loads(happy_path["create"].calls.last.request.content)
    assert campaign_body == {
        "name": "Summer MX",
        "type": "position",
        "cost_type": "CPC",
        "cost_auto": True,
        "domain_id": f.DOMAIN_ID,
        "group_id": f.GROUP_ID,
        "traffic_source_id": f.SOURCE_ID,
    }
    geo_body, offer_body = (json.loads(c.request.content) for c in happy_path["streams"].calls)
    assert geo_body == {
        "campaign_id": CAMPAIGN_ID,
        "name": "Geo MX AU RO",
        "type": "regular",
        "schema": "redirect",
        "position": 1,
        "action_type": "http",
        "action_payload": "https://google.com",
        "filters": [{"name": "country", "mode": "accept", "payload": ["MX", "AU", "RO"]}],
    }
    assert offer_body == {
        "campaign_id": CAMPAIGN_ID,
        "name": "Offers",
        "type": "default",
        "schema": "landings",
        "position": 2,
        "offers": [{"offer_id": 18001, "share": 100, "state": "active"}],
    }
    # Exactly: create campaign, two streams, read back the order. No rollback.
    assert [c.request.method + " " + c.request.url.path for c in keitaro.calls][-4:] == [
        "POST /admin_api/v1/campaigns",
        "POST /admin_api/v1/streams",
        "POST /admin_api/v1/streams",
        f"GET /admin_api/v1/campaigns/{CAMPAIGN_ID}/streams",
    ]
    assert not happy_path["delete"].called

    assert result.campaign.id == CAMPAIGN_ID
    assert result.ignored_fields == {}
    record = await session.scalar(select(Campaign))
    assert record.keitaro_id == CAMPAIGN_ID
    assert record.geo == ["MX", "AU", "RO"]
    assert record.status == "created"
    assert record.url == "https://tracker.example.com/aBcD12"
    entry = await session.scalar(select(AuditLog))
    assert (entry.action, entry.actor, entry.entity_id) == ("campaign.create", "tester", 501)


async def test_failed_offer_stream_rolls_back_campaign(
    creator, session, happy_path, keitaro
) -> None:
    happy_path["streams"].side_effect = [
        httpx.Response(200, json=GEO_STREAM),
        httpx.Response(400, json={"error": "Offer is invalid"}),
    ]

    with pytest.raises(CampaignCreationFailed, match=r"Offer is invalid.*rolled back"):
        await creator.create(make_request(), actor="tester")

    assert happy_path["delete"].call_count == 1
    assert await session.scalar(select(Campaign)) is None
    entry = await session.scalar(select(AuditLog))
    assert entry.action == "campaign.create_failed"
    assert entry.after["rolled_back"] is True
    assert "Offer is invalid" in entry.error


async def test_wrong_stream_order_rolls_back(creator, happy_path) -> None:
    happy_path["list"].respond(json=[OFFER_STREAM, GEO_STREAM])

    with pytest.raises(CampaignCreationFailed, match="stream order"):
        await creator.create(make_request(), actor="tester")

    assert happy_path["delete"].call_count == 1


async def test_failed_rollback_is_recorded_for_cleanup(creator, session, happy_path) -> None:
    happy_path["streams"].side_effect = httpx.ReadTimeout("slow")
    happy_path["delete"].respond(500, json={"error": "boom"})

    with pytest.raises(CampaignCreationFailed):
        await creator.create(make_request(), actor="tester")

    record = await session.scalar(select(Campaign))
    assert (record.keitaro_id, record.status) == (CAMPAIGN_ID, "rollback_failed")
    entry = await session.scalar(select(AuditLog))
    assert entry.after["rolled_back"] is False
    assert "rollback failed" in entry.error


async def test_unknown_references_are_rejected_before_any_write(
    creator, happy_path, mock_references
) -> None:
    with pytest.raises(ValidationFailed, match=r"Unknown domain #1; unknown offer #424242"):
        await creator.create(make_request(domain_id=1, offer_id=424242), actor="tester")

    assert not happy_path["create"].called


async def test_ignored_fields_are_reported(creator, happy_path) -> None:
    happy_path["create"].respond(
        json=f.campaign(CAMPAIGN_ID, name="Summer MX", cost_auto=False, type="weight")
    )

    result = await creator.create(make_request(), actor="tester")

    assert set(result.ignored_fields) == {"cost_auto", "type"}
