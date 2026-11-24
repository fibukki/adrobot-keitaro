from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


class OfferCache(Base):
    """Local snapshot of Keitaro offers, used for autocomplete and display names."""

    __tablename__ = "offers_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(512))
    state: Mapped[str | None] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    @property
    def label(self) -> str:
        """Same format the Keitaro admin uses: `[3749] Offer name`.

        Offer names on the stand already start with the id (`18001 Detoxin ...`);
        that duplicate is dropped so the label reads `[18001] Detoxin ...`.
        """
        name = self.name.removeprefix(f"{self.id} ")
        return f"[{self.id}] {name}"


class Campaign(Base):
    """Campaigns created through this service."""

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(String(255))
    alias: Mapped[str | None] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(String(1024))
    geo: Mapped[list[str]] = mapped_column(JSONType)
    offer_id: Mapped[int] = mapped_column(Integer)
    domain_id: Mapped[int] = mapped_column(Integer)
    group_id: Mapped[int] = mapped_column(Integer)
    traffic_source_id: Mapped[int] = mapped_column(Integer)
    # created | rollback_failed (exists in Keitaro half-built and needs manual cleanup)
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    """Who changed what and when, with payloads before/after."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_entity", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    actor: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    before: Mapped[Any | None] = mapped_column(JSONType)
    after: Mapped[Any | None] = mapped_column(JSONType)
    error: Mapped[str | None] = mapped_column(Text)
