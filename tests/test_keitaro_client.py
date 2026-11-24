import json
import logging

import httpx
import pytest

from app.keitaro.errors import KeitaroAPIError, KeitaroError, KeitaroNotFound, KeitaroUnavailable
from app.keitaro.schemas import CampaignCreate, StreamOffer
from tests import factories as f


async def test_sends_api_key_and_parses_campaigns(client, keitaro) -> None:
    route = keitaro.get("/campaigns", params={"offset": 0, "limit": 5}).respond(
        json=[f.campaign(1), f.campaign(2, name="Second")]
    )

    campaigns = await client.list_campaigns(limit=5)

    assert [c.name for c in campaigns] == ["Test campaign", "Second"]
    assert route.calls.last.request.headers["Api-Key"] == "test-key"


async def test_create_campaign_sends_documented_fields(client, keitaro) -> None:
    route = keitaro.post("/campaigns").respond(json=f.campaign(7))

    await client.create_campaign(CampaignCreate(name="X", domain_id=1, group_id=2))

    assert json.loads(route.calls.last.request.content) == {
        "name": "X",
        "type": "position",
        "cost_type": "CPC",
        "cost_auto": True,
        "domain_id": 1,
        "group_id": 2,
    }


async def test_api_error_is_wrapped_and_body_logged(client, keitaro, caplog) -> None:
    keitaro.put("/streams/1").respond(422, json={"error": "Field name is required"})

    with caplog.at_level(logging.WARNING), pytest.raises(KeitaroAPIError) as exc_info:
        await client.update_stream(1, {"offers": []})

    assert exc_info.value.status == 422
    assert "Field name is required" in exc_info.value.message
    assert "Field name is required" in caplog.text  # the stand's error body is logged


async def test_not_found(client, keitaro) -> None:
    keitaro.get("/streams/9").respond(404, json={"error": "Not found"})

    with pytest.raises(KeitaroNotFound):
        await client.get_stream(9)


async def test_timeout_is_reported_as_unavailable(client, keitaro) -> None:
    keitaro.get("/offers").mock(side_effect=httpx.ReadTimeout("slow"))

    with pytest.raises(KeitaroUnavailable, match="did not respond"):
        await client.list_offers()


async def test_unexpected_payload(client, keitaro) -> None:
    keitaro.get("/offers").respond(json={"not": "a list"})

    with pytest.raises(KeitaroError, match="unexpected response"):
        await client.list_offers()


async def test_non_json_error_body(client, keitaro) -> None:
    keitaro.get("/domains").respond(502, text="<html>Bad gateway</html>")

    with pytest.raises(KeitaroAPIError, match="Bad gateway"):
        await client.list_domains()


def test_stream_offer_round_trip_keeps_unknown_fields_and_drops_read_only() -> None:
    offer = StreamOffer.model_validate(
        f.stream_offer(5, 40, state="disabled", custom_flag=True) | {"stream_id": 3}
    )

    assert offer.to_api(share=60) == {
        "offer_id": 5,
        "state": "disabled",
        "share": 60,
        "custom_flag": True,
    }
