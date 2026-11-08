from __future__ import annotations

import asyncio

import pytest

from app.models.keys import VersionControlKey
from app.services import gitlab_service, vcs
from app.services.gitlab_service import GitLabError
from app.services.pull_request import PullRequestInfo
from tests.fixtures import MR_URL, create_vcs_key

MR_DIFF = """diff --git a/app/services/token_verifier.rb b/app/services/token_verifier.rb
--- a/app/services/token_verifier.rb
+++ b/app/services/token_verifier.rb
@@ -12,7 +12,9 @@ module Auth
     def verify(token)
-      payload = JWT.decode(token, nil, false).first
+      payload = JWT.decode(token, ENV.fetch("JWT_SECRET"), true, algorithm: "HS256").first
"""


def _key():
    return VersionControlKey(
        provider="gitlab", token="glpat-test", base_url="https://gitlab.example.com"
    )


def _pull() -> PullRequestInfo:
    return PullRequestInfo(
        vcs="gitlab",
        project="group/sub/project",
        number=7,
        title="Verify JWT signatures",
        state="opened",
        draft=False,
        head_sha="head111",
        base_sha="base111",
        start_sha="start111",
        base_ref="main",
        html_url=MR_URL,
        author="octocat",
        body=None,
        additions=0,
        deletions=0,
        changed_files=1,
    )


def test_parse_mr_url_supports_nested_groups_and_self_hosted_hosts():
    host, project, iid = gitlab_service.parse_mr_url(
        "https://gitlab.example.com/group/sub/project/-/merge_requests/42"
    )
    assert (host, project, iid) == ("gitlab.example.com", "group/sub/project", 42)

    host, project, iid = gitlab_service.parse_mr_url(
        "https://gitlab.com/octo/example/-/merge_requests/7/files"
    )
    assert (host, project, iid) == ("gitlab.com", "octo/example", 7)


def test_parse_mr_url_rejects_a_pull_url():
    with pytest.raises(GitLabError):
        gitlab_service.parse_mr_url("https://github.com/octo/example/pull/1")


def test_diff_rendering_adds_unified_headers():
    rendered = gitlab_service._render_change(
        {
            "old_path": "app/services/token_verifier.rb",
            "new_path": "app/services/token_verifier.rb",
            "diff": "@@ -1,2 +1,3 @@\n a\n+b\n",
        }
    )
    assert rendered.startswith("diff --git a/app/services/token_verifier.rb b/app/services/token_verifier.rb")
    assert "--- a/app/services/token_verifier.rb" in rendered
    assert "+++ b/app/services/token_verifier.rb" in rendered
    assert rendered.endswith(" a\n+b\n")

    added = gitlab_service._render_change(
        {"old_path": None, "new_path": "new.rb", "new_file": True, "diff": "@@ -0,0 +1 @@\n+x\n"}
    )
    assert "new file mode 100644" in added
    assert "--- /dev/null" in added


def test_inline_position_carries_the_diff_refs():
    position = gitlab_service.inline_position(
        "app/file.rb", 14, base_sha="b", start_sha="s", head_sha="h"
    )
    assert position == {
        "position_type": "text",
        "base_sha": "b",
        "start_sha": "s",
        "head_sha": "h",
        "old_path": "app/file.rb",
        "new_path": "app/file.rb",
        "new_line": 14,
    }


def test_publish_posts_one_discussion_per_comment(monkeypatch):
    calls: list[tuple] = []

    async def discussion(token, base_url, project, iid, body, position):
        calls.append(("discussion", body, position))
        return {"id": 2}

    async def approve(token, base_url, project, iid):
        calls.append(("approve", iid))
        return True, "Approved"

    monkeypatch.setattr(gitlab_service, "post_discussion", discussion)
    monkeypatch.setattr(gitlab_service, "approve", approve)

    ref = vcs.PullRef(vcs="gitlab", host="gitlab.example.com", project="group/sub/project", number=7)
    result, warnings = asyncio.run(
        vcs.publish(
            _key(),
            ref,
            _pull(),
            event="APPROVE",
            comments=[
                {"path": "app/a.rb", "line": 4, "body": "first"},
                {"path": "app/b.rb", "line": 9, "body": "second"},
            ],
        )
    )

    assert [call[0] for call in calls] == ["discussion", "discussion", "approve"]
    assert calls[0][2]["new_line"] == 4
    assert calls[0][2]["head_sha"] == "head111"
    assert result == {"url": MR_URL, "comments_posted": 2}
    assert warnings == []


def test_publish_keeps_going_when_one_inline_comment_is_rejected(monkeypatch):
    async def discussion(token, base_url, project, iid, body, position):
        if position["new_path"] == "app/b.rb":
            raise GitLabError("GitLab rejected the inline comment: line is not part of the diff", 422)
        return {"id": 2}

    async def approve(token, base_url, project, iid):
        return False, "Approval is not allowed for the author"

    monkeypatch.setattr(gitlab_service, "post_discussion", discussion)
    monkeypatch.setattr(gitlab_service, "approve", approve)

    ref = vcs.PullRef(vcs="gitlab", host="gitlab.example.com", project="group/sub/project", number=7)
    result, warnings = asyncio.run(
        vcs.publish(
            _key(),
            ref,
            _pull(),
            event="APPROVE",
            comments=[
                {"path": "app/a.rb", "line": 4, "body": "first"},
                {"path": "app/b.rb", "line": 9, "body": "second"},
            ],
        )
    )

    assert result["comments_posted"] == 1
    assert any("app/b.rb:9" in warning for warning in warnings)
    assert any("approval" in warning for warning in warnings)


def test_gitlab_key_is_accepted_by_the_keys_api(client):
    key = create_vcs_key(client, provider="gitlab", token="glpat-abcdef123456")
    assert key["provider"] == "gitlab"
    assert key["token_masked"].endswith("3456")


def test_mr_url_parses_through_the_dispatcher():
    ref = vcs.parse_pr_url(MR_URL)
    assert (ref.vcs, ref.project, ref.number) == ("gitlab", "octo/example", 7)
    assert ref.label == "octo/example!7"


def test_unsupported_url_names_both_hosts():
    with pytest.raises(vcs.VCSError) as excinfo:
        vcs.parse_pr_url("https://bitbucket.org/team/repo/pull-requests/1")
    assert "GitHub" in excinfo.value.message and "GitLab" in excinfo.value.message
