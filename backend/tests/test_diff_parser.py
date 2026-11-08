from __future__ import annotations

from app.services.diff_parser import (
    ADD,
    DEL,
    anchor_line,
    parse_diff,
    rebuild_snippet,
    resolve_path,
    reviewable_files,
    snippet_contains_line,
)
from tests.fixtures import SAMPLE_DIFF


def test_parses_files_and_hunk_lines():
    files = parse_diff(SAMPLE_DIFF)
    assert [f.path for f in files] == [
        "src/services/auth.py",
        "package-lock.json",
        "assets/logo.png",
        "src/deleted.py",
    ]

    auth = files[0]
    assert auth.added == 2
    assert auth.removed == 1
    kinds = [line.kind for line in auth.hunks[0].lines]
    assert kinds == ["context", "del", "add", "add", "context"]


def test_right_side_numbering_skips_deleted_lines():
    auth = parse_diff(SAMPLE_DIFF)[0]
    numbers = sorted(auth.right_lines())
    assert numbers == [10, 11, 12, 13]
    assert auth.right_lines()[10].text.strip() == "limit = 10"
    assert auth.right_lines()[13].text.strip() == "return rows"
    assert [line for line in auth.hunks[0].lines if line.kind == DEL][0].new_no is None


def test_generated_and_binary_files_are_skipped():
    files = parse_diff(SAMPLE_DIFF)
    assert files[1].skipped_reason == "lockfile or generated manifest"
    assert files[2].skipped_reason == "binary file"
    assert [f.path for f in reviewable_files(files)] == ["src/services/auth.py"]


def test_deleted_file_has_no_right_lines():
    deleted = parse_diff(SAMPLE_DIFF)[3]
    assert deleted.is_deleted is True
    assert deleted.right_lines() == {}
    assert anchor_line(deleted, 1) is None


def test_render_numbered_prints_legal_anchors_only():
    rendered = parse_diff(SAMPLE_DIFF)[0].render_numbered()
    assert "    10       limit = 10" in rendered
    assert "    11 +     rows = db.query(Model).limit(limit).all()" in rendered
    assert "      -     rows = db.query(Model).all()" in rendered


def test_anchor_prefers_exact_then_nearest_below():
    auth = parse_diff(SAMPLE_DIFF)[0]
    assert anchor_line(auth, 11) == 11
    assert anchor_line(auth, 0) == 10
    assert anchor_line(auth, 12) == 12
    assert anchor_line(auth, 999) == 13


def test_resolve_path_handles_prefixes_and_basenames():
    files = reviewable_files(parse_diff(SAMPLE_DIFF))
    assert resolve_path(files, "src/services/auth.py") is files[0]
    assert resolve_path(files, "a/src/services/auth.py") is files[0]
    assert resolve_path(files, "./src/services/auth.py") is files[0]
    assert resolve_path(files, "auth.py") is files[0]
    assert resolve_path(files, "src/other.py") is None


def test_rebuild_snippet_quotes_the_anchor_with_context():
    auth = parse_diff(SAMPLE_DIFF)[0]
    snippet = rebuild_snippet(auth, 11, context=2)
    assert snippet.startswith("@@ -10,4 +10,5 @@")
    assert "limit(limit)" in snippet
    assert "limit = 10" in snippet


def test_snippet_contains_line_matching():
    auth = parse_diff(SAMPLE_DIFF)[0]
    line = auth.right_lines()[11]
    assert snippet_contains_line("+    rows = db.query(Model).limit(limit).all()", line.text)
    assert not snippet_contains_line("unrelated", line.text)
    assert not snippet_contains_line("", "")


def test_new_file_and_no_newline_marker():
    diff = (
        "diff --git a/new.py b/new.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/new.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+print('hi')\n"
        "+print('bye')\n"
        "\\ No newline at end of file\n"
    )
    files = parse_diff(diff)
    assert files[0].is_new is True
    assert files[0].old_path is None
    assert sorted(files[0].right_lines()) == [1, 2]
    assert files[0].hunks[0].lines[-1].kind == "meta"
