# Privacy rules — PII at rest

Applies to everything under `backend/`. PII here means personal data about **other people** that the
tool happens to hold: names, handles, avatar URLs, IPs, customer identifiers, or free text containing
them. Account identity is a deliberate exception — `users.email` is the login identifier, needs a
case-insensitive equality lookup, is shown in the nav, and is **not classified as PII in this
project**; that decision is recorded here so it is not re-opened. Source code and diffs are not PII,
but they are sensitive — never paste customer data into fixtures.

## The rule

**PII is hashed when it only needs to be compared, encrypted when it must be read back, and not
stored at all when neither is needed.** A new plaintext PII column is a decision to raise with the
user, not a default.

- **Hash** (`sha256` for a token, PBKDF2/argon2 with a per-row salt for a password, HMAC-SHA256 with a
  server-side key when you need equality lookup) — irreversible, so the value can be verified but
  never recovered.
- **Encrypt** (authenticated symmetric encryption with a key that is not in the database) when the
  application must display the value again.
- **Never** rely on "the database is local" as the protection: backups, `pg_dump` files and copied
  `.db` files travel.

## What this repo stores today

| Value | Column | Treatment |
|---|---|---|
| Password | `users.password_hash` | PBKDF2-SHA256, 260k iterations, 16-byte per-user salt, constant-time compare |
| Session token | `sessions.token_hash` | SHA-256 of the cookie value; the raw token exists only in the HttpOnly cookie |
| API tokens / keys | `version_control_keys.token`, `llm_keys.api_key` | **encrypted** — Fernet (`enc:v1:`), key in `CREDENTIALS_ENCRYPTION_KEY`; decrypted only in memory for an outbound call or a `reveal=true` read, masked in every API read, `[REDACTED]` in logs |
| Email | `users.email` | Plaintext by decision: the account identifier, case-insensitive equality lookup, displayed in the nav. Not classified as PII |
| `label` fields, review titles, thread text | several | Free text; never put personal data there, and keep prompts free of customer identifiers |

Operational note, not policy: `pg_dump` output and copied `.db` files carry these addresses in clear
text, so backups stay operator-only files and are never attached to a review or a shared drive.

## Secrets in code, logs and environments

- Never print, log or commit a token, key, password or session cookie; redact as `[REDACTED]`.
  `.env` is gitignored and `.env.example` holds placeholders only.
- **Nothing leaves the machine** except the diff/prompts sent to the chosen provider.
- `CREDENTIALS_ENCRYPTION_KEY` lives in the environment only — never in the database, a migration, a
  commit or a log line. A deployment sets it in its project environment and exports it for the
  release migration; losing it means re-entering every credential.
- A new secret column is mapped as `EncryptedText`. A data pass over stored secrets is a data-only
  Alembic revision plus a helper in `db/encryption.py`, never an ad-hoc `UPDATE` in a route.

## Applying it to new work

- Classify the column in the plan's schema section: `not PII` / `hashed` / `encrypted` / `plaintext
  (exception, reason)`. The last one needs the user's agreement in the same change.
- If you add a lookup over a hashed value, store the digest **and** nothing reversible; if the value
  must be shown, encrypt it and keep the key in `.env` (gitignored) — never next to the ciphertext.
- Do not log PII, prompts, diffs or uploads; log ids. Errors surfaced to the UI name the field, not
  the value.
- Test fixtures use obviously fake identities (`tester@example.com`), never real addresses or
  tokens; the same applies to seeded reviews.
