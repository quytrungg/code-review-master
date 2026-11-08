from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

from app.core.config import get_settings

ANTHROPIC_VERSION = "2023-06-01"
OLLAMA_NUM_CTX = 32768

CLAUDE = "claude"
OPENAI = "openai"
# Hosted Ollama (https://ollama.com/api, bearer API key) — the default Ollama transport.
OLLAMA_CLOUD = "ollama-cloud"
# Ollama running on the operator's machine (no authentication).
OLLAMA_LOCAL = "ollama-local"
# Pre-Phase-6 ids: "ollama:<tag>" meant the local daemon. It now resolves to the hosted API,
# because cloud is the default; local models are addressed as "ollama-local:<tag>".
LEGACY_OLLAMA = "ollama"

OLLAMA_PROVIDERS = (OLLAMA_CLOUD, OLLAMA_LOCAL)
MODEL_PROVIDERS = (CLAUDE, OPENAI, *OLLAMA_PROVIDERS)

# Model-id prefix ↔ database provider name (`llm_keys.provider`).
DB_PROVIDER = {
    CLAUDE: "claude",
    OPENAI: "openai",
    OLLAMA_CLOUD: "ollama_cloud",
    OLLAMA_LOCAL: "ollama_local",
}
MODEL_PROVIDER = {value: key for key, value in DB_PROVIDER.items()}

MODEL_ID_HINT = (
    "Expected 'claude:<model>', 'openai:<model>', 'ollama-cloud:<tag>' or 'ollama-local:<tag>'."
)

CLAUDE_FALLBACK = [
    {"id": "claude-sonnet-4-5-20250929", "label": "Claude Sonnet 4.5"},
    {"id": "claude-3-5-haiku-20241022", "label": "Claude 3.5 Haiku"},
]

OPENAI_FALLBACK = [
    {"id": "gpt-5-codex", "label": "GPT-5 Codex"},
    {"id": "gpt-4.1", "label": "GPT-4.1"},
]

FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class LLMError(Exception):
    """Model call or response-shape failure, surfaced to the operator verbatim."""


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
    if model.provider == CLAUDE:
        if not credentials.api_key:
            raise LLMError("No Claude API key configured. Add one in Settings.")
        return (credentials.base_url or "https://api.anthropic.com").rstrip("/"), {}
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


async def probe_openai(
    api_key: str, base_url: str | None = None, timeout: float = 10.0
) -> tuple[bool, str, dict | None]:
    """Verify an OpenAI-compatible key against `GET /models`."""
    base = (base_url or "https://api.openai.com/v1").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{base}/models", headers={"Authorization": f"Bearer {api_key}"}
            )
    except httpx.HTTPError as exc:
        return False, f"Could not reach OpenAI at {base}: {exc.__class__.__name__}", None

    if response.status_code in (401, 403):
        return False, "OpenAI rejected the API key", None
    if response.status_code != 200:
        return False, f"OpenAI returned HTTP {response.status_code}", None
    try:
        models = [entry.get("id", "") for entry in response.json().get("data", [])]
    except (ValueError, AttributeError):
        models = []
    return True, f"{len([m for m in models if m])} model(s) available", {"models": sorted(m for m in models if m)}


async def list_claude_models(
    api_key: str, base_url: str | None = None, timeout: float = 5.0
) -> list[dict[str, str]]:
    """Installed/available Claude models; falls back to a static list when the API is down."""
    url = (base_url or "https://api.anthropic.com").rstrip("/") + "/v1/models?limit=20"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                url, headers={"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION}
            )
        if response.status_code == 200:
            models = [
                {"id": entry["id"], "label": entry.get("display_name") or entry["id"]}
                for entry in response.json().get("data", [])
                if entry.get("id")
            ]
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


async def generate(
    credentials: LLMCredentials,
    model: ModelRef,
    system_prompt: str,
    user_prompt: str,
    json_mode: bool = False,
) -> str:
    """One non-streaming completion, returned as raw text.

    `json_mode` asks the provider to constrain output to JSON (Ollama's `format: json`,
    OpenAI's `response_format`). Discussion replies are prose, so they pass False.
    """
    config = get_settings()
    if model.provider == CLAUDE:
        return await _generate_claude(
            credentials, model.name, system_prompt, user_prompt, config.llm_max_tokens
        )
    base_url, headers = resolve_endpoint(credentials, model)
    if model.provider == OPENAI:
        return await _generate_openai(
            base_url, headers, model.name, system_prompt, user_prompt, config, json_mode
        )
    return await _generate_ollama(
        base_url, headers, model.name, system_prompt, user_prompt, config, json_mode
    )


async def _generate_claude(
    credentials: LLMCredentials,
    name: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
) -> str:
    if not credentials.api_key:
        raise LLMError("No Claude API key configured. Add one in Settings.")

    from anthropic import APIError, AsyncAnthropic

    client = AsyncAnthropic(
        api_key=credentials.api_key, base_url=credentials.base_url or None
    )
    try:
        message = await client.messages.create(
            model=name,
            max_tokens=max_tokens,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except APIError as exc:
        raise LLMError(f"Claude API error: {getattr(exc, 'message', str(exc))}") from exc
    finally:
        await client.close()

    return "".join(block.text for block in message.content if getattr(block, "type", "") == "text")


async def _generate_openai(
    base_url: str,
    headers: dict[str, str],
    name: str,
    system_prompt: str,
    user_prompt: str,
    config,
    json_mode: bool = False,
) -> str:
    payload: dict = {
        "model": name,
        "temperature": 0,
        "max_tokens": config.llm_max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    try:
        async with httpx.AsyncClient(timeout=config.llm_timeout_s) as client:
            response = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise LLMError(f"Could not reach OpenAI at {base_url}: {exc.__class__.__name__}") from exc

    if response.status_code in (401, 403):
        raise LLMError("OpenAI rejected the API key. Check it in Settings.")
    if response.status_code == 404:
        raise LLMError(f"OpenAI does not have the model '{name}'. Check the model name.")
    if response.status_code != 200:
        raise LLMError(f"OpenAI returned HTTP {response.status_code}: {response.text[:300]}")

    try:
        return response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError) as exc:
        raise LLMError("OpenAI returned an unexpected response shape") from exc


async def _generate_ollama(
    base_url: str,
    headers: dict[str, str],
    name: str,
    system_prompt: str,
    user_prompt: str,
    config,
    json_mode: bool = False,
) -> str:
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
        return response.json()["message"]["content"]
    except (ValueError, KeyError) as exc:
        raise LLMError("Ollama returned an unexpected response shape") from exc


VALID_VERDICTS = ("APPROVE", "REQUEST_CHANGES", "COMMENT")


@dataclass
class ReviewResult:
    findings: list
    verdict: str | None = None
    confidence: int | None = None


def _load_payload(text: str):
    """First parsable JSON value in `text`, tolerating fences and surrounding prose."""
    if text is None:
        raise LLMError("Model returned an empty response")
    raw = text.strip()
    if not raw:
        raise LLMError("Model returned an empty response")

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
