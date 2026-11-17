from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from app.models.keys import AUTH_OAUTH
from app.services import ledger

ANTHROPIC_VERSION = "2023-06-01"
# Claude sign-in (OAuth): the Messages API wants a bearer token with this beta header, and an
# OAuth request whose system prompt does not start with the Claude Code preamble is refused.
CLAUDE_OAUTH_BETA = "oauth-2025-04-20"
CLAUDE_CODE_PREAMBLE = "You are Claude Code, Anthropic's official CLI for Claude."
ANTHROPIC_DEFAULT_URL = "https://api.anthropic.com"
OLLAMA_NUM_CTX = 32768

CLAUDE = "claude"
OPENAI = "openai"
# Hosted Ollama (https://ollama.com/api, bearer API key) — the default Ollama transport.
OLLAMA_CLOUD = "ollama-cloud"
# Ollama running on the operator's machine (no authentication).
OLLAMA_LOCAL = "ollama-local"
# OpenCode Console inference (bearer API key), served as an OpenAI-compatible endpoint. OpenCode
# also serves Anthropic- and Gemini-shaped routes and translates between them, so the Chat
# Completions transport reaches every model in its catalogue.
OPENCODE = "opencode"
OPENCODE_URL = "https://opencode.ai/inference/openai/v1"
# The OpenCode relay demands x-opencode-session and refuses requests without it (HTTP 400
# MissingSessionID) — the Go subscription relay in particular. One id per process is stable enough
# for the relay's routing/affinity and carries no account or prompt data; Zen accepts and ignores it.
OPENCODE_SESSION_ID = uuid.uuid4().hex
# Pre-Phase-6 ids: "ollama:<tag>" meant the local daemon. It now resolves to the hosted API,
# because cloud is the default; local models are addressed as "ollama-local:<tag>".
LEGACY_OLLAMA = "ollama"

OLLAMA_PROVIDERS = (OLLAMA_CLOUD, OLLAMA_LOCAL)
MODEL_PROVIDERS = (CLAUDE, OPENAI, OPENCODE, *OLLAMA_PROVIDERS)

# Model-id prefix ↔ database provider name (`llm_keys.provider`).
DB_PROVIDER = {
    CLAUDE: "claude",
    OPENAI: "openai",
    OPENCODE: "opencode",
    OLLAMA_CLOUD: "ollama_cloud",
    OLLAMA_LOCAL: "ollama_local",
}
MODEL_PROVIDER = {value: key for key, value in DB_PROVIDER.items()}

MODEL_ID_HINT = (
    "Expected 'claude:<model>', 'openai:<model>', 'opencode:<model>', 'ollama-cloud:<tag>' or "
    "'ollama-local:<tag>'."
)

