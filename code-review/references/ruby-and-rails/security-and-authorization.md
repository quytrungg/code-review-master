# Security and authorization

## Authorization boundaries

- Scope every object lookup and relationship mutation to an authorized user, membership, organisation, or parent resource. Unpredictable identifiers do not replace authorization.
- Validate all foreign keys and indirect identifiers supplied by users before mass assignment. Strong parameters prevent field injection; they do not prove ownership.
- Authorize at every externally reachable boundary and again where background or service execution can bypass the controller's established scope.
- Test negative cross-user and cross-organisation cases for every object reference, including URL, body, query, association, email, username, and business identifiers.
- Do not expose internal authorization reason codes or state that enables boundary enumeration. Follow the current API contract for 403 versus 404; the external IDOR policy's 404 preference is not automatically universal.
- Trace tenant scope to the first lookup derived from the authenticated boundary. Scoping a later query is insufficient when the member, organisation, or parent used to derive it was fetched globally.
- Register a new `before_action` after the authentication and authorization callbacks, never before or between them. A callback declared above `authorize_sso!` or `redirect_if_inactive!` runs for unauthenticated, inactive, or not-yet-authorized requests and can act on identity the chain has not validated.
- Treat a guard as redundant only after proving redundancy at every call site of the shared predicate: a leaf method reused by paths that lack the entry filter still needs its own check. Deleting it because the current caller covers the condition removes enforcement everywhere else, and no test fails because the tested caller keeps its check.
- When a release flag is decoupled from a data or entitlement check, re-home the non-flag conjunct in a flag-free policy method instead of deleting it. Removing the flag from the call site also removes entitlement enforcement, and the flag being on in that environment hides the loss.
- Make an authorization predicate state its own ordering and row scope explicitly instead of inheriting them from a related model's `default_scope` or from `unscoped`. A routine `default_scope` cleanup reverts `has_one` to arbitrary database order, and stripping `default_scope` flips a predicate from "any historical row" to "most recent row" — both change who passes the policy with no test failure. Before deploying such a change, run a production query that proves the affected row population is empty and name every gated surface that changes state for the non-empty case.

## Cached authorization and session validity

- Cached authorization must retain authoritative tenant and identity scope, immediate mutation and revocation requirements, invalidation, concurrency behavior, and explicit failure semantics.
- When replacing policy calls with a cached or optimized path, compare the complete legacy allow and deny semantics, including worker types and indirect guards, and test the affected role matrix. Faster evaluation is not equivalent if a guard disappears.
- Quantify a permission-cache key or epoch change as a temporary doubling of live keys against the cache store's headroom: after the first `permissions:bump_global_epoch` every old key is orphaned and new keys fill in, so the store holds roughly twice the permission-key set until the sweep or TTL expires. On an instance already above 75% in business hours this is an OOM path. Schedule the bump with a sweep and a memory abort threshold, and treat proactive or async deletion as reducing sweep cost rather than shortening the doubled window — orphaned keys live until the TTL expires.
- Treat permission aggregation as a request hot path: trace per-menu and per-policy calls, feature-flag lookups, recursion, and cache misses, because small additions multiply CPU work and saturate request threads.
- Reads that gate a write, validate session or token revocation, or decide whether a terminated user retains access must use an authoritative data source rather than a stale replica.
- A JWT session token survives logout unless logout actually invalidates the session claim: a token whose session claim is never revoked remains valid until expiry. When a change drops or moves session validation out of JWT verification, trace the logout path and prove the session token is destroyed or revoked.
- Cache session revocation, not session status, to avoid database hits on JWT validation: a revocation list is small and append-only, while session status is mutable state.

## Tokens, sessions, and credentials

