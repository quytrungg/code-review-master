from __future__ import annotations

from app.services import skill_loader


def make_root(tmp_path):
    (tmp_path / "SKILL.md").write_text("# Entry\n\nContract goes here.", encoding="utf-8")
    references = tmp_path / "references"
    references.mkdir()
    (references / "ruby-and-rails.md").write_text("Ruby rules " * 50, encoding="utf-8")
    (references / "frontend-review.md").write_text("React rules", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("plain text rules", encoding="utf-8")
    (tmp_path / "ignored.json").write_text("{}", encoding="utf-8")
    return tmp_path


def test_discovery_only_returns_markdown_and_text(tmp_path):
    root = make_root(tmp_path)
    names = {path.name for path in skill_loader.skill_files(root)}
    assert names == {"SKILL.md", "ruby-and-rails.md", "frontend-review.md", "notes.txt"}


def test_budget_keeps_the_entry_file_and_drops_the_rest(tmp_path):
    root = make_root(tmp_path)
    bundle = skill_loader.load_bundle(hints=set(), max_chars=70, root=root)
    assert bundle.included == ["SKILL.md"]
    assert bundle.skipped, "expected the reference files to be reported as skipped"
    assert len(bundle.skipped) == 3


def test_full_budget_includes_everything(tmp_path):
    root = make_root(tmp_path)
    bundle = skill_loader.load_bundle(hints={"ruby", "rails"}, max_chars=10_000, root=root)
    assert set(bundle.included) == {"SKILL.md", "references/ruby-and-rails.md", "references/frontend-review.md", "notes.txt"}
    assert bundle.included[0] == "SKILL.md"
    assert "## Skill file: SKILL.md" in bundle.text
    assert "Review standards" in bundle.text


def test_matching_hints_rank_a_reference_earlier(tmp_path):
    root = make_root(tmp_path)
    bundle = skill_loader.load_bundle(hints={"react", "frontend"}, max_chars=10_000, root=root)
    assert bundle.included.index("references/frontend-review.md") < bundle.included.index(
        "references/ruby-and-rails.md"
    )


def test_real_skill_library_loads_within_budget():
    bundle = skill_loader.load_bundle(hints={"ruby", "rails", "backend"}, max_chars=20_000)
    assert bundle.included, "expected skill files from the repository code-review folder"
    assert bundle.total_chars <= 20_000 + 1_000
    assert any(name.endswith("SKILL.md") for name in bundle.included)
    assert "Review standards" in bundle.text


def test_manifest_lists_relative_paths():
    entries = skill_loader.manifest()
    assert any(name.endswith("SKILL.md") for name in entries)
    assert all(not name.startswith("/") for name in entries)


def test_missing_directory_returns_empty_bundle(tmp_path):
    bundle = skill_loader.load_bundle(max_chars=1000, root=tmp_path / "nope")
    assert bundle.included == [] and bundle.text == ""
