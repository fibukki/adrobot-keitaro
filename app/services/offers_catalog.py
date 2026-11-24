"""Local cache of Keitaro offers (table `offers_cache`) and offer search.

GET /offers returns the full list (≈170 offers), so the cache is refreshed as a
whole snapshot: at most once per `ttl` seconds, or on explicit request.
"""

import asyncio
import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import String, case, cast, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.keitaro.client import KeitaroClient
from app.models import OfferCache

logger = logging.getLogger(__name__)

SEARCH_LIMIT = 20


class OffersCatalog:
    def __init__(
        self,
        session: AsyncSession,
        client: KeitaroClient,
        *,
        ttl_seconds: int,
        refresh_lock: asyncio.Lock,
    ) -> None:
        """`refresh_lock` is shared per process so concurrent requests refresh only once."""
        self._session = session
        self._client = client
        self._ttl = timedelta(seconds=ttl_seconds)
        self._refresh_lock = refresh_lock

    async def last_refreshed_at(self) -> datetime | None:
        value = await self._session.scalar(select(func.min(OfferCache.updated_at)))
        if value is not None and value.tzinfo is None:  # SQLite drops tzinfo
            value = value.replace(tzinfo=UTC)
        return value

    async def ensure_fresh(self) -> None:
        refreshed_at = await self.last_refreshed_at()
        if refreshed_at is not None and datetime.now(UTC) - refreshed_at < self._ttl:
            return
        async with self._refresh_lock:
            # Another request may have refreshed the cache while we waited.
            refreshed_at = await self.last_refreshed_at()
            if refreshed_at is not None and datetime.now(UTC) - refreshed_at < self._ttl:
                return
            await self._refresh()

    async def refresh(self) -> int:
        async with self._refresh_lock:
            return await self._refresh()

    async def _refresh(self) -> int:
        offers = await self._client.list_offers()
        now = datetime.now(UTC)
        await self._session.execute(delete(OfferCache))
        self._session.add_all(
            OfferCache(id=offer.id, name=offer.name, state=offer.state, updated_at=now)
            for offer in offers
        )
        await self._session.commit()
        logger.info("offers cache refreshed: %d offers", len(offers))
        return len(offers)

    async def search(self, query: str, limit: int = SEARCH_LIMIT) -> list[OfferCache]:
        """Search by id or name. An exact id match goes first, then by id."""
        await self.ensure_fresh()
        query = query.strip().lstrip("[").rstrip("]").strip()
        stmt = select(OfferCache)
        order = [OfferCache.id]
        if query:
            conditions = [OfferCache.name.ilike(f"%{_escape_like(query)}%", escape="\\")]
            if query.isdigit():
                conditions.append(cast(OfferCache.id, String).startswith(query))
                order.insert(0, case((OfferCache.id == int(query), 0), else_=1))
            stmt = stmt.where(or_(*conditions))
        result = await self._session.scalars(stmt.order_by(*order).limit(limit))
        return list(result)

    async def get(self, offer_id: int) -> OfferCache | None:
        await self.ensure_fresh()
        return await self._session.get(OfferCache, offer_id)

    async def names(self, offer_ids: Iterable[int]) -> dict[int, str]:
        ids = set(offer_ids)
        if not ids:
            return {}
        await self.ensure_fresh()
        offers = await self._session.scalars(select(OfferCache).where(OfferCache.id.in_(ids)))
        return {offer.id: offer.display_name for offer in offers}


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
