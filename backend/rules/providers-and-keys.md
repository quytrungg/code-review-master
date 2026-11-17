# Providers and credentials

Applies to everything under `backend/`. Root `AGENTS.md` §5 points here; storage rules are in
`privacy.md`.

## Provider identity

Model ids are `<provider>:<name>` (`claude`, `openai`, `opencode`, `ollama-cloud`, `ollama-local`)
and the prefix is persisted in `model_used`; a legacy `ollama:` id resolves to cloud. `opencode`
reuses the Chat Completions adapter against `https://opencode.ai/inference/openai/v1` (bearer key,
base URL overridable per key) — it is a dispatch branch, not a fourth transport. An OpenCode **Go**
key must set its base URL to `https://opencode.ai/inference/go/openai/v1`, and every OpenCode call
carries `x-opencode-session` (one id per process; Zen ignores it) — the Go relay answers
`HTTP 400 MissingSessionID` without it, and a Go key left on the Zen host answers
`HTTP 402 Insufficient balance`. The host comes from the URL,
not from settings: `code_reviews.vcs` records `github` or `gitlab` and every later call (fetch, diff,
publish) dispatches on it. Ollama `format: json` is for review generation only; discussion needs
prose.

## Claude sign-in (OAuth)

- **One provider, two auth types.** `llm_keys.auth_type` is `api_key` or `oauth`; Claude is the
  only provider with both, and model ids stay `claude:<model>` either way. An OAuth row keeps the
  access token in `api_key`, the refresh token in `refresh_token` and its expiry in `expires_at` —
  all `EncryptedText`, all hidden from responses (`has_refresh_token` is the only signal).
- **PKCE is server-side.** `POST /keys/claude/oauth/start` mints a state and a verifier
  (`claude_oauth_states`, encrypted, 15 minutes) and returns only the authorize URL. `complete`
  accepts `code#state` or a bare code; an echoed state must match the pending row.
- **Refresh before the call, never retry after it.** `keys_service.credentials_for_provider` is
  async and renews a Claude OAuth token inside the 120-second window once, under a per-key lock,
  in its own session — a caller's rollback must not undo a rotated refresh token.
  `require_llm_key` is the sync half for validation and policy creation (no network). A failed
  refresh is a `422` naming Settings; a mid-call `401` is surfaced, not looped.
- **Bearer transport.** OAuth requests send `Authorization: Bearer …`,
  `anthropic-beta: oauth-2025-04-20` and the Claude Code preamble as its **own first system
  block**, with the app prompt as a second block, through httpx (`_post_claude_messages`). One
  string containing both is rejected by the OAuth gate with a misleading `429 rate_limit_error`.
  An API key keeps the SDK path, `x-api-key` and a plain string prompt. Do not route an OAuth token
  through `AsyncAnthropic(api_key=…)` — an `ANTHROPIC_API_KEY` in the environment wins and the
  request goes out with the wrong header.
- **No `temperature` for Claude.** The Claude 5 family answers
  `400 invalid_request_error: temperature is deprecated for this model`, and `/v1/models` has no
  capability flag to tell which models accept it, so every Claude request omits the field (API
  default) and the other providers keep their deterministic temperature. Do not retry a rejected
  request with it removed: the immediate second call can hit a subscription rate limit (`429`).
- **Deprecated catalogue entries are not offered.** `_claude_catalogue` drops models with
  `lifecycle: deprecated` / `deprecated_at` (keeping them only if nothing else remains); Messages
  may already refuse a model the catalogue still lists, which is how a healthy sign-in once looked
  like a `404`.
- **Client identity is configuration.** The client id, authorize/token URLs, redirect URI and
  scopes default to Claude Code's public client; Anthropic has no third-party OAuth registration,
  so the sign-in is subject to Anthropic's terms for that client. Never commit a client secret —
  PKCE needs none.
- **Token endpoints are the only OAuth network calls**, and they live in `claude_oauth_service`, so
  a test monkeypatches `_post_token` instead of the network.

## Credential storage and resolution

- Secrets live in `version_control_keys` / `llm_keys`. `settings` holds only the active id per family,
  one row per account.
- Resolution prefers the active key when its provider matches, else the oldest key of that provider.
  An account may hold a Claude API key and a Claude sign-in at once; a model id does not encode the
  auth type, so **the active key wins** — activate the credential you mean to spend.
- Reads are masked (`ghp_••••••••cdef`) unless `?reveal=true`. In a PUT, an absent id keeps the
  selection and an explicit `null` clears it.
- Both columns are `EncryptedText`: ciphertext at rest (`enc:v1:`, Fernet), plaintext only in memory,
  decrypted by the ORM type so call sites read `.token` / `.api_key` unchanged. Key handling is in
  `privacy.md`.
- Connection probes return `ok: false` + detail, never a 5xx.
