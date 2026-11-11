from __future__ import annotations

from app.services.diff_parser import parse_diff
from app.services.prompts import build_user_prompt, render_file_block
from app.services.pull_request import PullRequestInfo
from tests.test_review_units import build_diff, files_of


def pr_info() -> PullRequestInfo:
    return PullRequestInfo(
        vcs="github",
        project="octo/example",
        number=123,
        title="Rewrite the ingest",
        state="open",
        draft=False,
        head_sha="abc123sha",
        base_sha="base123sha",
        start_sha="base123sha",
        base_ref="main",
        html_url="https://github.com/octo/example/pull/123",
        author="octocat",
        body="Big change.",
        additions=0,
        deletions=0,
        changed_files=1,
    )


def test_render_file_block_keeps_every_hunk_when_the_budget_allows():
    item = parse_diff(build_diff(1, lines=5))[0]
    block, dropped = render_file_block(item)

    assert dropped == 0
    assert block.startswith(f"## File: {item.path}  (+5/-0)\n@@ -0,0 +1,5 @@")
    assert item.render_numbered() in block


def test_render_file_block_drops_whole_hunks_never_half_of_one():
    (item,) = parse_diff(
        "diff --git a/a.py b/a.py\n"
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1,3 +1,3 @@ def first():\n"
        "+line one\n"
        "+line two\n"
        "+line three\n"
        "@@ -100,3 +100,3 @@ def later():\n"
        "+later one\n"
        "+later two\n"
        "+later three\n"
    )
    head = f"## File: {item.path}  (+6/-0)\n"
    budget = len(head) + len(item.hunks[0].render_numbered()) + 1

    block, dropped = render_file_block(item, budget)

    assert dropped == 1
    assert item.hunks[0].render_numbered() in block
    assert "later one" not in block
    assert "@@ -100,3 +100,3 @@" not in block
    assert block.endswith("[… 1 further hunk(s) of this file omitted …]\n")


def test_a_single_hunk_larger_than_the_whole_budget_is_cut_and_reported():
    (item,) = parse_diff(build_diff(1, lines=400))  # one hunk, far larger than the budget
    block, dropped = render_file_block(item, 1_000)

    assert dropped == 1
    assert "[… hunk truncated here …]" in block
    assert "[… 1 further hunk(s) of this file omitted …]" in block
    assert len(block) <= 1_200


def test_build_user_prompt_frames_a_part_and_lists_its_files():
    files = files_of(build_diff(2, lines=5))
    built = build_user_prompt(pr_info(), files, 60_000, part=2, total=3)

    assert "- This prompt covers part 2 of 3 of the change" in built.text
    assert "this is part 2 of 3 of a large pull request" in built.text
    assert "`app/services/mod_00.py`" in built.text
    assert built.truncated is False
    assert built.omitted == []


def test_build_user_prompt_without_a_part_keeps_the_old_shape():
    files = files_of(build_diff(1, lines=5))
    built = build_user_prompt(pr_info(), files, 60_000)

    assert "part 1 of 1" not in built.text
    assert "this is part" not in built.text
    assert "## File: app/services/mod_00.py" in built.text


def test_a_budget_too_small_for_the_files_reports_what_was_dropped():
    files = files_of(build_diff(3, lines=40, hunk_lines=10))
    built = build_user_prompt(pr_info(), files, 2_000, part=1, total=2)

    assert built.truncated is True
    assert built.omitted and built.omitted[0].startswith("app/services/mod_00.py")
    assert "NOTE: the diff was truncated to fit the model context." in built.text
    assert "further hunk(s) of this file omitted" in built.text
