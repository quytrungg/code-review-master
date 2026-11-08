SAMPLE_DIFF = """diff --git a/src/services/auth.py b/src/services/auth.py
index 1111111..2222222 100644
--- a/src/services/auth.py
+++ b/src/services/auth.py
@@ -10,4 +10,5 @@ def handler(request):
     limit = 10
-    rows = db.query(Model).all()
+    rows = db.query(Model).limit(limit).all()
+    log.debug("fetched %s rows", len(rows))
     return rows
diff --git a/package-lock.json b/package-lock.json
index 3333333..4444444 100644
--- a/package-lock.json
+++ b/package-lock.json
@@ -1,3 +1,3 @@
-  "old": true
+  "new": true
diff --git a/assets/logo.png b/assets/logo.png
index 5555555..6666666 100644
Binary files a/assets/logo.png and b/assets/logo.png differ
diff --git a/src/deleted.py b/src/deleted.py
deleted file mode 100644
--- a/src/deleted.py
+++ /dev/null
@@ -1,2 +0,0 @@
-print("gone")
-print("gone too")
"""

PR_URL = "https://github.com/octo/example/pull/123"
MR_URL = "https://gitlab.com/octo/example/-/merge_requests/7"

GITHUB_TOKEN = "ghp_test_token_123456"


def create_vcs_key(client, provider="github", token=GITHUB_TOKEN, base_url=None):
    payload = {"provider": provider, "token": token}
    if base_url:
        payload["base_url"] = base_url
    response = client.post("/api/keys/version-control", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def create_llm_key(client, provider="ollama_local", api_key=None, base_url=None, default_model=None):
    payload = {"provider": provider}
    if api_key is not None:
        payload["api_key"] = api_key
    if base_url:
        payload["base_url"] = base_url
    if default_model:
        payload["default_model"] = default_model
    response = client.post("/api/keys/llm", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def activate(client, version_control_key_id=None, llm_key_id=None):
    payload = {}
    if version_control_key_id is not None:
        payload["version_control_key_id"] = version_control_key_id
    if llm_key_id is not None:
        payload["llm_key_id"] = llm_key_id
    response = client.put("/api/settings", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def accept_findings(client, review) -> dict:
    """Accept every AI finding, so an apply has something to publish.

    The decision carries the finding text as the summary, which is what apply would post anyway —
    it keeps the tests free of a model call.
    """
    for thread in review["threads"]:
        if thread["origin"] != "AI_GENERATED":
            continue
        first = thread["rounds"][0]
        if first["status"] != "drafting":
            continue
        text = thread["messages"][-1]["content"] if thread["messages"] else "Finding"
        decided = client.post(
            f"/api/reviews/{review['id']}/rounds/{first['id']}/decision",
            json={"decision": "accept", "summary": text},
        )
        assert decided.status_code == 200, decided.text
    return client.get(f"/api/reviews/{review['id']}").json()


def provision(
    client,
    *,
    vcs="github",
    vcs_token=GITHUB_TOKEN,
    vcs_base_url=None,
    llm="ollama_local",
    api_key=None,
    llm_base_url=None,
    default_model=None,
):
    """Reset credentials, then create one key per family and activate both.

    The suite shares one database for the whole session, so a fresh slate keeps later tests
    (model catalogues, provider guards) independent of what earlier tests configured.
    """
    for key in client.get("/api/keys/version-control").json():
        client.delete(f"/api/keys/version-control/{key['id']}")
    for key in client.get("/api/keys/llm").json():
        client.delete(f"/api/keys/llm/{key['id']}")

    version_control = create_vcs_key(
        client, provider=vcs, token=vcs_token, base_url=vcs_base_url
    )
    model = create_llm_key(
        client,
        provider=llm,
        api_key=api_key,
        base_url=llm_base_url,
        default_model=default_model,
    )
    activate(client, version_control["id"], model["id"])
    return version_control, model
