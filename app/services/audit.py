from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


def record(
    session: AsyncSession,
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: int | None,
    before: Any = None,
    after: Any = None,
    error: str | None = None,
) -> AuditLog:
    """Add an audit entry to the session; the caller owns the commit."""
    entry = AuditLog(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=before,
        after=after,
        error=error,
    )
    session.add(entry)
    return entry
