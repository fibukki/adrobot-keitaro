"""Server-rendered pages (Jinja2) with htmx partials for the offer editor."""

from typing import Any

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select

from app.deps import (
    ActorDep,
    CreatorDep,
    EditorDep,
    KeitaroDep,
    OffersDep,
    ReferencesDep,
    SessionDep,
    SettingsDep,
)
from app.errors import AppError, NotFound
from app.keitaro.errors import KeitaroNotFound
from app.keitaro.schemas import Campaign, Stream
from app.models import Campaign as CampaignRecord
from app.services.campaign_creator import CampaignRequest
from app.services.countries import countries
from app.web.templating import templates

router = APIRouter(include_in_schema=False)

PAGE_SIZE = 20


@router.get("/")
async def index() -> Response:
    return RedirectResponse("/campaigns/new", status_code=303)


# --- part 1: campaign creator ----------------------------------------------------------


@router.get("/campaigns/new", response_class=HTMLResponse)
async def new_campaign_form(
    request: Request, references: ReferencesDep, settings: SettingsDep
) -> Response:
    form = {
        "domain_id": settings.default_domain_id,
        "group_id": settings.default_group_id,
        "traffic_source_id": settings.default_source_id,
        "geo": [],
    }
    return await _render_form(request, references, form)


@router.post("/campaigns/new", response_class=HTMLResponse)
async def create_campaign(
    request: Request, creator: CreatorDep, references: ReferencesDep, actor: ActorDep
) -> Response:
    raw = await request.form()
    form: dict[str, Any] = {
        "name": str(raw.get("name", "")),
        "geo": [str(code) for code in raw.getlist("geo")],
        "offer_id": raw.get("offer_id") or None,
        "offer_label": raw.get("offer_label", ""),
        "domain_id": raw.get("domain_id"),
        "group_id": raw.get("group_id"),
        "traffic_source_id": raw.get("traffic_source_id"),
    }
    try:
        campaign_request = CampaignRequest.build(
            **{k: v for k, v in form.items() if k != "offer_label"}
        )
        created = await creator.create(campaign_request, actor=actor)
    except AppError as exc:
        return await _render_form(
            request, references, form, error=exc.message, status=exc.status_code
        )

    query = ""
    if created.ignored_fields:
        query = "?ignored=" + ",".join(sorted(created.ignored_fields))
    return RedirectResponse(f"/campaigns/created/{created.record.id}{query}", status_code=303)


@router.get("/campaigns/created/{record_id}", response_class=HTMLResponse)
async def campaign_created(
    request: Request,
    record_id: int,
    session: SessionDep,
    settings: SettingsDep,
    ignored: str = "",
) -> Response:
    record = await session.get(CampaignRecord, record_id)
    if record is None:
        raise NotFound("Campaign not found")
    return templates.TemplateResponse(
        request,
        "campaign_created.html",
        {
            "record": record,
            "admin_url": settings.campaign_admin_link(record.keitaro_id),
            "ignored": [f for f in ignored.split(",") if f],
        },
    )


async def _render_form(
    request: Request,
    references: ReferencesDep,
    form: dict[str, Any],
    *,
    error: str | None = None,
    status: int = 200,
) -> Response:
    refs = await references.get()
    return templates.TemplateResponse(
        request,
        "campaign_new.html",
        {
            "form": form,
            "refs": refs,
            "countries": countries(),
            "error": error,
            "geo_redirect_url": request.app.state.settings.geo_redirect_url,
        },
        status_code=status,
    )


# --- part 2: campaign editor -----------------------------------------------------------


@router.get("/campaigns", response_class=HTMLResponse)
async def campaign_list(
    request: Request,
    client: KeitaroDep,
    session: SessionDep,
    settings: SettingsDep,
    q: str = "",
    page: int = Query(1, ge=1),
) -> Response:
    q = q.strip()
    has_next = False
    campaigns: list[Campaign]
    if q.isdigit():
        try:
            campaigns = [await client.get_campaign(int(q))]
        except KeitaroNotFound:
            campaigns = []
    elif q:
        # The API has no search: filter the most recent campaigns by name.
        recent = await client.list_campaigns(limit=settings.campaign_search_limit)
        campaigns = [c for c in recent if q.casefold() in c.name.casefold()]
    else:
        fetched = await client.list_campaigns(offset=(page - 1) * PAGE_SIZE, limit=PAGE_SIZE + 1)
        has_next = len(fetched) > PAGE_SIZE
        campaigns = fetched[:PAGE_SIZE]

    ours = set(
        await session.scalars(
            select(CampaignRecord.keitaro_id).where(
                CampaignRecord.keitaro_id.in_([c.id for c in campaigns])
            )
        )
    )
    return templates.TemplateResponse(
        request,
        "campaigns_list.html",
        {"campaigns": campaigns, "ours": ours, "q": q, "page": page, "has_next": has_next},
    )


@router.get("/campaigns/{campaign_id}", response_class=HTMLResponse)
async def campaign_editor(
    request: Request, campaign_id: int, editor: EditorDep, settings: SettingsDep
) -> Response:
    view = await editor.view(campaign_id)
    return templates.TemplateResponse(
        request,
        "campaign_edit.html",
        {
            "campaign": view.campaign,
            "streams": view.streams,
            "names": view.offer_names,
            "admin_url": settings.campaign_admin_link(campaign_id),
        },
    )


@router.post("/campaigns/{campaign_id}/streams/{stream_id}/offers", response_class=HTMLResponse)
async def add_offer(
    request: Request,
    campaign_id: int,
    stream_id: int,
    editor: EditorDep,
    actor: ActorDep,
    offer_id: int = Form(...),
) -> Response:
    stream = await editor.add_offer(
        campaign_id=campaign_id, stream_id=stream_id, offer_id=offer_id, actor=actor
    )
    return await _render_stream(request, editor, stream, f"Offer #{offer_id} added")


@router.post(
    "/campaigns/{campaign_id}/streams/{stream_id}/offers/{offer_id}/delete",
    response_class=HTMLResponse,
)
async def remove_offer(
    request: Request,
    campaign_id: int,
    stream_id: int,
    offer_id: int,
    editor: EditorDep,
    actor: ActorDep,
) -> Response:
    stream = await editor.remove_offer(
        campaign_id=campaign_id, stream_id=stream_id, offer_id=offer_id, actor=actor
    )
    return await _render_stream(request, editor, stream, f"Offer #{offer_id} removed")


async def _render_stream(
    request: Request, editor: EditorDep, stream: Stream, notice: str
) -> Response:
    return templates.TemplateResponse(
        request,
        "partials/stream.html",
        {
            "stream": stream,
            "names": await editor.offer_names([stream]),
            "campaign_id": stream.campaign_id,
            "notice": notice,
        },
    )


@router.post("/offers/refresh", response_class=HTMLResponse)
async def refresh_offers(offers: OffersDep) -> Response:
    count = await offers.refresh()
    return HTMLResponse(f"Offers cache refreshed: {count} offers")
