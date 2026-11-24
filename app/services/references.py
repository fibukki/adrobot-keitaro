"""In-memory TTL cache of read-only Keitaro references: domains, groups, sources.

These lists change rarely and are tiny, so a process-local cache is enough; it
saves three API calls on every render of the creation form.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.keitaro.client import KeitaroClient
from app.keitaro.schemas import CampaignGroup, Domain, TrafficSource


@dataclass(frozen=True)
class References:
    domains: list[Domain]
    groups: list[CampaignGroup]
    traffic_sources: list[TrafficSource]

    def domain(self, domain_id: int) -> Domain | None:
        return next((d for d in self.domains if d.id == domain_id), None)

    def has_group(self, group_id: int) -> bool:
        return any(g.id == group_id for g in self.groups)

    def has_traffic_source(self, source_id: int) -> bool:
        return any(s.id == source_id for s in self.traffic_sources)


class _TTLValue[T]:
    def __init__(self, loader: Callable[[], Awaitable[T]], ttl_seconds: float) -> None:
        self._loader = loader
        self._ttl = ttl_seconds
        self._value: T | None = None
        self._loaded_at = 0.0
        self._lock = asyncio.Lock()

    def _fresh(self) -> bool:
        return self._value is not None and time.monotonic() - self._loaded_at < self._ttl

    async def get(self) -> T:
        if not self._fresh():
            async with self._lock:
                if not self._fresh():
                    self._value = await self._loader()
                    self._loaded_at = time.monotonic()
        assert self._value is not None
        return self._value

    def invalidate(self) -> None:
        self._value = None


class ReferenceCache:
    def __init__(self, client: KeitaroClient, ttl_seconds: float) -> None:
        self._domains = _TTLValue(client.list_domains, ttl_seconds)
        self._groups = _TTLValue(client.list_campaign_groups, ttl_seconds)
        self._sources = _TTLValue(client.list_traffic_sources, ttl_seconds)

    async def get(self) -> References:
        domains, groups, sources = await asyncio.gather(
            self._domains.get(), self._groups.get(), self._sources.get()
        )
        return References(domains=domains, groups=groups, traffic_sources=sources)

    def invalidate(self) -> None:
        for value in (self._domains, self._groups, self._sources):
            value.invalidate()
