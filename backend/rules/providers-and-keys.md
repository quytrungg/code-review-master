# Providers and credentials

Applies to everything under `backend/`. Root `AGENTS.md` §5 points here; storage rules are in
`privacy.md`.

## Provider identity

Model ids are `<provider>:<name>` (`claude`, `openai`, `ollama-cloud`, `ollama-local`) and the prefix
is persisted in `model_used`; a legacy `ollama:` id resolves to cloud. The host comes from the URL,
not from settings: `code_reviews.vcs` records `github` or `gitlab` and every later call (fetch, diff,
publish) dispatches on it. Ollama `format: json` is for review generation only; discussion needs
prose.

## Credential storage and resolution

- Secrets live in `version_control_keys` / `llm_keys`. `settings` holds only the active id per family,
  one row per account.
- Resolution prefers the active key when its provider matches, else the oldest key of that provider.
- Reads are masked (`ghp_••••••••cdef`) unless `?reveal=true`. In a PUT, an absent id keeps the
  selection and an explicit `null` clears it.
- Both columns are `EncryptedText`: ciphertext at rest (`enc:v1:`, Fernet), plaintext only in memory,
  decrypted by the ORM type so call sites read `.token` / `.api_key` unchanged. Key handling is in
  `privacy.md`.
- Connection probes return `ok: false` + detail, never a 5xx.
