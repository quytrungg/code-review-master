from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.api.routes import analytics, auth, keys, models, reviews, settings, skills

# Public: signing in must be possible without a session.
api_router = APIRouter()
api_router.include_router(auth.router)

# Everything else is per-account; a missing session is a 401 before the handler runs.
_guarded = {"dependencies": [Depends(get_current_user)]}
api_router.include_router(settings.router, **_guarded)
api_router.include_router(keys.router, **_guarded)
api_router.include_router(reviews.router, **_guarded)
api_router.include_router(models.router, **_guarded)
api_router.include_router(skills.router, **_guarded)
api_router.include_router(analytics.router, **_guarded)
