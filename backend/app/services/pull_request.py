"""A provider-neutral description of the change request being reviewed."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PullRequestInfo:
    """What the review workspace needs to know, whatever the host is."""

    vcs: str
    project: str  # "owner/repo" (GitHub) or "group/sub/project" (GitLab)
    number: int
    title: str
    state: str
    draft: bool
    head_sha: str
    base_sha: str
    start_sha: str
    base_ref: str
    html_url: str
    author: str
    body: str | None
    additions: int
    deletions: int
    changed_files: int
