"""user accounts and per-user ownership

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-08

Adds `users`/`sessions` and a `user_id` to settings, credentials and reviews. Rows that existed
before accounts are attached to a disabled `legacy@localhost` account so nothing is silently
deleted; that account cannot sign in and simply holds the data until an operator reconfigures it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OWNED_TABLES = ("settings", "version_control_keys", "llm_keys", "code_reviews")
LEGACY_EMAIL = "legacy@localhost"
# Not a PBKDF2 string, so `verify_password` can never match it.
DISABLED_HASH = "!"


def _user_table() -> sa.Table:
    return sa.Table(
        "users",
        sa.MetaData(),
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.Text),
        sa.Column("password_hash", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def _has_legacy_rows(bind: sa.Connection) -> bool:
    for table in OWNED_TABLES:
        count = bind.execute(sa.text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one()
        if count:
            return True
    return False


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_token_hash", "sessions", ["token_hash"], unique=True)

    with op.batch_alter_table("version_control_keys") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_version_control_keys_user", "users", ["user_id"], ["id"], ondelete="CASCADE"
        )
    with op.batch_alter_table("llm_keys") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_llm_keys_user", "users", ["user_id"], ["id"], ondelete="CASCADE")
    with op.batch_alter_table("code_reviews") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_code_reviews_user", "users", ["user_id"], ["id"], ondelete="CASCADE")
    with op.batch_alter_table("settings") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_settings_user", "users", ["user_id"], ["id"], ondelete="CASCADE")

    bind = op.get_bind()
    if _has_legacy_rows(bind):
        legacy_id = bind.execute(
            _user_table().insert().values(email=LEGACY_EMAIL, password_hash=DISABLED_HASH)
        ).inserted_primary_key[0]
        for table in OWNED_TABLES:
            bind.execute(
                sa.text(f'UPDATE "{table}" SET user_id = :user WHERE user_id IS NULL'),
                {"user": legacy_id},
            )

    for table in OWNED_TABLES:
        with op.batch_alter_table(table) as batch:
            # A fresh database has no rows, so nothing is left NULL here.
            batch.alter_column("user_id", existing_type=sa.Integer(), nullable=False)

    op.create_index("uq_settings_user_id", "settings", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_settings_user_id", table_name="settings")

    for table, constraint in (
        ("settings", "fk_settings_user"),
        ("code_reviews", "fk_code_reviews_user"),
        ("llm_keys", "fk_llm_keys_user"),
        ("version_control_keys", "fk_version_control_keys_user"),
    ):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(constraint, type_="foreignkey")
            batch.drop_column("user_id")

    op.drop_index("ix_sessions_token_hash", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
