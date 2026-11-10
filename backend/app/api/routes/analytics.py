from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_db
from app.schemas.analytics import AnalyticsRead
from app.services import analytics

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("", response_model=AnalyticsRead)
def read_analytics(
    user: CurrentUser,
    days: int = Query(default=30, ge=1, le=365, description="Window in days, ending now."),
    db: Session = Depends(get_db),
) -> AnalyticsRead:
    """Spend, volume, latency and review-quality metrics for the signed-in account."""
    return analytics.summarise(db, user.id, days)
