from __future__ import annotations

import json

from app.services import llm_service
from tests.fixtures import PR_URL, activate, create_llm_key, create_vcs_key, provision
from tests.test_review_pipeline import FINDINGS, configure


def _probe(cloud_models, local_models):
    async def fake_probe(base_url, api_key=None, timeout=10.0, label="Ollama"):
        models = cloud_models if "ollama.com" in base_url else local_models
        if models is None:
            return False, f"Could not reach {label}", None
        return True, f"{len(models)} model(s) available", {"models": models}

    return fake_probe


def test_catalog_lists_both_transports_with_distinct_prefixes(client, monkeypatch):
    monkeypatch.setattr(
        llm_service, "probe_ollama", _probe(["gpt-oss:20b", "gemma4:31b"], ["llama3:8b"])
    )
    create_llm_key(client, provider="ollama_cloud", api_key="cloud-key")
    create_llm_key(client, provider="ollama_local")

    body = client.get("/api/models").json()
    ids = [model["id"] for model in body["models"]]
    assert "ollama-cloud:gpt-oss:20b" in ids
    assert "ollama-cloud:gemma4:31b" in ids
    assert "ollama-local:llama3:8b" in ids

    cloud = next(model for model in body["models"] if model["id"] == "ollama-cloud:gpt-oss:20b")
    assert cloud["provider"] == "ollama-cloud"
    assert cloud["available"] is True
    assert cloud["note"] == "Ollama Cloud"


def test_unreachable_transport_keeps_the_default_model_with_the_reason(client, monkeypatch):
    monkeypatch.setattr(llm_service, "probe_ollama", _probe(None, None))
    create_llm_key(
        client, provider="ollama_cloud", api_key="cloud-key", default_model="gemma4:31b"
    )

    body = client.get("/api/models").json()
    cloud = next(m for m in body["models"] if m["provider"] == "ollama-cloud")
    assert cloud["id"] == "ollama-cloud:gemma4:31b"
    assert cloud["available"] is False
    assert "Could not reach Ollama Cloud" in cloud["note"]


def test_preferred_model_comes_from_the_active_key(client, monkeypatch):
    monkeypatch.setattr(llm_service, "probe_ollama", _probe(["gemma4:31b"], None))
    cloud = create_llm_key(
        client, provider="ollama_cloud", api_key="cloud-key", default_model="gemma4:31b"
    )
    create_vcs_key(client)
    activate(client, llm_key_id=cloud["id"])

    body = client.get("/api/models").json()
    assert body["preferred"] == "ollama-cloud:gemma4:31b"


def test_cloud_model_without_a_key_is_rejected_at_ingest(client, monkeypatch):
    configure(monkeypatch, json.dumps(FINDINGS))
    provision(client, llm="ollama_local")

    response = client.post(
        "/api/reviews", json={"pr_url": PR_URL, "model": "ollama-cloud:gemma4:31b"}
    )
    assert response.status_code == 422
    assert "No Ollama Cloud key configured" in response.json()["detail"]


def test_openai_models_are_listed_when_a_key_exists(client, monkeypatch):
    async def fake_list(api_key, base_url=None, timeout=5.0):
        return [{"id": "gpt-5-codex", "label": "gpt-5-codex"}]

    monkeypatch.setattr(llm_service, "list_openai_models", fake_list)
    create_llm_key(client, provider="openai", api_key="sk-openai-1234567890")

    ids = [model["id"] for model in client.get("/api/models").json()["models"]]
    assert "openai:gpt-5-codex" in ids
