from __future__ import annotations

from app.services.diff_parser import parse_diff, reviewable_files
from app.services.review_units import plan_units


def build_diff(files: int, lines: int = 100, width: int = 60, hunk_lines: int | None = None) -> str:
    """A synthetic unified diff with `files` files of `lines` added lines each.

    `hunk_lines` splits each file into several hunks, which is what a real large file looks like and
    what the hunk-boundary truncation test needs.
    """
    step = hunk_lines or lines
    chunks: list[str] = []
    for index in range(files):
        path = f"app/services/mod_{index:02d}.py"
        chunks.append(f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n")
        for start in range(1, lines + 1, step):
            count = min(step, lines - start + 1)
            chunks.append(f"@@ -{start - 1},0 +{start},{count} @@ def handle_{index}():\n")
            for number in range(start, start + count):
                chunks.append(f"+    value_{number} = compute('{'x' * width}')\n")
    return "".join(chunks)


def files_of(diff_text: str):
    return reviewable_files(parse_diff(diff_text))


def test_a_diff_that_fits_is_one_part_with_the_full_budget():
    files = files_of(build_diff(2, lines=10))
    units = plan_units(files, unit_chars=25_000, max_chars=60_000)

    assert len(units) == 1
    assert units[0].index == 1 and units[0].total == 1
    assert units[0].budget == 60_000
    assert units[0].paths == ["app/services/mod_00.py", "app/services/mod_01.py"]
    assert units[0].oversized is False


def test_a_large_diff_is_packed_into_bounded_parts():
    files = files_of(build_diff(12, lines=120))
    units = plan_units(files, unit_chars=25_000, max_chars=60_000)

    assert len(units) >= 3
    assert [unit.index for unit in units] == list(range(1, len(units) + 1))
    assert {unit.total for unit in units} == {len(units)}
    # Every file lands in exactly one part, in diff order, and no part is empty.
    packed = [path for unit in units for path in unit.paths]
    assert packed == [item.path for item in files]
    assert all(unit.files for unit in units)
    assert all(unit.budget == 25_000 for unit in units)


def test_a_file_larger_than_one_part_gets_its_own_part():
    files = files_of(build_diff(1, lines=400) + build_diff(1, lines=5).replace("mod_00", "small"))
    oversized_name = files[0].path
    units = plan_units(files, unit_chars=5_000, max_chars=10_000)

    own = [unit for unit in units if oversized_name in unit.paths]
    assert own and len(own) == 1
    assert own[0].paths == [oversized_name]
    assert own[0].oversized is True
    # The small file never shares a part with the oversized one.
    assert all(oversized_name not in unit.paths for unit in units if unit is not own[0])


def test_no_files_means_no_parts():
    assert plan_units([], unit_chars=25_000, max_chars=60_000) == []