# Shown only when the catalogue cannot be fetched. Both ids were in the live list on 2026-11-17;
# the old `claude-sonnet-4-5-20250929` entry was removed because Anthropic marks it deprecated
# (`lifecycle: deprecated`, retires 2026-11-30) and Messages already refuses it on a subscription.
CLAUDE_FALLBACK = [
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5"},
    {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5"},
]

OPENAI_FALLBACK = [
    {"id": "gpt-5-codex", "label": "GPT-5 Codex"},
    {"id": "gpt-4.1", "label": "GPT-4.1"},
]

# Shown only when the OpenCode catalogue cannot be fetched; every id was in the live list on
# 2026-11-12. A stored `default_model` still wins over these.
OPENCODE_FALLBACK = [
    {"id": "kimi-k2.6", "label": "kimi-k2.6"},
    {"id": "glm-5.3", "label": "glm-5.3"},
]

FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class LLMError(Exception):
    """Model call or response-shape failure, surfaced to the operator verbatim.

    `status_code` is kept when the provider answered, so a caller can tell "this model is gone"
    from "this credential is wrong" without parsing the message.
    """

    def __init__(self, detail: str, status_code: int | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class ModelRef:
    provider: str
    name: str

    @property
    def id(self) -> str:
        return f"{self.provider}:{self.name}"


@dataclass(frozen=True)
class LLMCredentials:
    """Everything needed to call one provider, resolved from an `llm_keys` row."""

    provider: str  # database form: claude | openai | ollama_cloud | ollama_local
    api_key: str | None
    base_url: str | None
    default_model: str | None = None
    # `api_key` or `oauth`. Only Claude has both: an OAuth row's `api_key` is an access token and
    # the request authenticates with `Authorization: Bearer` instead of `x-api-key`.
    auth_type: str = "api_key"


@dataclass
class LLMResult:
    """One completion plus what the provider reported about it.

    `prompt_tokens`/`completion_tokens` are `None` when the provider or model does not report
    usage — never 0, which would silently under-report spend. `latency_ms` covers the provider
    call only, so it is comparable across adapters.
    """

    text: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int
    provider: str
    model: str
    ok: bool = True
    error_class: str | None = None

    @property
    def total_tokens(self) -> int | None:
        if self.prompt_tokens is None or self.completion_tokens is None:
            return None
        return self.prompt_tokens + self.completion_tokens


def _elapsed_ms(started: float) -> int:
    return max(0, int(round((time.monotonic() - started) * 1000)))


def _error_class(exc: BaseException) -> str:
    """The cause's class name (`RateLimitError`), never its message, which may quote a prompt."""
    cause = exc.__cause__
    return (cause or exc).__class__.__name__


def _reasoning_tokens(body: dict | None) -> int:
    """How many completion tokens the provider says went to reasoning, or 0."""
    usage = (body or {}).get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    value = details.get("reasoning_tokens")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return 0


def _truncation_error(
    label: str,
    name: str,
    limit: int | None,
    body: dict | None = None,
) -> LLMError:
    """A truncated answer is a configuration problem, not an empty response."""
    where = f" at its {limit}-token output limit" if limit else " at its output limit"
    detail = f"{label} stopped{where} before finishing the answer from '{name}'"
    reasoning = _reasoning_tokens(body)
    if reasoning:
        detail += f" ({reasoning} tokens went to reasoning)"
    return LLMError(
        detail
        + ". Raise the output limit (LLM_EVOLVE_MAX_TOKENS for skill evolution, LLM_MAX_TOKENS "
        "otherwise) or shorten the prompt."
    )


def _token(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def claude_usage(payload: dict | list) -> tuple[int | None, int | None]:
    """`(input, output)` tokens from a Messages response, or from its stream events.

    A stream reports `input_tokens` once in `message_start` and `output_tokens` in the trailing
    `message_delta`, so both are merged here; a non-streaming body carries the same numbers under
    `usage`.
    """
    if isinstance(payload, list):
        prompt = completion = None
        for event in payload:
            if not isinstance(event, dict):
                continue
            kind = event.get("type")
            if kind == "message_start":
                usage = (event.get("message") or {}).get("usage") or {}
                prompt = _token(usage.get("input_tokens")) or prompt
            elif kind == "message_delta":
                usage = event.get("usage") or {}
                completion = _token(usage.get("output_tokens")) or completion
        return prompt, completion
    usage = (payload or {}).get("usage") or {}
    return _token(usage.get("input_tokens")), _token(usage.get("output_tokens"))


def openai_usage(payload: dict) -> tuple[int | None, int | None]:
    """`(prompt, completion)` tokens from a Chat Completions body.

    Streamed responses carry the same `usage` object on the terminal chunk, which only appears
    when the request sets `stream_options: {"include_usage": true}`.
    """
    usage = (payload or {}).get("usage") or {}
    return _token(usage.get("prompt_tokens")), _token(usage.get("completion_tokens"))


def ollama_usage(payload: dict) -> tuple[int | None, int | None]:
    """`(prompt_eval_count, eval_count)`; absent or 0 means the model reported nothing."""
    prompt = _token((payload or {}).get("prompt_eval_count"))
    completion = _token((payload or {}).get("eval_count"))
    return prompt or None, completion or None


def parse_model_id(model_id: str) -> ModelRef:
    if not model_id or ":" not in model_id:
        raise LLMError(f"Unknown model id '{model_id}'. {MODEL_ID_HINT}")
    provider, _, name = model_id.partition(":")
    provider = provider.strip().lower()
    name = name.strip()
    if provider == LEGACY_OLLAMA:
        provider = OLLAMA_CLOUD
    if provider not in MODEL_PROVIDERS or not name:
        raise LLMError(f"Unknown model id '{model_id}'. {MODEL_ID_HINT}")
    return ModelRef(provider=provider, name=name)


def resolve_endpoint(credentials: LLMCredentials, model: ModelRef) -> tuple[str, dict[str, str]]:
    """Base URL plus auth headers for a model, based on the key's provider and stored base URL."""
    config = get_settings()
    if model.provider == OLLAMA_CLOUD:
        if not credentials.api_key:
            raise LLMError("No Ollama Cloud API key configured. Add one in Settings.")
        base = (credentials.base_url or config.ollama_cloud_url).rstrip("/")
        return base, {"Authorization": f"Bearer {credentials.api_key}"}
    if model.provider == OLLAMA_LOCAL:
        base = (credentials.base_url or "http://localhost:11434").rstrip("/")
        return base, {}
    if model.provider == OPENAI:
        if not credentials.api_key:
            raise LLMError("No OpenAI API key configured. Add one in Settings.")
        base = (credentials.base_url or config.openai_base_url).rstrip("/")
        return base, {"Authorization": f"Bearer {credentials.api_key}"}
    if model.provider == OPENCODE:
        if not credentials.api_key:
            raise LLMError("No OpenCode API key configured. Add one in Settings.")
        base = (credentials.base_url or OPENCODE_URL).rstrip("/")
        return base, {
            "Authorization": f"Bearer {credentials.api_key}",
            "x-opencode-session": OPENCODE_SESSION_ID,
        }
    if model.provider == CLAUDE:
        if not credentials.api_key:
            raise LLMError(
                "The Claude sign-in has no access token. Sign in again in Settings."
                if credentials.auth_type == AUTH_OAUTH
                else "No Claude API key configured. Add one in Settings."
            )
        return (credentials.base_url or ANTHROPIC_DEFAULT_URL).rstrip("/"), {}
    raise LLMError(f"Provider '{model.provider}' is not supported.")


async def probe_ollama(
    base_url: str, api_key: str | None = None, timeout: float = 10.0, label: str = "Ollama"
) -> tuple[bool, str, dict | None]:
    """Verify an Ollama endpoint answers and report the models it offers."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    url = base_url.rstrip("/") + "/api/tags"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return False, f"Could not reach {label} at {base_url}: {exc.__class__.__name__}", None

    if response.status_code in (401, 403):
        return False, f"{label} rejected the API key (HTTP {response.status_code})", None
    if response.status_code != 200:
        return False, f"{label} returned HTTP {response.status_code}", None

    try:
        models = [entry.get("name", "") for entry in response.json().get("models", [])]
    except ValueError:
        return False, f"{label} returned a non-JSON response", None

    models = sorted(name for name in models if name)
    detail = f"{len(models)} model(s) available" if models else f"{label} is reachable but has no models"
    return True, detail, {"models": models}


async def probe_claude(
    api_key: str, base_url: str | None = None, timeout: float = 10.0
) -> tuple[bool, str, dict | None]:
    """Verify an Anthropic API key with the cheapest authenticated endpoint."""
    if not api_key.startswith("sk-ant-"):
        return False, "Key does not look like an Anthropic API key (expected sk-ant-...)", None
    url = (base_url or "https://api.anthropic.com").rstrip("/") + "/v1/models"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                url, headers={"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION}
            )
    except httpx.HTTPError as exc:
        return False, f"Could not reach Anthropic: {exc.__class__.__name__}", None

    if response.status_code == 200:
        return True, "API key accepted", None
    if response.status_code in (401, 403):
        return False, "Anthropic rejected the API key", None
    return False, f"Anthropic returned HTTP {response.status_code}", None


async def probe_claude_oauth(
    access_token: str,
    base_url: str | None = None,
    model: str | None = None,
    timeout: float = 20.0,
) -> tuple[bool, str, dict | None]:
    """Verify a Claude sign-in with one tiny Messages call on a model this account accepts.

    A fixed model id is not a credential check: a subscription can reject a model the catalogue
    still lists (`404 not_found_error`), which looks exactly like a broken sign-in. The catalogue
    is the account's real list, so try the configured model first, then what it returns.
    """
    candidates: list[str] = []
    if model:
        candidates.append(model)
    for entry in await list_claude_models(access_token, base_url, timeout=5.0, oauth=True):
        candidates.append(entry["id"])
    for entry in CLAUDE_FALLBACK:
        candidates.append(entry["id"])
    # A handful is enough to get past a stale entry; an account always has one working model.
    unique = list(dict.fromkeys(candidates))[:6]

    last_error: LLMError | None = None
    for candidate in unique:
        payload = {
            "model": candidate,
            "max_tokens": 1,
            "system": claude_system_prompt("", oauth=True),
            "messages": [{"role": "user", "content": "ping"}],
        }
        try:
            await _post_claude_messages(
                claude_messages_url(base_url),
                claude_oauth_headers(access_token),
                payload,
                timeout,
            )
        except LLMError as exc:
            if exc.status_code in (401, 403):
                return False, exc.detail, None
            if exc.status_code == 404:
                last_error = exc
                continue
            return False, exc.detail, None
        return True, f"Claude sign-in accepted ({candidate})", {"model": candidate}

    if last_error is not None:
        return (
            False,
            "Claude rejected every model this account lists for the sign-in. "
            "Pick another model in Settings.",
            None,
        )
    return False, "Claude did not accept the sign-in. Sign in again in Settings.", None


async def probe_openai(
    api_key: str, base_url: str | None = None, timeout: float = 10.0, label: str = "OpenAI"
) -> tuple[bool, str, dict | None]:
    """Verify an OpenAI-compatible key against `GET /models`."""
    base = (base_url or "https://api.openai.com/v1").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{base}/models", headers={"Authorization": f"Bearer {api_key}"}
            )
    except httpx.HTTPError as exc:
        return False, f"Could not reach {label} at {base}: {exc.__class__.__name__}", None

    if response.status_code in (401, 403):
        return False, f"{label} rejected the API key", None
    if response.status_code != 200:
        return False, f"{label} returned HTTP {response.status_code}", None
    try:
        models = [entry.get("id", "") for entry in response.json().get("data", [])]
    except (ValueError, AttributeError):
        models = []
    return True, f"{len([m for m in models if m])} model(s) available", {"models": sorted(m for m in models if m)}


def _claude_catalogue(payload: dict) -> list[dict[str, str]]:
    """Usable `/v1/models` entries, dropping deprecated models while an active one exists.

    Anthropic keeps deprecated models in the catalogue and Messages may already refuse them for an
    account, which is how a healthy sign-in once looked like a 404. Keep the deprecated ones only
    when nothing else is left, so the picker never goes empty.
    """
    entries = [
        entry
        for entry in (payload.get("data") or [])
        if isinstance(entry, dict) and entry.get("id")
    ]
    active = [
        entry
        for entry in entries
        if entry.get("lifecycle") != "deprecated" and not entry.get("deprecated_at")
    ]
    return [
        {"id": entry["id"], "label": entry.get("display_name") or entry["id"]}
        for entry in (active or entries)
    ]


async def list_claude_models(
    api_key: str, base_url: str | None = None, timeout: float = 5.0, *, oauth: bool = False
) -> list[dict[str, str]]:
    """Claude models for a key or a sign-in; falls back to a static list when the API refuses.

    The models endpoint is API-key oriented, so an OAuth token may be refused there even though
    Messages accepts it; the static pair keeps the picker usable and the stored default model is
    added by the route.
    """
    url = (base_url or ANTHROPIC_DEFAULT_URL).rstrip("/") + "/v1/models?limit=20"
    headers = (
        claude_oauth_headers(api_key)
        if oauth
        else {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION}
    )
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers)
        if response.status_code == 200:
            models = _claude_catalogue(response.json())
            if models:
                return models
    except (httpx.HTTPError, ValueError, KeyError):
        pass
    return list(CLAUDE_FALLBACK)


async def list_openai_models(
    api_key: str, base_url: str | None = None, timeout: float = 5.0
) -> list[dict[str, str]]:
    """OpenAI-compatible model list; falls back to a static list when unreachable."""
    base = (base_url or "https://api.openai.com/v1").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{base}/models", headers={"Authorization": f"Bearer {api_key}"}
            )
        if response.status_code == 200:
            models = [
                {"id": entry["id"], "label": entry["id"]}
                for entry in response.json().get("data", [])
                if isinstance(entry, dict) and entry.get("id")
            ]
            if models:
                return sorted(models, key=lambda entry: entry["id"])
    except (httpx.HTTPError, ValueError, KeyError):
        pass
    return list(OPENAI_FALLBACK)


def claude_oauth_headers(access_token: str) -> dict[str, str]:
    """Bearer auth for a Claude sign-in, as Claude Code sends it."""
    return {
        "Authorization": f"Bearer {access_token}",
        "anthropic-version": ANTHROPIC_VERSION,
        "anthropic-beta": CLAUDE_OAUTH_BETA,
        "content-type": "application/json",
    }


def claude_system_prompt(system_prompt: str, *, oauth: bool) -> str | list[dict[str, str]]:
    """The system field for a Claude request.

    An OAuth request must carry the Claude Code preamble as its own first system block. Appending
    the app prompt to the preamble as one string makes Anthropic answer a misleading
    `429 rate_limit_error`; an array of text blocks is what Claude Code sends and is accepted for
    short and long prompts alike. API keys keep the plain string.
    """
    if not oauth:
        return system_prompt
    blocks = [{"type": "text", "text": CLAUDE_CODE_PREAMBLE}]
    if system_prompt:
        blocks.append({"type": "text", "text": system_prompt})
    return blocks


def claude_messages_url(base_url: str | None) -> str:
    return (base_url or ANTHROPIC_DEFAULT_URL).rstrip("/") + "/v1/messages"


def claude_message_payload(
    name: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    *,
    oauth: bool,
) -> dict:
    # No `temperature`: Anthropic deprecates it on newer models with a `400 invalid_request_error`
    # ("`temperature` is deprecated for this model"), and the catalogue has no capability flag to
    # tell which ones accept it. Omitting it works for every Claude generation and is the API
    # default; the other providers keep their deterministic temperature.
    return {
        "model": name,
        "max_tokens": max_tokens,
        "system": claude_system_prompt(system_prompt, oauth=oauth),
        "messages": [{"role": "user", "content": user_prompt}],
    }


async def _post_claude_messages(
    url: str, headers: dict[str, str], payload: dict, timeout: float | None = None
) -> dict:
    """One Messages request; the seam tests capture, and the only place raw Claude errors map."""
    try:
        async with httpx.AsyncClient(timeout=timeout or get_settings().llm_timeout_s) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise LLMError(f"Could not reach Claude: {exc.__class__.__name__}") from exc

    if response.status_code in (401, 403):
        detail = (response.text or "").strip()[:200]
        raise LLMError(
            "Claude rejected the sign-in. Sign in again in Settings."
            + (f" ({detail})" if detail else ""),
            response.status_code,
        )
    if response.status_code == 404:
        model = payload.get("model") if isinstance(payload, dict) else None
        raise LLMError(
            f"Claude does not have the model '{model}' for this account. Pick another model.",
            404,
        )
    if response.status_code == 429:
        raise LLMError(
            "Claude rate limit reached. Wait a moment and try again.", response.status_code
        )
    if response.status_code != 200:
        raise LLMError(
            f"Claude returned HTTP {response.status_code}: {response.text[:300]}",
            response.status_code,
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise LLMError("Claude returned an unexpected response shape") from exc
    if not isinstance(body, dict):
        raise LLMError("Claude returned an unexpected response shape")
    return body


async def generate(
    credentials: LLMCredentials,
    model: ModelRef,
    system_prompt: str,
    user_prompt: str,
    json_mode: bool = False,
    *,
    purpose: str,
    review_id: int | None = None,
    thread_id: int | None = None,
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
) -> LLMResult:
    """One non-streaming completion, with the token counts and latency it reported.

    `json_mode` asks the provider to constrain output to JSON (Ollama's `format: json`,
    OpenAI's `response_format`). Discussion replies are prose, so they pass False.

    `max_tokens` overrides the shared `LLM_MAX_TOKENS` for this call only (the skill-evolution
    answer needs more room than a review finding). `reasoning_effort` is forwarded to
    OpenAI-compatible transports; only the OpenCode relay has been verified to accept "none".

    `purpose` is the call site (`LLMPurpose`) and is required, so every call — success or failure
    — reaches the ledger with a reason attached. Recording happens after (or instead of) the
    result and never raises, so telemetry cannot change what the caller gets.

    Credentials are resolved *before* the recording block: a missing key means no request was made,
    so it is an error the caller sees, not a call in the ledger.
    """
    config = get_settings()
    output_limit = max_tokens or config.llm_max_tokens
    base_url: str = ""
    headers: dict[str, str] = {}
    if model.provider == CLAUDE:
        if not credentials.api_key:
            raise LLMError(
                "The Claude sign-in has no access token. Sign in again in Settings."
                if credentials.auth_type == AUTH_OAUTH
                else "No Claude API key configured. Add one in Settings."
            )
    else:
        base_url, headers = resolve_endpoint(credentials, model)

    started = time.monotonic()
    try:
        if model.provider == CLAUDE:
            if credentials.auth_type == AUTH_OAUTH:
                result = await _generate_claude_oauth(
                    credentials, model.name, system_prompt, user_prompt, output_limit
                )
            else:
                result = await _generate_claude(
                    credentials, model.name, system_prompt, user_prompt, output_limit
                )
        else:
            if model.provider in (OPENAI, OPENCODE):
                result = await _generate_openai(
                    base_url,
                    headers,
                    model.name,
                    system_prompt,
                    user_prompt,
                    config,
                    json_mode,
                    provider=model.provider,
                    label="OpenAI" if model.provider == OPENAI else "OpenCode",
                    max_tokens=output_limit,
                    reasoning_effort=reasoning_effort,
                )
            else:
                result = await _generate_ollama(
                    model.provider,
                    base_url,
                    headers,
                    model.name,
                    system_prompt,
                    user_prompt,
                    config,
                    json_mode,
                )
    except Exception as exc:
        # The request was sent and failed: record it, then let the caller handle it.
        ledger.record(
            LLMResult(
                text="",
                prompt_tokens=None,
                completion_tokens=None,
                latency_ms=_elapsed_ms(started),
                provider=model.provider,
                model=model.name,
                ok=False,
                error_class=_error_class(exc),
            ),
            purpose=purpose,
            review_id=review_id,
            thread_id=thread_id,
        )
        raise

    ledger.record(result, purpose=purpose, review_id=review_id, thread_id=thread_id)
    return result


async def _generate_claude(
    credentials: LLMCredentials,
    name: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
) -> LLMResult:
    if not credentials.api_key:
        raise LLMError("No Claude API key configured. Add one in Settings.")

    from anthropic import APIError, AsyncAnthropic

    client = AsyncAnthropic(
        api_key=credentials.api_key, base_url=credentials.base_url or None
    )
    started = time.monotonic()
    try:
        # No `temperature`: newer Claude models reject it (see `claude_message_payload`).
        message = await client.messages.create(
            model=name,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except APIError as exc:
        raise LLMError(f"Claude API error: {getattr(exc, 'message', str(exc))}") from exc
    finally:
        await client.close()

    if getattr(message, "stop_reason", None) == "max_tokens":
        raise _truncation_error("Claude", name, max_tokens)

    usage = getattr(message, "usage", None)
    prompt_tokens, completion_tokens = claude_usage(
        {
            "usage": {
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
            }
        }
    )
    text = "".join(block.text for block in message.content if getattr(block, "type", "") == "text")
    return LLMResult(
        text=text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=_elapsed_ms(started),
        provider=CLAUDE,
        model=name,
    )


async def _generate_claude_oauth(
    credentials: LLMCredentials,
    name: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
) -> LLMResult:
    """One Messages call with a Claude sign-in's bearer token (httpx, not the SDK).

    The SDK's API-key auth always wins when an `ANTHROPIC_API_KEY` happens to exist in the process
    environment, which would send the OAuth access token as `x-api-key`; this transport owns its
    headers instead, and pins the beta header and preamble the OAuth endpoint requires.
    """
    if not credentials.api_key:
        raise LLMError("The Claude sign-in has no access token. Sign in again in Settings.")

    started = time.monotonic()
    body = await _post_claude_messages(
        claude_messages_url(credentials.base_url),
        claude_oauth_headers(credentials.api_key),
        claude_message_payload(name, system_prompt, user_prompt, max_tokens, oauth=True),
    )
    if body.get("stop_reason") == "max_tokens":
        raise _truncation_error("Claude", name, max_tokens)

    text = "".join(
        block.get("text", "")
        for block in body.get("content") or []
        if isinstance(block, dict) and block.get("type") == "text"
    )
    prompt_tokens, completion_tokens = claude_usage(body)
    return LLMResult(
        text=text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=_elapsed_ms(started),
        provider=CLAUDE,
        model=name,
    )


async def _generate_openai(
    base_url: str,
    headers: dict[str, str],
    name: str,
    system_prompt: str,
    user_prompt: str,
    config,
    json_mode: bool = False,
    *,
    provider: str = OPENAI,
    label: str = "OpenAI",
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
) -> LLMResult:
    """Chat Completions call; `provider`/`label` name the transport for the ledger and errors."""
    limit = max_tokens or config.llm_max_tokens
    payload: dict = {
        "model": name,
        "temperature": 0,
        "max_tokens": limit,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort

    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=config.llm_timeout_s) as client:
            response = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise LLMError(f"Could not reach {label} at {base_url}: {exc.__class__.__name__}") from exc

    if response.status_code in (401, 403):
        raise LLMError(f"{label} rejected the API key. Check it in Settings.")
    if response.status_code == 404:
        raise LLMError(f"{label} does not have the model '{name}'. Check the model name.")
    if response.status_code != 200:
        raise LLMError(f"{label} returned HTTP {response.status_code}: {response.text[:300]}")

    try:
        body = response.json()
        choice = body["choices"][0]
        text = choice["message"]["content"] or ""
        finish_reason = choice.get("finish_reason")
    except (ValueError, KeyError, IndexError, AttributeError) as exc:
        raise LLMError(f"{label} returned an unexpected response shape") from exc

    if finish_reason == "length":
        raise _truncation_error(label, name, limit, body)

    prompt_tokens, completion_tokens = openai_usage(body)
    return LLMResult(
        text=text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=_elapsed_ms(started),
        provider=provider,
        model=name,
    )


async def _generate_ollama(
    provider: str,
    base_url: str,
    headers: dict[str, str],
    name: str,
    system_prompt: str,
    user_prompt: str,
    config,
    json_mode: bool = False,
) -> LLMResult:
    url = base_url.rstrip("/") + "/api/chat"
    payload = {
        "model": name,
        "stream": False,
        "options": {"temperature": 0.1, "num_ctx": OLLAMA_NUM_CTX},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if json_mode:
        payload["format"] = "json"

    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=config.llm_timeout_s) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise LLMError(f"Could not reach Ollama at {base_url}: {exc.__class__.__name__}") from exc

    if response.status_code in (401, 403):
        raise LLMError("Ollama rejected the API key. Check it in Settings.")
    if response.status_code == 404:
        raise LLMError(
            f"Ollama does not have the model '{name}'. Check the model name in Settings."
        )
    if response.status_code != 200:
        raise LLMError(f"Ollama returned HTTP {response.status_code}: {response.text[:300]}")

    try:
        body = response.json()
        text = body["message"]["content"] or ""
    except (ValueError, KeyError) as exc:
        raise LLMError("Ollama returned an unexpected response shape") from exc

    if body.get("done_reason") == "length":
        raise LLMError(
            f"Ollama stopped at its output limit before finishing the answer from '{name}' "
            "(the context window is full). Shorten the prompt or choose a model with a larger "
            "context."
        )

    # Local models often omit the eval counters entirely; the ledger keeps NULL in that case.
    prompt_tokens, completion_tokens = ollama_usage(body)
    return LLMResult(
        text=text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=_elapsed_ms(started),
        provider=provider,
        model=name,
    )


async def stream(
    credentials: LLMCredentials,
    model: ModelRef,
    system_prompt: str,
    user_prompt: str,
    *,
    on_delta: Callable[[str], None],
    purpose: str,
    review_id: int | None = None,
    thread_id: int | None = None,
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
) -> LLMResult:
    """One streaming completion: `on_delta` receives each text chunk as it arrives.

    Same contract as `generate()` — the assembled text and usage come back in one
    `LLMResult`, and every outcome (success or failure) reaches the ledger. Credentials are
    resolved before recording, so a missing key raises without a ledger row. A cancelled
    call records nothing: partial usage is unknowable.
    """
    config = get_settings()
    output_limit = max_tokens or config.llm_max_tokens
    base_url: str = ""
    headers: dict[str, str] = {}
    if model.provider == CLAUDE:
        if not credentials.api_key:
            raise LLMError(
                "The Claude sign-in has no access token. Sign in again in Settings."
                if credentials.auth_type == AUTH_OAUTH
                else "No Claude API key configured. Add one in Settings."
            )
    else:
        base_url, headers = resolve_endpoint(credentials, model)

    started = time.monotonic()
    try:
        if model.provider == CLAUDE:
            if credentials.auth_type == AUTH_OAUTH:
                result = await _stream_claude_oauth(
                    credentials, model.name, system_prompt, user_prompt, output_limit,
                    on_delta,
                )
            else:
                result = await _stream_claude(
                    credentials, model.name, system_prompt, user_prompt, output_limit,
                    on_delta,
                )
        elif model.provider in (OPENAI, OPENCODE):
            result = await _stream_openai(
                base_url,
                headers,
                model.name,
                system_prompt,
                user_prompt,
                config,
                on_delta,
                provider=model.provider,
                label="OpenAI" if model.provider == OPENAI else "OpenCode",
                max_tokens=output_limit,
                reasoning_effort=reasoning_effort,
            )
        else:
            result = await _stream_ollama(
                model.provider, base_url, headers, model.name, system_prompt, user_prompt,
                config, on_delta,
            )
    except Exception as exc:
        ledger.record(
            LLMResult(
                text="",
                prompt_tokens=None,
                completion_tokens=None,
                latency_ms=_elapsed_ms(started),
                provider=model.provider,
                model=model.name,
                ok=False,
                error_class=_error_class(exc),
            ),
            purpose=purpose,
            review_id=review_id,
            thread_id=thread_id,
        )
        raise

    ledger.record(result, purpose=purpose, review_id=review_id, thread_id=thread_id)
    return result


async def _stream_ollama(
    provider: str,
    base_url: str,
    headers: dict[str, str],
    name: str,
    system_prompt: str,
    user_prompt: str,
    config,
    on_delta: Callable[[str], None],
) -> LLMResult:
    """Ollama NDJSON stream: one JSON object per line, terminal frame has `done: true`."""
    url = base_url.rstrip("/") + "/api/chat"
    payload = {
        "model": name,
        "stream": True,
        "options": {"temperature": 0.1, "num_ctx": OLLAMA_NUM_CTX},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    started = time.monotonic()
    parts: list[str] = []
    terminal: dict = {}
    try:
        async with httpx.AsyncClient(timeout=config.llm_timeout_s) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code in (401, 403):
                    raise LLMError("Ollama rejected the API key. Check it in Settings.")
                if response.status_code == 404:
                    raise LLMError(
                        f"Ollama does not have the model '{name}'. Check the model name in Settings."
                    )
                if response.status_code != 200:
                    await response.aread()
                    raise LLMError(
                        f"Ollama returned HTTP {response.status_code}: {response.text[:300]}"
                    )
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError as exc:
                        raise LLMError("Ollama returned an unexpected response shape") from exc
                    chunk = (event.get("message") or {}).get("content") or ""
                    if chunk:
                        parts.append(chunk)
                        on_delta(chunk)
                    if event.get("done"):
                        terminal = event
                        break
    except httpx.HTTPError as exc:
        raise LLMError(f"Could not reach Ollama at {base_url}: {exc.__class__.__name__}") from exc

    if terminal.get("done_reason") == "length":
        raise LLMError(
            f"Ollama stopped at its output limit before finishing the answer from '{name}' "
            "(the context window is full). Shorten the prompt or choose a model with a larger "
            "context."
        )

    prompt_tokens, completion_tokens = ollama_usage(terminal)
    return LLMResult(
        text="".join(parts),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=_elapsed_ms(started),
        provider=provider,
        model=name,
    )


async def _stream_openai(
    base_url: str,
    headers: dict[str, str],
    name: str,
    system_prompt: str,
    user_prompt: str,
    config,
    on_delta: Callable[[str], None],
    *,
    provider: str = OPENAI,
    label: str = "OpenAI",
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
) -> LLMResult:
    """OpenAI SSE stream: `data:` chunks, usage on the terminal frame, `data: [DONE]` ends."""
    limit = max_tokens or config.llm_max_tokens
    payload: dict = {
        "model": name,
        "temperature": 0,
        "max_tokens": limit,
        "stream": True,
        # Usage arrives on a final choice-less chunk only when this is set.
        "stream_options": {"include_usage": True},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort

    started = time.monotonic()
    parts: list[str] = []
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None
    usage_body: dict | None = None
    try:
        async with httpx.AsyncClient(timeout=config.llm_timeout_s) as client:
            async with client.stream(
                "POST", f"{base_url}/chat/completions", json=payload, headers=headers
            ) as response:
                if response.status_code in (401, 403):
                    raise LLMError(f"{label} rejected the API key. Check it in Settings.")
                if response.status_code == 404:
                    raise LLMError(
                        f"{label} does not have the model '{name}'. Check the model name."
                    )
                if response.status_code != 200:
                    await response.aread()
                    raise LLMError(
                        f"{label} returned HTTP {response.status_code}: {response.text[:300]}"
                    )
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    try:
                        body = json.loads(data)
                    except ValueError as exc:
                        raise LLMError(f"{label} returned an unexpected response shape") from exc
                    choices = body.get("choices") or []
                    if choices:
                        finish_reason = choices[0].get("finish_reason") or finish_reason
                        chunk = (choices[0].get("delta") or {}).get("content") or ""
                        if chunk:
                            parts.append(chunk)
                            on_delta(chunk)
                    if body.get("usage"):
                        usage_body = body
                        prompt_tokens, completion_tokens = openai_usage(body)
    except httpx.HTTPError as exc:
        raise LLMError(f"Could not reach {label} at {base_url}: {exc.__class__.__name__}") from exc

    if finish_reason == "length":
        raise _truncation_error(label, name, limit, usage_body)

    return LLMResult(
        text="".join(parts),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=_elapsed_ms(started),
        provider=provider,
        model=name,
    )


async def _stream_claude(
    credentials: LLMCredentials,
    name: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    on_delta: Callable[[str], None],
) -> LLMResult:
    """Anthropic SDK stream: text deltas, usage merged from message_start/message_delta."""
    if not credentials.api_key:
        raise LLMError("No Claude API key configured. Add one in Settings.")

    from anthropic import APIError, AsyncAnthropic

    client = AsyncAnthropic(
        api_key=credentials.api_key, base_url=credentials.base_url or None
    )
    started = time.monotonic()
    parts: list[str] = []
    try:
        # No `temperature`: newer Claude models reject it (see `claude_message_payload`).
        async with client.messages.stream(
            model=name,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            async for text in stream.text_stream:
                if text:
                    parts.append(text)
                    on_delta(text)
            message = await stream.get_final_message()
    except APIError as exc:
        raise LLMError(f"Claude API error: {getattr(exc, 'message', str(exc))}") from exc
    finally:
        await client.close()

    if getattr(message, "stop_reason", None) == "max_tokens":
        raise _truncation_error("Claude", name, max_tokens)

    usage = getattr(message, "usage", None)
    prompt_tokens, completion_tokens = claude_usage(
        {
            "usage": {
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
            }
        }
    )
    return LLMResult(
        text="".join(parts),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=_elapsed_ms(started),
        provider=CLAUDE,
        model=name,
    )


async def _stream_claude_oauth(
    credentials: LLMCredentials,
    name: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    on_delta: Callable[[str], None],
) -> LLMResult:
    """Anthropic SSE over a bearer token: `content_block_delta` text, usage on start/delta."""
    if not credentials.api_key:
        raise LLMError("The Claude sign-in has no access token. Sign in again in Settings.")

    payload = claude_message_payload(name, system_prompt, user_prompt, max_tokens, oauth=True)
    payload["stream"] = True
    url = claude_messages_url(credentials.base_url)
    headers = claude_oauth_headers(credentials.api_key)

    started = time.monotonic()
    parts: list[str] = []
    events: list[dict] = []
    stop_reason: str | None = None
    try:
        async with httpx.AsyncClient(timeout=get_settings().llm_timeout_s) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code in (401, 403):
                    await response.aread()
                    detail = (response.text or "").strip()[:200]
                    raise LLMError(
                        "Claude rejected the sign-in. Sign in again in Settings."
                        + (f" ({detail})" if detail else ""),
                        response.status_code,
                    )
                if response.status_code == 429:
                    raise LLMError("Claude rate limit reached. Wait a moment and try again.", 429)
                if response.status_code == 404:
                    await response.aread()
                    raise LLMError(
                        f"Claude does not have the model '{name}' for this account. "
                        "Pick another model.",
                        404,
                    )
                if response.status_code != 200:
                    await response.aread()
                    raise LLMError(
                        f"Claude returned HTTP {response.status_code}: {response.text[:300]}",
                        response.status_code,
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        event = json.loads(data)
                    except ValueError as exc:
                        raise LLMError("Claude returned an unexpected response shape") from exc
                    if not isinstance(event, dict):
                        continue
                    events.append(event)
                    if event.get("type") == "error":
                        message = (event.get("error") or {}).get("message") or "stream error"
                        raise LLMError(f"Claude stream error: {message}")
                    if event.get("type") == "content_block_delta":
                        delta = event.get("delta") or {}
                        if delta.get("type") == "text_delta":
                            chunk = delta.get("text") or ""
                            if chunk:
                                parts.append(chunk)
                                on_delta(chunk)
                    elif event.get("type") == "message_delta":
                        stop_reason = (event.get("delta") or {}).get("stop_reason") or stop_reason
    except httpx.HTTPError as exc:
        raise LLMError(f"Could not reach Claude: {exc.__class__.__name__}") from exc

    if stop_reason == "max_tokens":
        raise _truncation_error("Claude", name, max_tokens)

    prompt_tokens, completion_tokens = claude_usage(events)
    return LLMResult(
        text="".join(parts),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=_elapsed_ms(started),
        provider=CLAUDE,
        model=name,
    )


VALID_VERDICTS = ("APPROVE", "REQUEST_CHANGES", "COMMENT")


@dataclass
class ReviewResult:
    findings: list
    verdict: str | None = None
    confidence: int | None = None


def _load_payload(text: str):
    """First parsable JSON value in `text`, tolerating fences and surrounding prose."""
    if text is None:
        raise LLMError(
            "The model returned an empty response. It may have spent its output budget on "
            "reasoning; check the provider's limit and reasoning settings."
        )
    raw = text.strip()
    if not raw:
        raise LLMError(
            "The model returned an empty response. It may have spent its output budget on "
            "reasoning; check the provider's limit and reasoning settings."
        )

    candidates: list[str] = []
    fence = FENCE_RE.search(raw)
    if fence:
        candidates.append(fence.group(1).strip())
    candidates.append(raw)

    for candidate in candidates:
        for attempt in (candidate, _slice_brackets(candidate), _slice_braces(candidate)):
            if not attempt:
                continue
            try:
                parsed = json.loads(attempt)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, (list, dict)):
                return parsed

    raise LLMError(f"Model returned no parsable JSON: {raw[:280]}")


def _normalise_verdict(value) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip().upper().replace("-", "_").replace(" ", "_")
    return candidate if candidate in VALID_VERDICTS else None


def _normalise_confidence(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, int(round(number))))


def extract_review_result(text: str) -> ReviewResult:
    """Parse the review payload: an object with verdict/confidence, or a legacy bare array."""
    payload = _load_payload(text)
    if isinstance(payload, list):
        return ReviewResult(findings=payload)

    findings = payload.get("findings")
    if not isinstance(findings, list):
        for key in ("comments", "results", "threads", "review"):
            if isinstance(payload.get(key), list):
                findings = payload[key]
                break
    if not isinstance(findings, list):
        # A single finding object with no wrapper.
        findings = [payload] if payload.get("filePath") or payload.get("file_path") else []

    return ReviewResult(
        findings=findings,
        verdict=_normalise_verdict(payload.get("verdict")),
        confidence=_normalise_confidence(payload.get("confidence")),
    )


def extract_json_array(text: str) -> list:
    """Pull a JSON array out of a model response (legacy helper)."""
    payload = _load_payload(text)
    if isinstance(payload, list):
        return payload
    for key in ("findings", "comments", "review", "results", "threads"):
        if isinstance(payload.get(key), list):
            return payload[key]
    return [payload]


def extract_json_document(text: str) -> dict | list:
    """Any JSON document the model returned (objects included)."""
    return _load_payload(text)


def _slice_brackets(text: str) -> str | None:
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def _slice_braces(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]
