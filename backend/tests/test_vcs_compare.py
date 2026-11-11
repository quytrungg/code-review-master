"""`vcs.compare`: the delta a watch reviews, rendered as a unified diff by both hosts."""

from __future__ import annotations

import asyncio

import pytest

from app.models.keys import VersionControlKey
from app.services import github_service, gitlab_service, vcs
from app.services.github_service import GitHubError
from app.services.gitlab_service import GitLabError

DELTA = """diff --git a/src/billing.py b/src/billing.py
--- a/src/billing.py
+++ b/src/billing.py
@@ -1,2 +1,3 @@
 def charge():
+    total = compute_total()
     return total
"""


class _Response:
    def __init__(self, payload=None, text: str = "", status_code: int = 200) -> None:
        self._payload = payload
        self.text = text
        self.status_code = status_code
        self.headers: dict[str, str] = {}

    def json(self):
        return self._payload


def _github_key() -> VersionControlKey:
    return VersionControlKey(provider="github", token="ghp_test", base_url=None)


def _gitlab_key() -> VersionControlKey:
    return VersionControlKey(provider="gitlab", token="glpat-test", base_url="https://gitlab.example.com")


def test_github_compare_requests_the_dotdotdot_range_and_accepts_a_diff(monkeypatch):
    seen: list[tuple[str, str]] = []

    async def fake_get(token, path, accept="", base_url=None):
        seen.append((path, accept))
        return _Response(text=DELTA)

    monkeypatch.setattr(github_service, "_get", fake_get)

    ref = vcs.PullRef(vcs="github", host="github.com", project="octo/example", number=123)
    diff = asyncio.run(vcs.compare(_github_key(), ref, "old111", "new222"))

    assert diff == DELTA
    assert seen == [
        ("/repos/octo/example/compare/old111...new222", "application/vnd.github.v3.diff")
    ]


def test_a_force_pushed_github_branch_names_the_real_cause(monkeypatch):
    async def unreachable(token, path, accept="", base_url=None):
        raise GitHubError("Pull request not found, or the token cannot see this repository.", 404)

    monkeypatch.setattr(github_service, "_get", unreachable)

    ref = vcs.PullRef(vcs="github", host="github.com", project="octo/example", number=123)
    with pytest.raises(vcs.VCSError) as caught:
        asyncio.run(vcs.compare(_github_key(), ref, "old111", "new222"))

    assert "force-pushed" in caught.value.message


def test_gitlab_compare_renders_each_change_as_a_unified_diff_section(monkeypatch):
    seen: list[str] = []

    async def fake_request(method, base_url, token, path, *, json=None, timeout=30.0):
        seen.append(path)
        return _Response(
            {
                "commits": [{"id": "new222"}],
                "diffs": [
                    {
                        "old_path": "src/billing.py",
                        "new_path": "src/billing.py",
                        "diff": "@@ -1,2 +1,3 @@\n def charge():\n+    total = compute_total()\n     return total\n",
                    },
                    {
                        "old_path": None,
                        "new_path": "src/added.rb",
                        "new_file": True,
                        "diff": "@@ -0,0 +1 @@\n+x\n",
                    },
                ],
            }
        )

    monkeypatch.setattr(gitlab_service, "_request", fake_request)

    ref = vcs.PullRef(vcs="gitlab", host="gitlab.example.com", project="group/sub/project", number=7)
    diff = asyncio.run(vcs.compare(_gitlab_key(), ref, "old111", "new222"))

    assert seen == [
        "/projects/group%2Fsub%2Fproject/repository/compare?from=old111&to=new222"
    ]
    assert diff.count("diff --git") == 2
    assert "diff --git a/src/billing.py b/src/billing.py" in diff
    assert "new file mode 100644" in diff
    assert "src/added.rb" in diff


def test_gitlab_compare_with_nothing_textual_is_422(monkeypatch):
    async def fake_request(method, base_url, token, path, *, json=None, timeout=30.0):
        return _Response({"diffs": [{"old_path": "a.png", "new_path": "a.png", "diff": ""}]})

    monkeypatch.setattr(gitlab_service, "_request", fake_request)

    ref = vcs.PullRef(vcs="gitlab", host="gitlab.example.com", project="group/sub/project", number=7)
    with pytest.raises(vcs.VCSError) as caught:
        asyncio.run(vcs.compare(_gitlab_key(), ref, "old111", "new222"))

    assert "no textual changes" in caught.value.message
    assert caught.value.status_code == 422


def test_gitlab_compare_surfaces_a_rewritten_branch(monkeypatch):
    async def fake_request(method, base_url, token, path, *, json=None, timeout=30.0):
        raise GitLabError("Merge request not found, or the token cannot see this project.", 404)

    monkeypatch.setattr(gitlab_service, "_request", fake_request)

    ref = vcs.PullRef(vcs="gitlab", host="gitlab.example.com", project="group/sub/project", number=7)
    with pytest.raises(vcs.VCSError) as caught:
        asyncio.run(vcs.compare(_gitlab_key(), ref, "old111", "new222"))

    assert "rewritten" in caught.value.message
