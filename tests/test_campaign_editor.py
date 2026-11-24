import json

import httpx
import pytest
from sqlalchemy import select

from app.errors import Conflict, NotFound, ValidationFailed
from app.models import AuditLog
from app.services.campaign_editor import CampaignEditor
from tests import factories as f

CAMPAIGN_ID = 501
STREAM_ID = 77


@pytest.fixture
def editor(session, client, offers, mock_offers) -> CampaignEditor:
    return CampaignEditor(session=session, client=client, offers=offers)


def mock_stream(keitaro, offers):
    """GET returns `offers`; PUT echoes what was sent back, like Keitaro does."""
    keitaro.get(f"/streams/{STREAM_ID}").respond(json=f.stream(STREAM_ID, offers=offers))

    def echo(request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)["offers"]
        return httpx.Response(200, json=f.stream(STREAM_ID, offers=sent))

    return keitaro.put(f"/streams/{STREAM_ID}").mock(side_effect=echo)


def sent_offers(route) -> list[dict]:
    return json.loads(route.calls.last.request.content)["offers"]


async def test_add_offer_rebalances_and_keeps_other_fields(editor, keitaro, session) -> None:
    put = mock_stream(
        keitaro,
        [
            f.stream_offer(18001, 70, state="disabled", custom="kept"),
            f.stream_offer(18002, 30),
        ],
    )

    stream = await editor.add_offer(
        campaign_id=CAMPAIGN_ID, stream_id=STREAM_ID, offer_id=3749, actor="tester"
    )

    assert sent_offers(put) == [
        {"offer_id": 18001, "share": 34, "state": "disabled", "custom": "kept"},
        {"offer_id": 18002, "share": 33, "state": "active"},
        {"offer_id": 3749, "share": 33, "state": "active"},
    ]
    assert [(o.offer_id, o.share) for o in stream.offers] == [(18001, 34), (18002, 33), (3749, 33)]
    entry = await session.scalar(select(AuditLog))
    assert entry.action == "stream.offer_add"
    assert [o["share"] for o in entry.before] == [70, 30]
    assert [o["share"] for o in entry.after] == [34, 33, 33]


async def test_add_to_empty_stream_gets_100(editor, keitaro) -> None:
    put = mock_stream(keitaro, [])

    await editor.add_offer(campaign_id=CAMPAIGN_ID, stream_id=STREAM_ID, offer_id=3749, actor="t")

    assert sent_offers(put) == [{"offer_id": 3749, "share": 100, "state": "active"}]


async def test_add_duplicate_offer_is_rejected_without_writing(editor, keitaro) -> None:
    put = mock_stream(keitaro, [f.stream_offer(18001, 100)])

    with pytest.raises(Conflict, match="already in stream"):
        await editor.add_offer(
            campaign_id=CAMPAIGN_ID, stream_id=STREAM_ID, offer_id=18001, actor="t"
        )

    assert not put.called


async def test_add_unknown_offer_is_rejected_without_reading_stream(editor, keitaro) -> None:
    put = mock_stream(keitaro, [])

    with pytest.raises(NotFound, match="does not exist"):
        await editor.add_offer(
            campaign_id=CAMPAIGN_ID, stream_id=STREAM_ID, offer_id=424242, actor="t"
        )

    assert not put.called


async def test_remove_offer_rebalances(editor, keitaro, session) -> None:
    put = mock_stream(
        keitaro,
        [f.stream_offer(18001, 34), f.stream_offer(18002, 33), f.stream_offer(3749, 33)],
    )

    stream = await editor.remove_offer(
        campaign_id=CAMPAIGN_ID, stream_id=STREAM_ID, offer_id=18002, actor="t"
    )

    assert [(o["offer_id"], o["share"]) for o in sent_offers(put)] == [(18001, 50), (3749, 50)]
    assert sum(o.share for o in stream.offers) == 100
    entry = await session.scalar(select(AuditLog))
    assert entry.action == "stream.offer_remove"


async def test_removing_last_offer_is_forbidden(editor, keitaro) -> None:
    put = mock_stream(keitaro, [f.stream_offer(18001, 100)])

    with pytest.raises(ValidationFailed, match="last offer"):
        await editor.remove_offer(
            campaign_id=CAMPAIGN_ID, stream_id=STREAM_ID, offer_id=18001, actor="t"
        )

    assert not put.called


async def test_remove_missing_offer(editor, keitaro) -> None:
    put = mock_stream(keitaro, [f.stream_offer(18001, 100)])

    with pytest.raises(NotFound, match="not in stream"):
        await editor.remove_offer(
            campaign_id=CAMPAIGN_ID, stream_id=STREAM_ID, offer_id=3749, actor="t"
        )

    assert not put.called


async def test_stream_of_another_campaign_is_rejected(editor, keitaro) -> None:
    put = mock_stream(keitaro, [f.stream_offer(18001, 100)])

    with pytest.raises(NotFound, match="does not belong"):
        await editor.add_offer(campaign_id=999, stream_id=STREAM_ID, offer_id=3749, actor="t")

    assert not put.called


async def test_redirect_stream_has_no_offers(editor, keitaro) -> None:
    keitaro.get(f"/streams/{STREAM_ID}").respond(
        json=f.stream(STREAM_ID, type_="regular", schema="redirect")
    )

    with pytest.raises(ValidationFailed, match="does not use offers"):
        await editor.add_offer(
            campaign_id=CAMPAIGN_ID, stream_id=STREAM_ID, offer_id=3749, actor="t"
        )


async def test_result_is_taken_from_api_response(editor, keitaro) -> None:
    """If Keitaro stores something else than we sent, we show what Keitaro stored."""
    keitaro.get(f"/streams/{STREAM_ID}").respond(
        json=f.stream(STREAM_ID, offers=[f.stream_offer(18001, 100)])
    )
    keitaro.put(f"/streams/{STREAM_ID}").respond(
        json=f.stream(STREAM_ID, offers=[f.stream_offer(18001, 60), f.stream_offer(3749, 40)])
    )

    stream = await editor.add_offer(
        campaign_id=CAMPAIGN_ID, stream_id=STREAM_ID, offer_id=3749, actor="t"
    )

    assert [o.share for o in stream.offers] == [60, 40]