- A bearer token embedded in a URL leaks on first click through browser history, logs, proxies, and shoulder surfing. Require one-time use or device and IP binding, and severely limit the sensitivity of actions allowed through URL tokens.
- An anonymous form token in a query param lets the holder read prior submissions if the form is revisitable when the token is long-lived. Prefer stateless HMAC tokens — a shared secret over job_id, candidate_job_id, and expiry — over database token tables.
- Wildcard CORS is only safe when sensitive cookies are `SameSite=lax/strict`; never pair a wildcard origin with `Access-Control-Allow-Credentials`. PINs must be hashed and brute-force protected. The PIN is sensitive data even when the action it protects is low-sensitivity, because users reuse PINs.
- Mobile sessions need shorter expiry with a fresh MFA exchange for refresh, tied to the 2FA verification timestamp. A service credential must carry the full user context: a caller acting on behalf of a user is subject to at least the same authorization checks as the user, and a reduced user_id silently drops context-dependent authorization.
- IdP session revocation: treat 404 as revoked for overlapping revocations. Only 200 and 404 clear the timestamp, and a second simultaneous revoke must not resurrect the session.
- JWT private signing keys belong in KMS or a vault, not in each service's database; serving public keys through JWKS is the low-risk part. Preserve the chain of trust in service-to-service auth: delegation with scoped short-lived tokens, never intermediary re-issuance. An intermediary that mints tokens accepted downstream becomes a new identity authority. Powerful server-to-server credentials should be short-lived signed JWT bearer tokens with registered public keys rather than long-lived access tokens; long-lived shared secrets leak into logs and cannot be revoked granularly.
- Hashing low-entropy encrypted data such as BSB plus account number for duplicate detection is brute-forceable because the input space is predictable. Use per-row salt plus dirty-bit delta checking instead.

## Redaction, rate limiting, and feature flags

- Log redaction by substring-matching the whole `filter_parameters` list destroys innocuous logs. Redact k=v pairs with word boundaries instead of substring matching.
- Require one authoritative rate limiter per boundary. If infrastructure and application limiters coexist, define precedence, identity key, bucket period, response contract, observability, and failure behavior; multiple independent limiters using different identities can be bypassed or reject inconsistently, and a temporary exception needs an owner, expiry, audit trail, and removal condition. Rate-limit keys derived from client-supplied signals such as IP or headers are trivially spoofable from an attacker-controlled endpoint. IP-based keys also overlap for large organisations sharing office networks, so prefer a user or session-key-based limit.
- Review feature-flag bucketing in its actual identity context: user, member, organisation, tenant, request, and cross-service propagation. Rollout behavior must remain stable during identity or service migrations.
- Never silently `to_s` an object in a feature-flag context; convert `object.uuid` explicitly or raise. Implicit stringification yields a garbage key, wrong flag evaluation, and user-facing authorization failures.
- `request.hash` is not stable across interpreter invocations: two processes compute different keys and miss the same cache entries. Build cache keys from an MD5 of the request instead.
- Do not use feature flags as an untracked authorization bypass. Preserve CSS and entitlement policy boundaries, and test ON, OFF, and undefined states where the system requires them.
- Before requiring a cohort exclusion in a new flag gate, read the surface the feature must mirror: a neighbouring gate's exclusion may belong to a different rollout. Trace the mirrored surface's data path — its service, selector, or serializer — to the cohort before writing or accepting the conjunct, and treat the neighbouring comment as scoped to the feature it guards.
- Distributed-cache bypasses for feature flags create backend QPS; model call frequency and failure behavior before disabling caching.
- A batch feature-flag checker with `failover_return_value: []` silently disables all flags on a single gRPC error and short-circuits the singular fallback. Refactoring lazy per-branch checks into an eager batch check converts a soft dependency into a hard one. In-process feature-flag evaluation is a short-lived release technique, not a permanent default: require benchmark evidence, close monitoring, immediate disable capability, and cleanup after public release. Avoid storing opaque feature-flag keys in mutable database arrays, which bypasses code review, validation, discoverability, and lifecycle ownership.

## Secrets, audit, and PII

