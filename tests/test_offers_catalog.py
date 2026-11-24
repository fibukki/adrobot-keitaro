import asyncio

import httpx
from sqlalchemy import select

from app.models import OfferCache
from app.services.offers_catalog import OffersCatalog
from tests import factories as f


async def test_search_fills_cache_once(offers, mock_offers) -> None:
    first = await offers.search("beauty")
    second = await offers.search("keto")

    assert [o.id for o in first] == [3749, 18002]
    assert [o.id for o in second] == [18001]
    assert mock_offers.call_count == 1  # second search served from the DB


async def test_label_matches_keitaro_format(offers, mock_offers) -> None:
    [offer] = await offers.search("Miaflow")
    assert offer.label == "[3749] Miaflow [BEAUTY-RO-BE_0009]"


async def test_label_drops_id_already_in_name(offers, mock_offers) -> None:
    [offer] = await offers.search("Hepatix")
    assert offer.label == "[18004] Hepatix [PROSTATE-DE] [quiz de -] ADNOVA v3"


async def test_search_by_id_puts_exact_match_first(offers, mock_offers) -> None:
    found = await offers.search("374")
    assert [o.id for o in found] == [374, 3749]


async def test_search_accepts_bracketed_id(offers, mock_offers) -> None:
    found = await offers.search("[18001]")
    assert [o.id for o in found] == [18001]


async def test_like_wildcards_are_escaped(offers, mock_offers) -> None:
    found = await offers.search("100%")
    assert [o.id for o in found] == [374]
    # Unescaped, "%" would match every offer; escaped, only the literal percent sign.
    assert [o.id for o in await offers.search("%")] == [374]


async def test_empty_query_lists_first_offers_up_to_limit(offers, mock_offers) -> None:
    found = await offers.search("", limit=3)
    assert [o.id for o in found] == [374, 3749, 18001]


async def test_expired_cache_is_refetched(session, client, keitaro) -> None:
    route = keitaro.get("/offers").respond(json=f.OFFERS)
    catalog = OffersCatalog(session, client, ttl_seconds=0, refresh_lock=asyncio.Lock())

    await catalog.search("a")
    await catalog.search("a")

    assert route.call_count == 2


async def test_refresh_replaces_snapshot(offers, session, keitaro) -> None:
    keitaro.get("/offers").mock(
        side_effect=[
            httpx.Response(200, json=f.OFFERS),
            httpx.Response(200, json=f.OFFERS[:2]),
        ]
    )

    assert await offers.refresh() == len(f.OFFERS)
    assert await offers.refresh() == 2

    ids = set(await session.scalars(select(OfferCache.id)))
    assert ids == {3749, 18001}


async def test_names(offers, mock_offers) -> None:
    assert await offers.names([18001, 999]) == {18001: "Keto Slim [DIET-MX]"}
    assert await offers.names([]) == {}
