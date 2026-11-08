# Database rules

Applies to everything under `backend/`. Root `AGENTS.md` §6 is the summary; this is the checklist to
run before touching stored data.

## Never wipe a database without asking first

"Wipe" means any of: `rm`/`mv` a database file, `DROP`/`TRUNCATE`/schema drops, a `DELETE` you have
not read the `WHERE` on, `DELETE` with no `WHERE`, `alembic downgrade` past a revision that carries
data, `dropdb`, or `--truncate` in `scripts/migrate_sqlite_to_postgres.py`.

The configured database is `DATABASE_URL` from `backend/.env` (PostgreSQL on
`localhost:5432/code_review`; the local cluster is `/opt/homebrew/var/postgresql@15`, via
`brew services`). SQLite URLs: `sqlite:///./app.db` is relative to `backend/`; an absolute path
needs four slashes.

1. **Stop and ask the user.** One message, before the command, containing:
   - **what** would be deleted — table, row count or file path, and which database
     (`DATABASE_URL` from `.env`, or a scratch one);
   - **why** it is needed — the bug, migration or test that requires it, not "cleanup";
   - **what is lost** and whether it is recoverable (has a `pg_dump` been taken? was it only fixtures
     you created minutes ago?);
   - **the alternative** you considered — a scratch database, a backfill migration, a scoped
     `UPDATE ... WHERE`.
2. **Prefer the non-destructive path.** Schema work runs against
   `sqlite:////tmp/verify.db` or a separate `createdb code_review_check`. Data repair is an `UPDATE`
   in a migration, not a delete. Cleanup is removing the fixtures you created, named out loud.
3. **Never treat `DATABASE_URL` as scratch.** No "reset the dev database", no truncating between
   test runs — tests already use a `mkdtemp` SQLite file (see `tests/conftest.py`).
4. **Fixtures you created may be deleted** when you finish, provided you say which rows and confirm
   the count afterwards; anything that predates your session is the user's data.
5. **If the user approves a delete**, take `pg_dump <db> > <file>.sql` first and state the path in
   the same message, then report the row counts before and after.

This governs what **you** run while working, not product behaviour: an endpoint that deletes a key
or a foundation is the product working as designed — it must stay owner-scoped and confirmed in the
UI, and its cascade must only reach the row the user named.

## Schema changes

- Alembic is the only schema source; new revisions are verified `upgrade` **and** `downgrade -1` on a
  scratch database before they touch the configured one.
- Destructive-looking migrations (dropping a column or table) must **backfill or archive** what they
  replace and say so in the plan; `0008` is the model — old rows moved to a disabled account rather
  than being dropped.
- `batch_alter_table` for column changes so SQLite works; reset `pg_get_serial_sequence` after bulk
  copies that insert explicit ids.
- `DateTime(timezone=True)`: SQLite stores naive UTC and PostgreSQL reinterprets naive values —
  attach `timezone.utc` when copying.

## Drift is repaired ad-hoc, not by a revision

A column one database is merely missing (one database, one statement) is an operator `ALTER`
recorded in the phase plan with its guard query; `alembic_version` stays at head. A revision is for
schema evolution every database needs. If a database is stamped with a revision that is then
removed, restamp it to head (`UPDATE alembic_version`) **before** deleting the file.

