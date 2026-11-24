"""Thin async client for the Keitaro Admin API v1.

Only HTTP and (de)serialisation live here: no caching, no business rules, no retries.
Requests to the API are not idempotent (POST /campaigns, POST /streams), and the
stand logs every call, so retrying blindly would do more harm than good.
"""

import logging
import time
from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError

from app.keitaro.errors import KeitaroAPIError, KeitaroError, KeitaroNotFound, KeitaroUnavailable
from app.keitaro.schemas import (
    Campaign,
    CampaignCreate,
    CampaignGroup,
    Domain,
    Offer,
    Stream,
    StreamCreate,
    TrafficSource,
)

logger = logging.getLogger(__name__)

_ERROR_BODY_LIMIT = 2000


class KeitaroClient:
    def __init__(self, http: httpx.AsyncClient) -> None:
        """`http` must be configured with base_url, the Api-Key header and timeouts."""
        self._http = http

    @classmethod
    def build_http(cls, base_url: str, api_key: str, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Api-Key": api_key, "Accept": "application/json"},
            timeout=httpx.Timeout(timeout),
        )

    # --- campaigns -------------------------------------------------------------------

    async def list_campaigns(self, *, offset: int = 0, limit: int = 50) -> list[Campaign]:
        data = await self._request("GET", "/campaigns", params={"offset": offset, "limit": limit})
        return self._parse(list[Campaign], data)

    async def get_campaign(self, campaign_id: int) -> Campaign:
        return self._parse(Campaign, await self._request("GET", f"/campaigns/{campaign_id}"))

    async def create_campaign(self, payload: CampaignCreate) -> Campaign:
        data = await self._request("POST", "/campaigns", json=payload.to_api())
        return self._parse(Campaign, data)

    async def delete_campaign(self, campaign_id: int) -> None:
        await self._request("DELETE", f"/campaigns/{campaign_id}")

    async def list_campaign_streams(self, campaign_id: int) -> list[Stream]:
        data = await self._request("GET", f"/campaigns/{campaign_id}/streams")
        return self._parse(list[Stream], data)

    # --- streams ---------------------------------------------------------------------

    async def create_stream(self, payload: StreamCreate) -> Stream:
        return self._parse(Stream, await self._request("POST", "/streams", json=payload.to_api()))

    async def get_stream(self, stream_id: int) -> Stream:
        return self._parse(Stream, await self._request("GET", f"/streams/{stream_id}"))

    async def update_stream(self, stream_id: int, payload: dict[str, Any]) -> Stream:
        """PUT /streams/{id}. Note: `offers` and `filters` replace the whole collection."""
        data = await self._request("PUT", f"/streams/{stream_id}", json=payload)
        return self._parse(Stream, data)

    # --- read-only references --------------------------------------------------------

    async def list_offers(self) -> list[Offer]:
        return self._parse(list[Offer], await self._request("GET", "/offers"))

    async def list_domains(self) -> list[Domain]:
        return self._parse(list[Domain], await self._request("GET", "/domains"))

    async def list_campaign_groups(self) -> list[CampaignGroup]:
        data = await self._request("GET", "/groups", params={"type": "campaigns"})
        return self._parse(list[CampaignGroup], data)

    async def list_traffic_sources(self) -> list[TrafficSource]:
        return self._parse(list[TrafficSource], await self._request("GET", "/traffic_sources"))

    # --- plumbing --------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        started = time.perf_counter()
        try:
            response = await self._http.request(method, path, params=params, json=json)
        except httpx.TimeoutException as exc:
            logger.warning("keitaro %s %s timed out: %r", method, path, exc)
            raise KeitaroUnavailable("Keitaro did not respond in time, try again later") from exc
        except httpx.HTTPError as exc:
            logger.warning("keitaro %s %s transport error: %r", method, path, exc)
            raise KeitaroUnavailable("Keitaro is unreachable, try again later") from exc

        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info("keitaro %s %s -> %s (%.0f ms)", method, path, response.status_code, elapsed_ms)

        if response.is_error:
            body = response.text[:_ERROR_BODY_LIMIT]
            logger.warning(
                "keitaro %s %s failed with %s, request=%s, response=%s",
                method,
                path,
                response.status_code,
                json,
                body,
            )
            error_cls = KeitaroNotFound if response.status_code == 404 else KeitaroAPIError
            raise error_cls(method, path, response.status_code, _error_detail(response))

        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            logger.warning("keitaro %s %s returned non-JSON: %s", method, path, response.text[:500])
            raise KeitaroError("Keitaro returned a malformed response") from exc

    @staticmethod
    def _parse[T](model: type[T], data: Any) -> T:
        try:
            return TypeAdapter(model).validate_python(data)
        except ValidationError as exc:
            logger.error("unexpected Keitaro payload for %s: %s", model, exc)
            raise KeitaroError("Keitaro returned an unexpected response") from exc


def _error_detail(response: httpx.Response) -> str:
    """Keitaro reports errors as {"error": "..."}; fall back to the raw body."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:300] or response.reason_phrase
    if isinstance(body, dict):
        for key in ("error", "message", "errors"):
            if body.get(key):
                return str(body[key])[:300]
    return str(body)[:300]
