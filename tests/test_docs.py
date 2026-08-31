# SCCS Docs Module Tests
# Tests for hub README generation

from pathlib import Path

import pytest

from sccs.config.schema import SccsConfig
from sccs.docs.generator import MARKER, DocsGenerator


@pytest.fixture
def docs_config(sample_config: dict, mock_repo: Path) -> SccsConfig:
    """Create SccsConfig for docs tests."""
    return SccsConfig.model_validate(sample_config)


@pytest.fixture
def docs_repo_with_readmes(mock_repo: Path) -> Path:
    """Set up repo with README files in category paths."""
    skills_readme = mock_repo / ".claude" / "skills" / "README.md"
    skills_readme.write_text("# Skills Catalog\n\nAll available skills.\n", encoding="utf-8")

    commands_readme = mock_repo / ".claude" / "commands" / "README.md"
    commands_readme.write_text("# Commands Reference\n\nAll commands.\n", encoding="utf-8")

    return mock_repo


def test_discover_readmes_finds_existing(docs_config: SccsConfig, docs_repo_with_readmes: Path) -> None:
    """README files in repo paths are discovered."""
    gen = DocsGenerator(docs_config)
    readmes = gen._discover_readmes()

    assert len(readmes) >= 1
    names = [r.category_name for r in readmes]
    assert "claude_skills" in names


def test_discover_readmes_empty_repo(docs_config: SccsConfig) -> None:
    """Empty repo returns no READMEs."""
    gen = DocsGenerator(docs_config)
    readmes = gen._discover_readmes()

    assert readmes == []


def test_render_readme_has_all_sections(docs_config: SccsConfig, docs_repo_with_readmes: Path) -> None:
    """Rendered README contains all required sections."""
    gen = DocsGenerator(docs_config)
    content = gen.render_readme()

    assert "## Documentation" in content
    assert "## Sync Categories" in content
    assert "## Repository Structure" in content


def test_render_readme_has_marker(docs_config: SccsConfig) -> None:
    """Rendered README starts with auto-generation marker."""
    gen = DocsGenerator(docs_config)
    content = gen.render_readme()

    assert content.startswith(MARKER)


def test_generate_writes_file(docs_config: SccsConfig, mock_repo: Path) -> None:
    """generate() writes README.md to repo root."""
    gen = DocsGenerator(docs_config)
    result = gen.generate()

    assert result.success is True
    assert result.readme_path is not None

    readme = mock_repo / "README.md"
    assert readme.is_file()
    content = readme.read_text(encoding="utf-8")
    assert content.startswith(MARKER)


def test_generate_dry_run_no_write(docs_config: SccsConfig, mock_repo: Path) -> None:
    """Dry-run does not write any file."""
    gen = DocsGenerator(docs_config)
    result = gen.generate(dry_run=True)

    assert result.success is True
    readme = mock_repo / "README.md"
    assert not readme.exists()


def test_build_directory_tree(docs_config: SccsConfig, mock_repo: Path) -> None:
    """Directory tree is generated successfully."""
    gen = DocsGenerator(docs_config)
    tree = gen._build_directory_tree()

    assert mock_repo.name in tree
    assert "/" in tree  # Contains directory markers


def test_categories_table_includes_disabled(sample_config: dict, mock_repo: Path, temp_home: Path) -> None:
    """Disabled categories appear in the categories table."""
    # Add a disabled category
    sample_config["sync_categories"]["disabled_cat"] = {
        "enabled": False,
        "description": "A disabled category",
        "local_path": str(temp_home / ".claude" / "hooks"),
        "repo_path": ".claude/hooks",
        "sync_mode": "bidirectional",
        "item_type": "file",
    }
    config = SccsConfig.model_validate(sample_config)

    gen = DocsGenerator(config)
    categories = gen._collect_categories()

    names = [c.name for c in categories]
    assert "disabled_cat" in names

    disabled = [c for c in categories if c.name == "disabled_cat"][0]
    assert disabled.enabled is False

    # Also check rendered output
    content = gen.render_readme()
    assert "disabled_cat" in content
    assert "\u26d4" in content  # disabled marker


