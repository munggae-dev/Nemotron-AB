from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.deps import get_conn
from nemotron_ab import db

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(limit: int = 100) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = db.fetch_notifications(conn, limit=limit)
        return [dict(r) for r in rows]


@router.get("/unread-count")
def unread_count() -> dict[str, int]:
    with get_conn() as conn:
        return {"count": db.unread_notification_count(conn)}


@router.patch("/{notification_id}/read")
def mark_read(notification_id: int) -> dict[str, str]:
    with get_conn() as conn:
        db.mark_notification_read(conn, notification_id)
    return {"status": "ok"}
