"""Version-control dispatch.

One URL in, the right provider client out. Everything above this module (ingest, apply,
re-validation) talks in `PullRef` / `PullRequestInfo`, so adding a host means adding one client and
one branch here — not touching the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import get_settings
from app.models.keys import VCS_GITHUB, VCS_GITLAB, VersionControlKey
from app.services import github_service, gitlab_service
from app.services.github_service import GitHubError
from app.services.gitlab_service import GitLabError
from app.services.pull_request import PullRequestInfo

SUPPORTED_HINT = (
    "Use a GitHub pull request URL (https://github.com/<owner>/<repo>/pull/<n>) or a GitLab merge "
    "request URL (https://gitlab.com/<group>/<project>/-/merge_requests/<iid>)."
)


class VCSError(Exception):
    """Any provider failure, already worded for the operator."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class PullRef:
    vcs: str
    host: str
    project: str
    number: int

    @property
    def label(self) -> str:
        separator = "#" if self.vcs == VCS_GITHUB else "!"
        return f"{self.project}{separator}{self.number}"


def parse_pr_url(url: str) -> PullRef:
    text = (url or "").strip()
    if "github.com" in text:
        try:
            owner, repo, number = github_service.parse_pr_url(text)
        except GitHubError as exc:
            raise VCSError(exc.message, 400) from exc
        return PullRef(VCS_GITHUB, "github.com", f"{owner}/{repo}", number)
    if "merge_requests" in text:
        try:
            host, project, iid = gitlab_service.parse_mr_url(text)
        except GitLabError as exc:
            raise VCSError(exc.message, 400) from exc
        return PullRef(VCS_GITLAB, host, project, iid)
    raise VCSError(f"Unsupported pull-request URL. {SUPPORTED_HINT}", 400)


def api_base(key: VersionControlKey, ref: PullRef) -> str:
    """Per-key base URL first, then the environment default for the host kind."""
    if key.base_url:
        return key.base_url
    config = get_settings()
    return config.github_api_url if ref.vcs == VCS_GITHUB else config.gitlab_base_url


async def verify(key: VersionControlKey) -> tuple[bool, str, dict | None]:
    if key.provider == VCS_GITHUB:
        return await github_service.verify_token(key.token, base_url=key.base_url)
    return await gitlab_service.verify_token(key.token, key.effective_base_url)


async def fetch(key: VersionControlKey, ref: PullRef) -> PullRequestInfo:
    base = api_base(key, ref)
    try:
        if ref.vcs == VCS_GITHUB:
            owner, _, repo = ref.project.partition("/")
            return await github_service.fetch_pr(key.token, owner, repo, ref.number, base_url=base)
        return await gitlab_service.fetch_mr(key.token, base, ref.project, ref.number)
    except GitHubError as exc:
        raise VCSError(exc.message, exc.status_code or 502) from exc
    except GitLabError as exc:
        raise VCSError(exc.message, exc.status_code or 502) from exc


async def fetch_diff(key: VersionControlKey, ref: PullRef) -> str:
    base = api_base(key, ref)
    try:
        if ref.vcs == VCS_GITHUB:
            owner, _, repo = ref.project.partition("/")
            return await github_service.fetch_diff(key.token, owner, repo, ref.number, base_url=base)
        return await gitlab_service.fetch_diff(key.token, base, ref.project, ref.number)
    except GitHubError as exc:
        raise VCSError(exc.message, exc.status_code or 502) from exc
    except GitLabError as exc:
        raise VCSError(exc.message, exc.status_code or 502) from exc


async def fetch_comments(key: VersionControlKey, ref: PullRef) -> list[dict]:
    """Existing inline review comments. GitLab discussions are out of scope for this phase."""
    if ref.vcs != VCS_GITHUB:
        return []
    try:
        return await github_service.fetch_review_comments(
            key.token, ref.project, ref.number, base_url=api_base(key, ref)
        )
    except GitHubError as exc:
        raise VCSError(exc.message, exc.status_code or 502) from exc


async def post_reply(
    key: VersionControlKey, ref: PullRef, comment_id: int, body: str
) -> dict:
    """Reply inside one existing review thread."""
    if ref.vcs != VCS_GITHUB:
        raise VCSError("Replying to an existing review thread is GitHub-only in this phase.", 422)
    try:
        return await github_service.post_reply(
            key.token, ref.project, ref.number, comment_id, body, base_url=api_base(key, ref)
        )
    except GitHubError as exc:
        raise VCSError(exc.message, exc.status_code or 502) from exc


async def publish(
    key: VersionControlKey,
    ref: PullRef,
    pull: PullRequestInfo,
    *,
    event: str,
    comments: list[dict],
) -> tuple[dict, list[str]]:
    """Publish the review's inline comments. Returns `(result, warnings)`; raises `VCSError`.

    There is no review body: the comments carry the findings, and a review with nothing to say would
    be noise on the pull request. An approval is the exception — it says something by itself, so an
    empty `comments` list is a valid approval and nothing else.
    """
    if ref.vcs == VCS_GITHUB:
        return await _publish_github(key, ref, pull, event=event, comments=comments)
    return await _publish_gitlab(key, ref, pull, event=event, comments=comments)


async def _publish_github(
    key: VersionControlKey,
    ref: PullRef,
    pull: PullRequestInfo,
    *,
    event: str,
    comments: list[dict],
) -> tuple[dict, list[str]]:
    base = api_base(key, ref)
    payload = {"commit_id": pull.head_sha, "event": event, "comments": comments}
    try:
        response = await github_service.post_review(
            key.token, ref.project, ref.number, payload, base_url=base
        )
    except GitHubError as exc:
        # Without a body there is nothing to fall back to: the rejection is the answer.
        raise VCSError(exc.message, 502) from exc

    return (
        {
            "url": response.get("html_url"),
            "comments_posted": len(comments),
            "review_id": response.get("id"),
        },
        [],
    )


async def _publish_gitlab(
    key: VersionControlKey,
    ref: PullRef,
    pull: PullRequestInfo,
    *,
    event: str,
    comments: list[dict],
) -> tuple[dict, list[str]]:
    base = api_base(key, ref)
    warnings: list[str] = []

    posted = 0
    for comment in comments:
        position = gitlab_service.inline_position(
            comment["path"],
            comment["line"],
            base_sha=pull.base_sha,
            start_sha=pull.start_sha,
            head_sha=pull.head_sha,
        )
        try:
            await gitlab_service.post_discussion(
                key.token, base, ref.project, ref.number, comment["body"], position
            )
            posted += 1
        except GitLabError as exc:
            warnings.append(
                f"Dropped the inline comment on {comment['path']}:{comment['line']} — {exc.message}"
            )

    if event == "APPROVE":
        approved, detail = await gitlab_service.approve(key.token, base, ref.project, ref.number)
        if not approved:
            warnings.append(f"GitLab did not record the approval: {detail}")

    return {"url": pull.html_url, "comments_posted": posted}, warnings