- Never commit credentials or secret values. Use the organisation's current secret manager and environment injection.
- Broad application configuration can contain sensitive data even when no secret is obvious in the changed lines. Require an accountable code owner and inspect exposure, history, generated output, and downstream distribution.
- Review `.gitleaksignore` and other secret-scanner allowlist edits as security-gate changes needing a named finding, a false-positive reason, and security code-owner approval. An allowlist entry suppresses the only automated detection for a secret class, and pairing it with a `CODEOWNERS` edit removes the code owner who would have caught it.
- A security-review bypass needs an explicit acknowledgement naming the residual risk, the environment scope, the controls that still apply, the prohibitions it does not lift, and a linked follow-up, and it is resolved only after a verified revision contains the fix.
- Sanitize URLs, referrers, structured logs, job arguments, exception context, and metrics for PII and tokens, and verify filtering after interpolation and serialization.
- When city, IP, device, or similar metadata is security or attestation evidence, source it from a trusted gateway or server boundary; user-supplied fields remain spoofable even when they look plausible.

## Deletion, retention, and third-party data

- Trace deletion through uploads and object storage, audit records, caches, analytics, and downstream events. A database delete alone may leave regulated data behind.
- Soft deletion requires a specific retention and restoration contract, access controls, purge behavior, uniqueness semantics, and legal ownership.
- Gate Brakeman high- and medium-confidence findings unless the change includes concrete false-positive evidence. Do not dismiss a finding solely because the vulnerable path seems unlikely.
- Review SQL construction at identifier, fragment, ordering, and value boundaries; parameterized values do not make interpolated identifiers or clauses safe.
- Audit permission and security-sensitive changes with actor, tenant, target, action, result, and correlation data without leaking protected content. Encrypt webhook and integration payloads in transit and at rest according to the boundary contract, including signing, replay defense, rotation, and failure handling.

## Webhooks, tokens, and internal boundaries

- Webhook signature validation is not freshness validation: a valid HMAC over timestamp and payload proves authenticity, not freshness, so a replayed signed request always passes. Validate the timestamp against the wall clock and reject requests older than about 5 minutes.
- Webhook endpoints need signature verification and rate limiting: an endpoint without HMAC lets any HTTP client fabricate events, such as payout completion to trigger fund releases, and a webhook namespace without rate limiting can be flooded into database write pressure and queue saturation. Add Rack::Attack rules to webhook namespaces as defence in depth regardless of infrastructure config.
- URL shorteners: a small ID space is enumerable, so whitelist destination URLs and never let user input enter them, encrypt stored secrets with column-level encryption, obscure them from analytics and logging, use URL-safe Base64, and use PostgreSQL partitions for bulk removals.
- Tokenization: make token IDs self-describing multi-part identifiers such as `${region}/${entity}/${uuid}` so routing and validation work without a lookup; a bare opaque UUID is not enough. Detokenize on all external interfaces — webhooks, Kafka — and deal in tokens internally.
- Caching third-party API data: transforming or "washing" values, by splitting, normalising, or mapping to ISO codes, does not remove the provider's storage restrictions. A value originating from a Places or Autocomplete response remains restricted unless the user submitted it in full or it came from a non-restricted source.
- At internal trust boundaries, gRPC handlers and Kafka consumers that trust caller-supplied tenant or identity fields treat network reachability as authorization. Authenticate internal callers, enforce tenant scoping at handler and consumer entry, and reject mismatched tenant context early. Audit records must include actor and correlation ID on all writes, and production audit kill switches must be removed.

## Repository authorization systems and infrastructure actions

- Bot and service identities need the minimum data and action scope, controlled authentication paths, rotation, auditability, and explicit organisation boundaries.
- When the change touches Entitlement Access, read the current repository documents routed from `docs/authorization/entitlement/README.md` first, and verify feature type, fallback boundaries, kill-switch semantics, constant use, addon and subplan precedence, and the migration category. Test all documented states.
- When the change touches CSS permissions, read `docs/authorization/security_permission/README.md` first. Prefer CSS permission checks over new role checks, preserve subordinate and exclusion scope, and coordinate new permission models with the owning team. Apply these checks only where the repository contains and uses those systems, and let repository documentation outrank this file.
- Verify sidebar and menu-item changes against the repository's sidebar permissions payload guard, and keep the payload limited to serving menu items. The menu payload is computed from entitlement and permission state, so a payload change is a permission change shipped through a UI diff.
- Authorize destructive infrastructure actions on explicit resource identity, conditioning on every required resource tag checked against the vendor's service-authorization reference, wherever the action supports that condition key. Where it does not, keep the prefix grant scoped to one environment's name prefix and record in the policy file how and when the grant is removed: a name-prefix wildcard grants access the tag conditions were meant to deny, and an action taking an explicit cluster or instance ID is not protected by a name-scoped pattern.