def test_extract_title_from_readme(tmp_path: Path) -> None:
    """Title extraction reads first # heading."""
    readme = tmp_path / "README.md"
    readme.write_text("# My Great Title\n\nSome content.\n", encoding="utf-8")

    title = DocsGenerator._extract_title(readme)
    assert title == "My Great Title"


def test_extract_title_fallback(tmp_path: Path) -> None:
    """Title extraction falls back to directory name when no heading."""
    readme = tmp_path / "README.md"
    readme.write_text("No heading here.\n", encoding="utf-8")

    title = DocsGenerator._extract_title(readme)
    assert title == tmp_path.name


def test_docs_result_fields(docs_config: SccsConfig) -> None:
    """DocsResult has correct field values after generation."""
    gen = DocsGenerator(docs_config)
    result = gen.generate()

    assert result.success is True
    assert result.categories_total == len(docs_config.sync_categories)
    assert result.error is None


def test_render_readme_contains_version(docs_config: SccsConfig) -> None:
    """Rendered README includes SCCS version."""
    from sccs import __version__

    gen = DocsGenerator(docs_config)
    content = gen.render_readme()

    assert f"SCCS v{__version__}" in content


class TestTreeRespectsExcludes:
    """The directory tree and item counts must honour the same excludes as the sync engine.

    Regression: `_walk_tree` filtered only dotfiles, so a `__pycache__/` left behind by a
    tooling run showed up in the generated README's repository structure even though
    `__pycache__` is a default `global_exclude` pattern and the sync engine never touches
    it. `_collect_categories` had the same gap in its item counts.
    """

    def test_tree_skips_global_exclude_match(self, docs_config: SccsConfig, mock_repo: Path) -> None:
        """An entry matching a configured global_exclude pattern never reaches the tree."""
        (mock_repo / "scratch.tmp").write_text("x\n", encoding="utf-8")
        (mock_repo / "keepme.md").write_text("x\n", encoding="utf-8")

        gen = DocsGenerator(docs_config)
        tree = gen._build_directory_tree()

        assert "keepme.md" in tree
        assert "scratch.tmp" not in tree

    def test_tree_skips_pycache_under_default_excludes(self, sample_config: dict, mock_repo: Path) -> None:
        """The original trigger: a stray __pycache__/ left behind by a tooling run.

        ``__pycache__`` ships in the ``global_exclude`` default but is absent from the
        test fixture's trimmed-down pattern list, so this exercises the real-world path.
        """
        sample_config.pop("global_exclude", None)  # fall back to the shipped defaults
        config = SccsConfig.model_validate(sample_config)

        (mock_repo / "__pycache__").mkdir()
        (mock_repo / "__pycache__" / "thing.cpython-313.pyc").write_bytes(b"\x00")
        (mock_repo / "keepme").mkdir()

        gen = DocsGenerator(config)
        tree = gen._build_directory_tree()

        assert "keepme" in tree
        assert "__pycache__" not in tree

    def test_tree_skips_doctor_managed_items(self, docs_config: SccsConfig, mock_repo: Path) -> None:
        """Doctor-managed patterns (gsd-*) are excluded like the sync engine excludes them."""
        (mock_repo / "gsd-helper.md").write_text("managed\n", encoding="utf-8")
        (mock_repo / "own-notes.md").write_text("mine\n", encoding="utf-8")

        gen = DocsGenerator(docs_config)
        tree = gen._build_directory_tree()

        assert "own-notes.md" in tree
        assert "gsd-helper.md" not in tree

    def test_item_count_skips_excluded_entries(self, docs_config: SccsConfig, mock_repo: Path) -> None:
        """Excluded files are not counted in a category's item total."""
        commands = mock_repo / ".claude" / "commands"
        commands.mkdir(parents=True, exist_ok=True)
        (commands / "real.md").write_text("x\n", encoding="utf-8")
        (commands / "gsd-managed.md").write_text("x\n", encoding="utf-8")
        (commands / ".DS_Store").write_bytes(b"\x00")

        gen = DocsGenerator(docs_config)
        counts = {c.name: c.item_count for c in gen._collect_categories()}

        assert counts["claude_commands"] == 1
