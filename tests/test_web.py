"""End-to-end tests of the HTTP layer (pages, htmx partials, JSON API) on mocks."""

import json

import httpx
import pytest

from tests import factories as f

CAMPAIGN_ID = 501


@pytest.fixture
def creation_mocks(keitaro, mock_references, mock_offers):
    streams = [
        f.stream(9001, CAMPAIGN_ID, position=1, type_="regular", schema="redirect"),
        f.stream(9002, CAMPAIGN_ID, position=2, offers=[f.stream_offer(18001, 100)]),
    ]
    pending = iter(streams)
    keitaro.post("/campaigns").respond(json=f.campaign(CAMPAIGN_ID, name="Summer"))
    keitaro.post("/streams").mock(side_effect=lambda r: httpx.Response(200, json=next(pending)))
    keitaro.get(f"/campaigns/{CAMPAIGN_ID}/streams").respond(json=streams)
    return streams


async def test_creation_form_uses_cached_references(web, mock_references) -> None:
    for _ in range(2):
        response = await web.get("/campaigns/new")
        assert response.status_code == 200

    assert "FORTESTS" in response.text
    assert 'value="1813" selected' in response.text
    assert all(route.call_count == 1 for route in mock_references.values())


async def test_create_campaign_via_form(web, creation_mocks) -> None:
    response = await web.post(
        "/campaigns/new",
        data={
            "name": "Summer",
            "geo": ["MX", "AU"],
            "offer_id": "18001",
            "offer_label": "[18001] Keto Slim",
            "domain_id": "1813",
            "group_id": "10332",
            "traffic_source_id": "836",
        },
    )
    assert response.status_code == 303

    page = await web.get(response.headers["location"])
    assert "https://keitaro.test/admin/#!/campaign.editor/501" in page.text
    assert "https://tracker.example.com/aBcD12" in page.text
    assert 'href="/campaigns/501"' in page.text


async def test_invalid_form_is_rerendered_with_error(web, keitaro, mock_references) -> None:
    create = keitaro.post("/campaigns")

    response = await web.post(
        "/campaigns/new",
        data={
            "name": "X",
            "geo": ["ZZ"],
            "offer_id": "18001",
            "domain_id": "1813",
            "group_id": "10332",
            "traffic_source_id": "836",
        },
    )

    assert response.status_code == 422
    assert "ISO 3166-1" in response.text
    assert 'value="X"' in response.text  # user input preserved
    assert not create.called


async def test_offer_search_api(web, mock_offers) -> None:
    response = await web.get("/api/offers", params={"q": "beauty"})

    assert response.status_code == 200
    assert [o["label"] for o in response.json()] == [
        "[3749] Miaflow [BEAUTY-RO-BE_0009]",
        "[18002] Hair Pro [BEAUTY-AU]",
    ]


async def test_editor_page_shows_offers_with_names(web, keitaro, mock_offers) -> None:
    keitaro.get(f"/campaigns/{CAMPAIGN_ID}").respond(json=f.campaign(CAMPAIGN_ID))
    keitaro.get(f"/campaigns/{CAMPAIGN_ID}/streams").respond(
        json=[f.stream(9002, offers=[f.stream_offer(18001, 50), f.stream_offer(3749, 50)])]
    )

    response = await web.get(f"/campaigns/{CAMPAIGN_ID}")

    assert response.status_code == 200
    assert "Keto Slim [DIET-MX]" in response.text
    assert "Miaflow" in response.text
    assert "100%" in response.text  # total row


async def test_htmx_add_offer_returns_stream_fragment(web, keitaro, mock_offers) -> None:
    keitaro.get("/streams/9002").respond(json=f.stream(9002, offers=[f.stream_offer(18001, 100)]))
    put = keitaro.put("/streams/9002").respond(
        json=f.stream(9002, offers=[f.stream_offer(18001, 50), f.stream_offer(3749, 50)])
    )

    response = await web.post(
        f"/campaigns/{CAMPAIGN_ID}/streams/9002/offers",
        data={"offer_id": "3749"},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert response.text.startswith('<section class="card stream" id="stream-9002">')
    assert "Offer #3749 added" in response.text
    assert [o["share"] for o in json.loads(put.calls.last.request.content)["offers"]] == [50, 50]


async def test_htmx_error_is_a_readable_fragment(web, keitaro, mock_offers) -> None:
    keitaro.get("/streams/9002").respond(json=f.stream(9002, offers=[f.stream_offer(18001, 100)]))

    response = await web.post(
        f"/campaigns/{CAMPAIGN_ID}/streams/9002/offers/18001/delete",
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 422
    assert 'class="alert alert-error"' in response.text
    assert "last offer" in response.text


async def test_keitaro_outage_is_not_a_500(web, keitaro) -> None:
    keitaro.get(f"/campaigns/{CAMPAIGN_ID}").respond(500, text="internal error")

    response = await web.get(f"/campaigns/{CAMPAIGN_ID}")

    assert response.status_code == 502
    assert "Keitaro rejected GET /campaigns/501 (HTTP 500)" in response.text


async def test_api_errors_are_json(web, keitaro, mock_offers) -> None:
    keitaro.get("/streams/9002").respond(json=f.stream(9002, offers=[f.stream_offer(18001, 100)]))

    response = await web.post(
        f"/api/campaigns/{CAMPAIGN_ID}/streams/9002/offers", json={"offer_id": 18001}
    )

    assert response.status_code == 409
    assert "already in stream" in response.json()["detail"]


async def test_campaign_list_search_by_name(web, keitaro) -> None:
    keitaro.get("/campaigns", params={"offset": 0, "limit": 500}).respond(
        json=[f.campaign(1, name="Summer MX"), f.campaign(2, name="Winter AU")]
    )

    response = await web.get("/campaigns", params={"q": "summer"})

    assert "Summer MX" in response.text
    assert "Winter AU" not in response.text


async def test_campaign_list_pagination(web, keitaro) -> None:
    keitaro.get("/campaigns", params={"offset": 20, "limit": 21}).respond(
        json=[f.campaign(i) for i in range(21)]
    )

    response = await web.get("/campaigns", params={"page": 2})

    assert "← Newer" in response.text
    assert "Older →" in response.text
