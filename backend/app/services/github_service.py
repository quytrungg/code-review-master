from __future__ import annotations

import re

import httpx

from app.core.config import get_settings
from app.services.pull_request import PullRequestInfo

GITHUB_API_ACCEPT = "application/vnd.github+json"
GITHUB_DIFF_ACCEPT = "application/vnd.github.v3.diff"

PR_URL_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)/pull/(?P<number>\d+)/?(?:[?#].*)?$"
)


class GitHubError(Exception):
    """Raised when GitHub cannot satisfy a request the review depends on."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


__all__ = [
    "GitHubError",
    "PullRequestInfo",
    "fetch_diff",
    "fetch_pr",
    "fetch_review_comments",
    "fetch_review_id_comments",
    "parse_pr_url",
    "post_reply",
    "post_review",
    "verify_token",
]

COMMENTS_PAGE_SIZE = 100
MAX_COMMENT_PAGES = 10


def parse_pr_url(url: str) -> tuple[str, str, int]:
    match = PR_URL_RE.match((url or "").strip())
    if not match:
        raise GitHubError(
            "Not a GitHub pull request URL. Expected https://github.com/<owner>/<repo>/pull/<number>"
        )
    return match.group("owner"), match.group("repo"), int(match.group("number"))


def _headers(token: str, accept: str = GITHUB_API_ACCEPT) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ai-code-review-assistant",
    }


async def verify_token(
    token: str, base_url: str | None = None
) -> tuple[bool, str, dict | None]:
    """Check a personal access token against GET /user."""
    settings = get_settings()
    api = (base_url or settings.github_api_url).rstrip("/")
    try:
        async with httpx.AsyncClient(base_url=api, timeout=10.0) as client:
            response = await client.get("/user", headers=_headers(token))
    except httpx.HTTPError as exc:
        return False, f"Could not reach GitHub: {exc.__class__.__name__}", None

    if response.status_code == 200:
        login = response.json().get("login", "unknown")
        return True, f"Authenticated as {login}", {"login": login}
    if response.status_code == 401:
        return False, "GitHub rejected the token (401 Unauthorized)", None
    return False, f"GitHub returned HTTP {response.status_code}", None


async def _get(
    token: str, path: str, accept: str = GITHUB_API_ACCEPT, base_url: str | None = None
) -> httpx.Response:
    settings = get_settings()
    api = (base_url or settings.github_api_url).rstrip("/")
    try:
        async with httpx.AsyncClient(
            base_url=api, timeout=settings.github_timeout_s
        ) as client:
            response = await client.get(path, headers=_headers(token, accept))
    except httpx.HTTPError as exc:
        raise GitHubError(f"Could not reach GitHub: {exc.__class__.__name__}") from exc

    if response.status_code == 401:
        raise GitHubError("GitHub rejected the token (401). Check the token in Settings.", 401)
    if response.status_code == 403:
        rate_limited = response.headers.get("x-ratelimit-remaining") == "0"
        raise GitHubError(
            "GitHub rate limit reached. Try again later." if rate_limited else "GitHub denied access (403).",
            403,
        )
    if response.status_code == 404:
        raise GitHubError("Pull request not found, or the token cannot see this repository.", 404)
    if response.status_code >= 400:
        raise GitHubError(f"GitHub returned HTTP {response.status_code}.", response.status_code)
    return response


async def fetch_pr(
    token: str, owner: str, repo: str, number: int, base_url: str | None = None
) -> PullRequestInfo:
    response = await _get(token, f"/repos/{owner}/{repo}/pulls/{number}", base_url=base_url)
    try:
        body = response.json()
    except ValueError as exc:
        raise GitHubError("GitHub returned a malformed response.") from exc

    base = body.get("base") or {}
    return PullRequestInfo(
        vcs="github",
        project=f"{owner}/{repo}",
        number=number,
        title=body.get("title") or f"{owner}/{repo}#{number}",
        state=body.get("state", "unknown"),
        draft=bool(body.get("draft")),
        head_sha=(body.get("head") or {}).get("sha", ""),
        base_sha=base.get("sha", ""),
        start_sha=base.get("sha", ""),
        base_ref=base.get("ref", ""),
        html_url=body.get("html_url") or f"https://github.com/{owner}/{repo}/pull/{number}",
        author=(body.get("user") or {}).get("login", "unknown"),
        body=body.get("body"),
        additions=body.get("additions") or 0,
        deletions=body.get("deletions") or 0,
        changed_files=body.get("changed_files") or 0,
    )


async def fetch_diff(
    token: str, owner: str, repo: str, number: int, base_url: str | None = None
) -> str:
    response = await _get(
        token,
        f"/repos/{owner}/{repo}/pulls/{number}",
        accept=GITHUB_DIFF_ACCEPT,
        base_url=base_url,
    )
    text = response.text
    if not text.strip():
        raise GitHubError("GitHub returned an empty diff for this pull request.", 422)
    return text


async def post_review(
    token: str,
    repo_full_name: str,
    number: int,
    payload: dict,
    base_url: str | None = None,
) -> dict:
    """Create a pull-request review with inline comments (used by Phase 5)."""
    settings = get_settings()
    api = (base_url or settings.github_api_url).rstrip("/")
    try:
        async with httpx.AsyncClient(
            base_url=api, timeout=settings.github_timeout_s
        ) as client:
            response = await client.post(
                f"/repos/{repo_full_name}/pulls/{number}/reviews",
                headers=_headers(token),
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise GitHubError(f"Could not reach GitHub: {exc.__class__.__name__}") from exc

    if response.status_code in (200, 201):
        try:
            return response.json()
        except ValueError:
            return {}

    detail = ""
    try:
        detail = response.json().get("message", "")
    except ValueError:
        detail = response.text[:300]
    if response.status_code == 422:
        raise GitHubError(f"GitHub rejected the review: {detail or 'invalid comment anchor'}", 422)
    if response.status_code == 401:
        raise GitHubError("GitHub rejected the token (401).", 401)
    raise GitHubError(f"GitHub returned HTTP {response.status_code}: {detail}", response.status_code)


def _comment_list(response: httpx.Response) -> list[dict]:
    try:
        body = response.json()
    except ValueError as exc:
        raise GitHubError("GitHub returned a malformed comments response.") from exc
    if not isinstance(body, list):
        raise GitHubError("GitHub returned a malformed comments response.")
    return [item for item in body if isinstance(item, dict)]


async def fetch_review_comments(
    token: str, repo_full_name: str, number: int, base_url: str | None = None
) -> list[dict]:
    """Every review comment on the pull request, all pages, oldest first."""
    comments: list[dict] = []
    for page in range(1, MAX_COMMENT_PAGES + 1):
        path = (
            f"/repos/{repo_full_name}/pulls/{number}/comments"
            f"?per_page={COMMENTS_PAGE_SIZE}&page={page}&sort=created&direction=asc"
        )
        batch = _comment_list(await _get(token, path, base_url=base_url))
        comments.extend(batch)
        if len(batch) < COMMENTS_PAGE_SIZE:
            break
    return comments


async def fetch_review_id_comments(
    token: str, repo_full_name: str, number: int, review_id: int, base_url: str | None = None
) -> list[dict]:
    """The inline comments a specific review created, used to backfill root ids after apply.

    Read from the pull request's comment list and filtered on `pull_request_review_id`, not from
    `/reviews/{review_id}/comments`: that review-scoped endpoint returns `line: null` and
    `original_line: null` for the same comments, which starves the anchor matching that needs a line.
    """
    comments: list[dict] = []
    for page in range(1, MAX_COMMENT_PAGES + 1):
        path = (
            f"/repos/{repo_full_name}/pulls/{number}/comments"
            f"?per_page={COMMENTS_PAGE_SIZE}&page={page}"
        )
        batch = _comment_list(await _get(token, path, base_url=base_url))
        comments.extend(batch)
        if len(batch) < COMMENTS_PAGE_SIZE:
            break
    return [
        comment for comment in comments if comment.get("pull_request_review_id") == review_id
    ]


async def post_reply(
    token: str,
    repo_full_name: str,
    number: int,
    comment_id: int,
    body: str,
    base_url: str | None = None,
) -> dict:
    """Reply inside an existing review thread (POST …/pulls/{n}/comments/{id}/replies)."""
    settings = get_settings()
    api = (base_url or settings.github_api_url).rstrip("/")
    try:
        async with httpx.AsyncClient(
            base_url=api, timeout=settings.github_timeout_s
        ) as client:
            response = await client.post(
                f"/repos/{repo_full_name}/pulls/{number}/comments/{comment_id}/replies",
                headers=_headers(token),
                json={"body": body},
            )
    except httpx.HTTPError as exc:
        raise GitHubError(f"Could not reach GitHub: {exc.__class__.__name__}") from exc

    if response.status_code in (200, 201):
        try:
            return response.json()
        except ValueError:
            return {}

    detail = ""
    try:
        detail = response.json().get("message", "")
    except ValueError:
        detail = response.text[:300]
    if response.status_code == 401:
        raise GitHubError("GitHub rejected the token (401).", 401)
    raise GitHubError(f"GitHub returned HTTP {response.status_code}: {detail}", response.status_code)
