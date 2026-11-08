"""provider keys: version_control_keys + llm_keys, referenced from settings

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-08

Moves credentials out of the `settings` row into one row per credential and leaves `settings`
pointing at the active pair. Existing values are converted rather than dropped.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_COLUMNS = (
    "github_token",
    "claude_api_key",
    "ollama_api_key",
    "ollama_mode",
    "ollama_base_url",
    "ollama_model",
)


def _version_control_keys() -> sa.Table:
    return sa.Table(
        "version_control_keys",
        sa.MetaData(),
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("token", sa.Text, nullable=False),
        sa.Column("base_url", sa.Text),
        sa.Column("label", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def _llm_keys() -> sa.Table:
    return sa.Table(
        "llm_keys",
        sa.MetaData(),
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("api_key", sa.Text),
        sa.Column("base_url", sa.Text),
        sa.Column("default_model", sa.Text),
        sa.Column("label", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def upgrade() -> None:
    op.create_table(
        "version_control_keys",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_version_control_keys_provider", "version_control_keys", ["provider"])

    op.create_table(
        "llm_keys",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("api_key", sa.Text(), nullable=True),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("default_model", sa.Text(), nullable=True),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_llm_keys_provider", "llm_keys", ["provider"])

    op.add_column(
        "code_reviews",
        sa.Column("vcs", sa.String(length=16), server_default="github", nullable=False),
    )

    with op.batch_alter_table("settings") as batch:
        batch.add_column(sa.Column("version_control_key_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("llm_key_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_settings_version_control_key",
            "version_control_keys",
            ["version_control_key_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_settings_llm_key",
            "llm_keys",
            ["llm_key_id"],
            ["id"],
            ondelete="SET NULL",
        )

    bind = op.get_bind()
    legacy = bind.execute(
        sa.text(
            "SELECT github_token, claude_api_key, ollama_api_key, ollama_mode, "
            "ollama_base_url, ollama_model FROM settings WHERE id = 1"
        )
    ).mappings().first()

    if legacy is not None:
        vc_table = _version_control_keys()
        llm_table = _llm_keys()
        version_control_id: int | None = None
        llm_key_id: int | None = None

        if legacy["github_token"]:
            version_control_id = bind.execute(
                vc_table.insert().values(
                    provider="github",
                    token=legacy["github_token"],
                    label="migrated from settings",
                )
            ).inserted_primary_key[0]

        if legacy["ollama_api_key"]:
            llm_key_id = bind.execute(
                llm_table.insert().values(
                    provider="ollama_cloud",
                    api_key=legacy["ollama_api_key"],
                    default_model=legacy["ollama_model"],
                    label="migrated from settings",
                )
            ).inserted_primary_key[0]
        elif legacy["ollama_mode"] == "local":
            llm_key_id = bind.execute(
                llm_table.insert().values(
                    provider="ollama_local",
                    api_key=None,
                    base_url=legacy["ollama_base_url"],
                    default_model=legacy["ollama_model"],
                    label="migrated from settings",
                )
            ).inserted_primary_key[0]

        if legacy["claude_api_key"]:
            claude_id = bind.execute(
                llm_table.insert().values(
                    provider="claude",
                    api_key=legacy["claude_api_key"],
                    label="migrated from settings",
                )
            ).inserted_primary_key[0]
            if llm_key_id is None:
                llm_key_id = claude_id

        bind.execute(
            sa.text(
                "UPDATE settings SET version_control_key_id = :vc, llm_key_id = :llm WHERE id = 1"
            ),
            {"vc": version_control_id, "llm": llm_key_id},
        )

    with op.batch_alter_table("settings") as batch:
        for column in LEGACY_COLUMNS:
            batch.drop_column(column)


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch:
        batch.add_column(sa.Column("github_token", sa.Text(), nullable=True))
        batch.add_column(sa.Column("claude_api_key", sa.Text(), nullable=True))
        batch.add_column(sa.Column("ollama_api_key", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("ollama_mode", sa.String(length=16), server_default="cloud", nullable=False)
        )
        batch.add_column(
            sa.Column(
                "ollama_base_url",
                sa.Text(),
                server_default="http://localhost:11434",
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column("ollama_model", sa.Text(), server_default="llama3", nullable=False)
        )

    bind = op.get_bind()
    vc_table = _version_control_keys()
    llm_table = _llm_keys()
    settings = bind.execute(
        sa.text("SELECT version_control_key_id, llm_key_id FROM settings WHERE id = 1")
    ).mappings().first()

    if settings is not None:
        if settings["version_control_key_id"]:
            token = bind.execute(
                sa.select(vc_table.c.token, vc_table.c.provider).where(
                    vc_table.c.id == settings["version_control_key_id"]
                )
            ).first()
            if token is not None and token.provider == "github":
                bind.execute(
                    sa.text("UPDATE settings SET github_token = :t WHERE id = 1"),
                    {"t": token.token},
                )

        if settings["llm_key_id"]:
            key = bind.execute(
                sa.select(llm_table).where(llm_table.c.id == settings["llm_key_id"])
            ).mappings().first()
            if key is not None:
                if key["provider"] == "claude" and key["api_key"]:
                    bind.execute(
                        sa.text("UPDATE settings SET claude_api_key = :v WHERE id = 1"),
                        {"v": key["api_key"]},
                    )
                elif key["provider"] == "ollama_cloud" and key["api_key"]:
                    bind.execute(
                        sa.text(
                            "UPDATE settings SET ollama_api_key = :k, ollama_mode = 'cloud', "
                            "ollama_model = COALESCE(:m, ollama_model) WHERE id = 1"
                        ),
                        {"k": key["api_key"], "m": key["default_model"]},
                    )
                elif key["provider"] == "ollama_local":
                    bind.execute(
                        sa.text(
                            "UPDATE settings SET ollama_mode = 'local', "
                            "ollama_base_url = COALESCE(:u, ollama_base_url), "
                            "ollama_model = COALESCE(:m, ollama_model) WHERE id = 1"
                        ),
                        {"u": key["base_url"], "m": key["default_model"]},
                    )

    with op.batch_alter_table("settings") as batch:
        batch.drop_constraint("fk_settings_version_control_key", type_="foreignkey")
        batch.drop_constraint("fk_settings_llm_key", type_="foreignkey")
        batch.drop_column("version_control_key_id")
        batch.drop_column("llm_key_id")

    with op.batch_alter_table("code_reviews") as batch:
        batch.drop_column("vcs")

    op.drop_index("ix_llm_keys_provider", table_name="llm_keys")
    op.drop_table("llm_keys")
    op.drop_index("ix_version_control_keys_provider", table_name="version_control_keys")
    op.drop_table("version_control_keys")