### Entitlement access (org rule `#EH-AUTHORIZATION-ENTITLEMENT-ACCESS`)

- Read the flag category before judging a change that migrates a feature flag to an entitlement check. A release flag, a subplan-targeting flag, and a flag carrying other conditions (country, allowlist) each migrate differently, and a diff that treats them the same is unresolved rather than wrong. Ask which category a flag is when the change does not say.
- Release flag: keep the check outside the entitlement call, so the rollout switch survives the migration — `feature_flag_on?(:release_flag_name) && entitlement_access?(EntitlementCodes::FEATURE) { true }`.
- Subplan-targeting flag: move the check inside the entitlement block as its fallback — `entitlement_access?(EntitlementCodes::FEATURE) { feature_flag_on?(:subplan_targeting_flag_name) }`.
- Flag carrying other conditions: keep those conditions outside the entitlement call, and split the flag rather than nesting one name that means two things — one name for the subplan targeting that becomes the fallback, one for the conditions that stay outside.
- The fallback block holds only legacy flags and hardcoded plan checks (`org.premium?`, `org.free?`). Authorization, state checks, country checks, and release flags stay outside it, and entitlement codes are always constants (`EntitlementCodes::FEATURE`), never symbols.
- Standard order inside a policy: early returns, then release flags, then `entitlement_access?` with its fallback. Use early returns (`return false unless authorized?`) rather than nesting the authorization check.
- Migrating a `compute_permission` call: move the authorization out as an early return, keep `compute_permission` inside the fallback, and pass `auth: -> { true }` there because the check already ran outside.
- Multiple entitlements: `FeatureFlagAssistant.rule_based_entitlement_access?(codes, rules, context) { fallback }`, with `overrides` (`{ on: [code1], off: [code2] }`) for immediate results and `clauses` (`[{ quantifier: :all, on: [code1, code2] }]`) for conditional logic. `:all` requires every code to match, `:any` requires one.
- Test all three states of every migrated entitlement: explicitly on, explicitly off, and undefined so the fallback runs. Two states pass while the fallback is broken.

### Object references and IDOR (org rule `#EH-SECURITY-IDOR-RB`)

- Scope the query itself, not only the lookup that feeds it: `@current_user.projects.find(params[:id])`, never `Project.find(params[:id])`. Build through the association too (`@current_user.projects.build`), and route reads through the pre-authorized helpers (`current_user`, `current_organisation`, `current_membership`). In `InheritedResources`, `begin_of_association_chain` is what scopes the whole controller to that identity.
- Strong parameters everywhere, and never `assign_attributes(params)` or `update_attributes(params)` with raw params. A permitted foreign key (`user_id`, `organisation_id`) still needs an ownership check before assignment, and every supplied foreign key and indirect identifier is validated at every nesting level of the payload — `{ file_ids: [1, 2, 3] }` is three object references, not one field.
- Apply authorization in service objects, commands, and background jobs as well as controllers, since those paths run without the controller's scope.
- Test the negative case for every object reference an interface accepts, and keep the test even where the current code is already secure, so the protection survives the next change. Where the endpoint's contract answers 404 for an object outside the caller's scope, split the expectation: out of scope answers 404, in scope but not permitted answers 403. A 404 for an in-scope object and a 403 for an out-of-scope one are both information leaks, and each finding names which of the two it is. Where the contract has not settled the pair, the rule above applies: follow the contract, and treat the 404 preference as a default rather than a law.
- UUIDs or encrypted tokens are defence in depth, never the control: never rely on an unpredictable identifier in place of an authorization check, and validate the same way for email, username, or business number used as a lookup key.
