from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.models.user import User
from app.schemas.common import iso_utc


class CredentialsRequest(BaseModel):
    """Shared shape for sign-up and login; validation lives in `auth_service` so both routes
    answer with the same `422` wording."""

    email: str
    password: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    created_at: str | None = None

    @classmethod
    def from_row(cls, user: User) -> "UserRead":
        return cls(id=user.id, email=user.email, created_at=iso_utc(user.created_at))
