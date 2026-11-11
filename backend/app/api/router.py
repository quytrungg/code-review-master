from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.api.routes import analytics, auth, inbox, keys, models, reviews, settings, skills, watches

# Public: signing in must be possible without a session.
api_router = APIRouter()
api_router.include_router(auth.router)
# Public: a cron job cannot hold a cookie, so the watch tick carries a shared secret instead.
api_router.include_router(watches.tick_router)

# Everything else is per-account; a missing session is a 401 before the handler runs.
_guarded = {"dependencies": [Depends(get_current_user)]}
api_router.include_router(settings.router, **_guarded)
api_router.include_router(keys.router, **_guarded)
api_router.include_router(reviews.router, **_guarded)
api_router.include_router(inbox.router, **_guarded)
api_router.include_router(watches.router, **_guarded)
api_router.include_router(models.router, **_guarded)
api_router.include_router(skills.router, **_guarded)
api_router.include_router(analytics.router, **_guarded)
