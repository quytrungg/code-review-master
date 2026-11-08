"""GitLab merge requests: fetch, diff and publish.

GitLab has no "create a review with N inline comments" endpoint. Publishing therefore means one
discussion per accepted finding, each carrying a `position` built from the merge request's diff
refs. Approval is a separate, optional call.
"""

from __future__ import annotations

import re
from urllib.parse import quote

import httpx

from app.services.pull_request import PullRequestInfo

MR_URL_RE = re.compile(
    r"^https?://(?P<host>[^/]+)/(?P<path>.+?)/-/merge_requests/(?P<iid>\d+)(?:[/?#].*)?$"
)

MAX_DIFF_PAGES = 20
PER_PAGE = 100


class GitLabError(Exception):
    """Raised when GitLab cannot satisfy a request the review depends on."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def parse_mr_url(url: str) -> tuple[str, str, int]:
    """Return `(host, project_path, iid)` for a merge-request URL."""
    match = MR_URL_RE.match((url or "").strip())
    if not match:
        raise GitLabError(
            "Not a GitLab merge request URL. Expected "
            "https://gitlab.com/<group>/<project>/-/merge_requests/<iid>"
        )
    return match.group("host"), match.group("path"), int(match.group("iid"))


def _api_base(base_url: str) -> str:
    base = (base_url or "https://gitlab.com").rstrip("/")
    return f"{base}/api/v4"


def _headers(token: str) -> dict[str, str]:
    return {"PRIVATE-TOKEN": token, "Accept": "application/json"}


def _project(project_path: str) -> str:
    return quote(project_path, safe="")


async def _request(
    method: str,
    base_url: str,
    token: str,
    path: str,
    *,
    json: dict | None = None,
    timeout: float = 30.0,
) -> httpx.Response:
    api = _api_base(base_url)
    try:
        async with httpx.AsyncClient(base_url=api, timeout=timeout) as client:
            response = await client.request(method, path, headers=_headers(token), json=json)
    except httpx.HTTPError as exc:
        raise GitLabError(f"Could not reach GitLab: {exc.__class__.__name__}") from exc

    if response.status_code == 401:
        raise GitLabError("GitLab rejected the token (401). Check the token in Settings.", 401)
    if response.status_code == 403:
        raise GitLabError("GitLab denied access (403). The token needs `api` scope.", 403)
    if response.status_code == 404:
        raise GitLabError(
            "Merge request not found, or the token cannot see this project.", 404
        )
    return response


def _message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(payload, dict):
        return str(payload.get("message") or payload.get("error") or payload)[:300]
    return str(payload)[:300]


async def verify_token(token: str, base_url: str) -> tuple[bool, str, dict | None]:
    """Check a personal access token against GET /user."""
    try:
        response = await _request("GET", base_url, token, "/user", timeout=10.0)
    except GitLabError as exc:
        return False, exc.message, None
    if response.status_code == 200:
        username = response.json().get("username", "unknown")
        return True, f"Authenticated as {username}", {"username": username}
    return False, f"GitLab returned HTTP {response.status_code}", None


def _is_draft(mr: dict) -> bool:
    title = (mr.get("title") or "").strip()
    return bool(mr.get("draft") or mr.get("work_in_progress")) or title.startswith(("Draft:", "[Draft]"))


async def fetch_mr(token: str, base_url: str, project_path: str, iid: int) -> PullRequestInfo:
    path = f"/projects/{_project(project_path)}/merge_requests/{iid}"
    response = await _request("GET", base_url, token, path)
    if response.status_code >= 400:
        raise GitLabError(f"GitLab returned HTTP {response.status_code}: {_message(response)}")
    try:
        body = response.json()
    except ValueError as exc:
        raise GitLabError("GitLab returned a malformed response.") from exc

    refs = body.get("diff_refs") or {}
    return PullRequestInfo(
        vcs="gitlab",
        project=project_path,
        number=iid,
        title=body.get("title") or f"{project_path}!{iid}",
        state=body.get("state", "unknown"),
        draft=_is_draft(body),
        head_sha=refs.get("head_sha") or (body.get("sha") or ""),
        base_sha=refs.get("base_sha") or "",
        start_sha=refs.get("start_sha") or "",
        base_ref=body.get("target_branch") or "",
        html_url=body.get("web_url") or f"https://{base_url}/-/{iid}",
        author=(body.get("author") or {}).get("username", "unknown"),
        body=body.get("description"),
        additions=0,
        deletions=0,
        changed_files=int(body.get("changes_count") or 0) if str(body.get("changes_count", "")).isdigit() else 0,
    )


def _render_change(change: dict) -> str:
    """Turn one GitLab `changes`/`diffs` entry into a unified-diff file section."""
    old_path = change.get("old_path") or change.get("new_path")
    new_path = change.get("new_path") or old_path
    body = (change.get("diff") or "").rstrip("\n")
    if not body:
        return ""

    lines = [f"diff --git a/{old_path} b/{new_path}"]
    if change.get("new_file"):
        lines += ["new file mode 100644", "--- /dev/null", f"+++ b/{new_path}"]
    elif change.get("deleted_file"):
        lines += ["deleted file mode 100644", f"--- a/{old_path}", "+++ /dev/null"]
    elif change.get("renamed_file"):
        lines += [f"rename from {old_path}", f"rename to {new_path}"]
        lines += [f"--- a/{old_path}", f"+++ b/{new_path}"]
    else:
        lines += [f"--- a/{old_path}", f"+++ b/{new_path}"]
    return "\n".join(lines) + "\n" + body + "\n"


async def fetch_diff(token: str, base_url: str, project_path: str, iid: int) -> str:
    """Full merge-request diff, paginated and re-rendered as a unified diff."""
    sections: list[str] = []
    page = 1
    while page and page <= MAX_DIFF_PAGES:
        path = (
            f"/projects/{_project(project_path)}/merge_requests/{iid}"
            f"/diffs?per_page={PER_PAGE}&page={page}"
        )
        response = await _request("GET", base_url, token, path)
        if response.status_code >= 400:
            raise GitLabError(f"GitLab returned HTTP {response.status_code}: {_message(response)}")
        try:
            changes = response.json()
        except ValueError as exc:
            raise GitLabError("GitLab returned a malformed diff response.") from exc
        if not isinstance(changes, list):
            raise GitLabError("GitLab returned an unexpected diff shape.")

        for change in changes:
            if isinstance(change, dict):
                section = _render_change(change)
                if section:
                    sections.append(section)

        next_page = response.headers.get("x-next-page") or ""
        page = int(next_page) if next_page.isdigit() else 0

    diff = "".join(sections)
    if not diff.strip():
        raise GitLabError("GitLab returned an empty diff for this merge request.", 422)
    return diff


def inline_position(
    path: str, line: int, *, base_sha: str, start_sha: str, head_sha: str
) -> dict:
    """Discussion position anchored to the new side of the diff."""
    return {
        "position_type": "text",
        "base_sha": base_sha,
        "start_sha": start_sha,
        "head_sha": head_sha,
        "old_path": path,
        "new_path": path,
        "new_line": line,
    }


async def post_note(token: str, base_url: str, project_path: str, iid: int, body: str) -> dict:
    path = f"/projects/{_project(project_path)}/merge_requests/{iid}/notes"
    response = await _request("POST", base_url, token, path, json={"body": body})
    if response.status_code not in (200, 201):
        raise GitLabError(
            f"GitLab rejected the review summary: {_message(response)}", response.status_code
        )
    try:
        return response.json()
    except ValueError:
        return {}


async def post_discussion(
    token: str, base_url: str, project_path: str, iid: int, body: str, position: dict
) -> dict:
    path = f"/projects/{_project(project_path)}/merge_requests/{iid}/discussions"
    response = await _request(
        "POST", base_url, token, path, json={"body": body, "position": position}
    )
    if response.status_code in (200, 201):
        try:
            return response.json()
        except ValueError:
            return {}
    if response.status_code in (400, 422):
        raise GitLabError(
            f"GitLab rejected the inline comment: {_message(response)}", 422
        )
    raise GitLabError(
        f"GitLab returned HTTP {response.status_code}: {_message(response)}",
        response.status_code,
    )


async def approve(token: str, base_url: str, project_path: str, iid: int) -> tuple[bool, str]:
    """Best-effort approval; GitLab may forbid self-approval."""
    path = f"/projects/{_project(project_path)}/merge_requests/{iid}/approve"
    try:
        response = await _request("POST", base_url, token, path)
    except GitLabError as exc:
        return False, exc.message
    if response.status_code in (200, 201):
        return True, "Approved"
    return False, f"GitLab did not accept the approval: {_message(response)}"
