# SCCS Transfer Tests
# Tests for export/import functionality

import zipfile
from pathlib import Path

import pytest

from sccs.config.schema import ItemType, SccsConfig
from sccs.transfer.exporter import Exporter, generate_export_filename
from sccs.transfer.importer import Importer
from sccs.transfer.manifest import (
    MANIFEST_FILENAME,
    ExportManifest,
    ManifestCategory,
    ManifestItem,
    create_manifest,
    deserialize_manifest,
    serialize_manifest,
)
from sccs.transfer.ui import build_export_choices, build_import_choices, parse_selections

# ── Manifest Tests ──────────────────────────────────────────────


class TestManifest:
    """Test manifest serialization and deserialization."""

    def test_serialize_deserialize_roundtrip(self):
        """Manifest survives YAML round-trip."""
        manifest = create_manifest(
            {
                "claude_skills": ManifestCategory(
                    description="Claude Code skills",
                    item_type="directory",
                    local_path="~/.claude/skills",
                    items=[
                        ManifestItem(
                            name="test-skill",
                            zip_path="claude_skills/test-skill/",
                            item_type="directory",
                        ),
                    ],
                ),
            }
        )

        yaml_str = serialize_manifest(manifest)
        restored = deserialize_manifest(yaml_str)

        assert restored.sccs_version == manifest.sccs_version
        assert restored.total_items == 1
        assert restored.total_categories == 1
        assert restored.categories["claude_skills"].items[0].name == "test-skill"

    def test_deserialize_invalid_yaml(self):
        """Invalid YAML raises ValueError."""
        with pytest.raises(ValueError, match="Invalid manifest YAML"):
            deserialize_manifest("not: valid: yaml: [")

    def test_deserialize_non_mapping(self):
        """Non-mapping YAML raises ValueError."""
        with pytest.raises(ValueError, match="must be a YAML mapping"):
            deserialize_manifest("- just a list")

    def test_manifest_total_items(self):
        """total_items counts across categories."""
        manifest = ExportManifest(
            sccs_version="1.0.0",
            created_at="2026-01-01T00:00:00Z",
            created_on="macos",
            categories={
                "cat1": ManifestCategory(
                    description="A",
                    item_type="file",
                    local_path="~/a",
                    items=[
                        ManifestItem(name="f1", zip_path="cat1/f1", item_type="file"),
                        ManifestItem(name="f2", zip_path="cat1/f2", item_type="file"),
                    ],
                ),
                "cat2": ManifestCategory(
                    description="B",
                    item_type="file",
                    local_path="~/b",
                    items=[
                        ManifestItem(name="f3", zip_path="cat2/f3", item_type="file"),
                    ],
                ),
            },
        )
        assert manifest.total_items == 3
        assert manifest.total_categories == 2

    def test_manifest_platform_hint(self):
        """Platform hint is preserved in serialization."""
        item = ManifestItem(
            name="config.fish",
            zip_path="fish/config.fish",
            item_type="file",
            platform_hint="macos",
        )
        manifest = create_manifest(
            {
                "fish": ManifestCategory(
                    description="Fish",
                    item_type="file",
                    local_path="~/.config/fish",
                    items=[item],
                ),
            }
        )
        yaml_str = serialize_manifest(manifest)
        restored = deserialize_manifest(yaml_str)
        assert restored.categories["fish"].items[0].platform_hint == "macos"


# ── Exporter Tests ──────────────────────────────────────────────


class TestExporter:
    """Test export scanning and ZIP creation."""

    def test_scan_filters_local_only(self, sample_config, mock_claude_dir):
        """Only items that exist locally are included."""
        config = SccsConfig.model_validate(sample_config)
        exporter = Exporter(config)
        scanned = exporter.scan_available_items()

        # mock_claude_dir has skills and commands
        for _cat_name, items in scanned.items():
            for item in items:
                assert item.exists_local, f"{item.name} should exist locally"

    def test_export_creates_valid_zip(self, sample_config, mock_claude_dir, temp_dir):
        """Export creates a ZIP with manifest and files."""
        config = SccsConfig.model_validate(sample_config)
        exporter = Exporter(config)
        scanned = exporter.scan_available_items()
        selections = exporter.build_selections_all(scanned)

        output = temp_dir / "test-export.zip"
        result = exporter.export_to_zip(selections, output, sample_config)

        assert result.success is True
        assert output.exists()

        with zipfile.ZipFile(output, "r") as zf:
            names = zf.namelist()
            assert MANIFEST_FILENAME in names
            assert result.total_items > 0

            # Verify manifest is valid YAML
            manifest_content = zf.read(MANIFEST_FILENAME).decode("utf-8")
            manifest = deserialize_manifest(manifest_content)
            assert manifest.total_items == result.total_items

    def test_export_directory_item(self, sample_config, mock_claude_dir, temp_dir):
        """Directory items include all their files in ZIP."""
        config = SccsConfig.model_validate(sample_config)
        exporter = Exporter(config)
        scanned = exporter.scan_available_items()

        # Filter to skills only
        skills_scanned = {k: v for k, v in scanned.items() if k == "claude_skills"}
        if not skills_scanned:
            pytest.skip("No skills found in mock data")

        selections = exporter.build_selections_all(skills_scanned)
        output = temp_dir / "skills-export.zip"
        result = exporter.export_to_zip(selections, output, sample_config)

        assert result.success is True

        with zipfile.ZipFile(output, "r") as zf:
            names = zf.namelist()
            # Should contain the SKILL.md file from the test-skill directory
            skill_files = [n for n in names if n.startswith("claude_skills/test-skill/")]
            assert len(skill_files) > 0, f"Expected skill files, got: {names}"

    def test_global_excludes_applied(self, sample_config, mock_claude_dir, temp_dir):
        """Global exclude patterns (e.g. .DS_Store) are not in ZIP."""
        # Create a .DS_Store file in skills
        skills_dir = mock_claude_dir / "skills" / "test-skill"
        (skills_dir / ".DS_Store").write_text("junk", encoding="utf-8")

        config = SccsConfig.model_validate(sample_config)
        exporter = Exporter(config)
        scanned = exporter.scan_available_items()
        selections = exporter.build_selections_all(scanned)

        output = temp_dir / "no-dsstore.zip"
        result = exporter.export_to_zip(selections, output, sample_config)

        assert result.success is True

        with zipfile.ZipFile(output, "r") as zf:
            names = zf.namelist()
            ds_store = [n for n in names if ".DS_Store" in n]
            assert len(ds_store) == 0, f".DS_Store should be excluded, found: {ds_store}"

    def test_export_empty_selections(self, sample_config, mock_claude_dir, temp_dir):
        """Empty selection list returns failure."""
        config = SccsConfig.model_validate(sample_config)
        exporter = Exporter(config)

        output = temp_dir / "empty.zip"
        result = exporter.export_to_zip([], output, sample_config)

        assert result.success is False
        assert "No items selected" in (result.error or "")

    def test_generate_export_filename(self):
        """Default filename matches expected pattern."""
        name = generate_export_filename()
        assert name.startswith("sccs-export-")
        assert name.endswith(".zip")

    def test_build_selections_from_parsed(self, sample_config, mock_claude_dir):
        """Parsed selections map back to correct items."""
        config = SccsConfig.model_validate(sample_config)
        exporter = Exporter(config)
        scanned = exporter.scan_available_items()

        # Simulate user selecting just test-skill
        parsed = {"claude_skills": ["test-skill"]}
        selections = exporter.build_selections_from_parsed(parsed, scanned)

        assert len(selections) == 1
        assert selections[0].category_name == "claude_skills"
        assert len(selections[0].items) == 1
        assert selections[0].items[0].name == "test-skill"


# ── Importer Tests ──────────────────────────────────────────────


def _create_test_zip(zip_path: Path, items: dict[str, str] | None = None, manifest: ExportManifest | None = None):
    """Helper to create a test ZIP archive."""
    if manifest is None:
        manifest = ExportManifest(
            sccs_version="2.14.0",
            created_at="2026-03-26T12:00:00Z",
            created_on="macos",
            categories={
                "claude_commands": ManifestCategory(
                    description="Test commands",
                    item_type="file",
                    local_path="~/.claude/commands",
                    items=[
                        ManifestItem(
                            name="test-cmd.md",
                            zip_path="claude_commands/test-cmd.md",
                            item_type="file",
                        ),
                    ],
                ),
            },
        )

    if items is None:
        items = {"claude_commands/test-cmd.md": "# Test Command\n\nThis is a test."}

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest_yaml = serialize_manifest(manifest)
        zf.writestr(MANIFEST_FILENAME, manifest_yaml)
        for arc_name, content in items.items():
            zf.writestr(arc_name, content)


class TestImporter:
    """Test import from ZIP archives."""

    def test_load_manifest_valid(self, temp_dir):
        """Valid ZIP manifest is loaded correctly."""
        zip_path = temp_dir / "valid.zip"
        _create_test_zip(zip_path)

        importer = Importer(zip_path)
        manifest = importer.load_manifest()

        assert manifest.sccs_version == "2.14.0"
        assert manifest.total_items == 1

    def test_load_manifest_missing(self, temp_dir):
        """ZIP without manifest raises ValueError."""
        zip_path = temp_dir / "no-manifest.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("random.txt", "hello")

        importer = Importer(zip_path)
        with pytest.raises(ValueError, match="does not contain"):
            importer.load_manifest()

    def test_load_nonexistent_zip(self, temp_dir):
        """Non-existent ZIP raises FileNotFoundError."""
        importer = Importer(temp_dir / "nonexistent.zip")
        with pytest.raises(FileNotFoundError):
            importer.load_manifest()

    def test_load_invalid_zip(self, temp_dir):
        """Non-ZIP file raises ValueError."""
        bad_file = temp_dir / "not-a-zip.zip"
        bad_file.write_text("this is not a zip", encoding="utf-8")

        importer = Importer(bad_file)
        with pytest.raises(ValueError, match="Not a valid ZIP"):
            importer.load_manifest()

    def test_path_traversal_blocked(self, temp_dir):
        """ZIP with path traversal attempts is rejected."""
        zip_path = temp_dir / "evil.zip"

        manifest = ExportManifest(
            sccs_version="2.14.0",
            created_at="2026-03-26T12:00:00Z",
            created_on="macos",
            categories={
                "evil": ManifestCategory(
                    description="Evil",
                    item_type="file",
                    local_path="~/.claude",
                    items=[
                        ManifestItem(
                            name="evil.md",
                            zip_path="../../../etc/passwd",
                            item_type="file",
                        ),
                    ],
                ),
            },
        )

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr(MANIFEST_FILENAME, serialize_manifest(manifest))
            zf.writestr("../../../etc/passwd", "root:x:0:0")

        importer = Importer(zip_path)
        importer.load_manifest()

        selections = importer.build_selections_all()
        result = importer.apply(selections, overwrite=True)

        assert not result.success

    def test_apply_dry_run(self, temp_dir, temp_home):
        """Dry run does not write files."""
        zip_path = temp_dir / "dryrun.zip"
        _create_test_zip(zip_path)

        # Update manifest to point to temp_home
        manifest = ExportManifest(
            sccs_version="2.14.0",
            created_at="2026-03-26T12:00:00Z",
            created_on="macos",
            categories={
                "claude_commands": ManifestCategory(
                    description="Test",
                    item_type="file",
                    local_path=str(temp_home / ".claude" / "commands"),
                    items=[
                        ManifestItem(
                            name="test-cmd.md",
                            zip_path="claude_commands/test-cmd.md",
                            item_type="file",
                        ),
                    ],
                ),
            },
        )
        _create_test_zip(zip_path, manifest=manifest)

        importer = Importer(zip_path)
        importer.load_manifest()
        selections = importer.build_selections_all()

        result = importer.apply(selections, dry_run=True)

        assert result.success is True
        assert result.written == 1
        # File should NOT actually exist
        target = temp_home / ".claude" / "commands" / "test-cmd.md"
        assert not target.exists()

    def test_apply_creates_files(self, temp_dir, temp_home):
        """Apply writes files to correct target paths."""
        target_dir = temp_home / ".claude" / "commands"
        target_dir.mkdir(parents=True, exist_ok=True)

        manifest = ExportManifest(
            sccs_version="2.14.0",
            created_at="2026-03-26T12:00:00Z",
            created_on="macos",
            categories={
                "claude_commands": ManifestCategory(
                    description="Test",
                    item_type="file",
                    local_path=str(target_dir),
                    items=[
                        ManifestItem(
                            name="imported-cmd.md",
                            zip_path="claude_commands/imported-cmd.md",
                            item_type="file",
                        ),
                    ],
                ),
            },
        )

        zip_path = temp_dir / "apply.zip"
        _create_test_zip(
            zip_path,
            items={"claude_commands/imported-cmd.md": "# Imported\n"},
            manifest=manifest,
        )

        importer = Importer(zip_path)
        importer.load_manifest()
        selections = importer.build_selections_all()

        result = importer.apply(selections, overwrite=True)

        assert result.success is True
        assert result.written == 1

        target = target_dir / "imported-cmd.md"
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "# Imported\n"

    def test_apply_skip_existing_without_overwrite(self, temp_dir, temp_home):
        """Existing files are skipped when overwrite=False."""
        target_dir = temp_home / ".claude" / "commands"
        target_dir.mkdir(parents=True, exist_ok=True)

        # Pre-existing file
        existing = target_dir / "existing.md"
        existing.write_text("original content", encoding="utf-8")

        manifest = ExportManifest(
            sccs_version="2.14.0",
            created_at="2026-03-26T12:00:00Z",
            created_on="macos",
            categories={
                "claude_commands": ManifestCategory(
                    description="Test",
                    item_type="file",
                    local_path=str(target_dir),
                    items=[
                        ManifestItem(
                            name="existing.md",
                            zip_path="claude_commands/existing.md",
                            item_type="file",
                        ),
                    ],
                ),
            },
        )

        zip_path = temp_dir / "skip.zip"
        _create_test_zip(
            zip_path,
            items={"claude_commands/existing.md": "new content"},
            manifest=manifest,
        )

        importer = Importer(zip_path)
        importer.load_manifest()
        selections = importer.build_selections_all()

        result = importer.apply(selections, overwrite=False, backup=False)

        assert result.success is True
        assert result.skipped == 1
        assert result.written == 0

        # Original content preserved
        assert existing.read_text(encoding="utf-8") == "original content"

    def test_apply_backup_on_overwrite(self, temp_dir, temp_home):
        """Backup is created when overwriting with backup=True."""
        target_dir = temp_home / ".claude" / "commands"
        target_dir.mkdir(parents=True, exist_ok=True)

        existing = target_dir / "backed-up.md"
        existing.write_text("original", encoding="utf-8")

        manifest = ExportManifest(
            sccs_version="2.14.0",
            created_at="2026-03-26T12:00:00Z",
            created_on="macos",
            categories={
                "claude_commands": ManifestCategory(
                    description="Test",
                    item_type="file",
                    local_path=str(target_dir),
                    items=[
                        ManifestItem(
                            name="backed-up.md",
                            zip_path="claude_commands/backed-up.md",
                            item_type="file",
                        ),
                    ],
                ),
            },
        )

        zip_path = temp_dir / "backup.zip"
        _create_test_zip(
            zip_path,
            items={"claude_commands/backed-up.md": "replaced"},
            manifest=manifest,
        )

        importer = Importer(zip_path)
        importer.load_manifest()
        selections = importer.build_selections_all()

        result = importer.apply(selections, overwrite=True, backup=True)

        assert result.success is True
        assert result.backed_up == 1
        assert result.written == 1

        # New content written
        assert existing.read_text(encoding="utf-8") == "replaced"


# ── UI Tests ────────────────────────────────────────────────────


class TestParseSelections:
    """Test selection parsing."""

    def test_basic_parsing(self):
        """Parse category::item format correctly."""
        values = ["cat1::item1", "cat1::item2", "cat2::item3"]
        result = parse_selections(values)

        assert result == {
            "cat1": ["item1", "item2"],
            "cat2": ["item3"],
        }

    def test_empty_list(self):
        """Empty list returns empty dict."""
        assert parse_selections([]) == {}

    def test_invalid_format_skipped(self):
        """Values without :: are skipped."""
        values = ["no-separator", "valid::item"]
        result = parse_selections(values)
        assert result == {"valid": ["item"]}


class TestBuildExportChoices:
    """Test export choice building."""

    def test_empty_categories_excluded(self, sample_config, mock_claude_dir):
        """Empty categories don't appear in choices."""
        config = SccsConfig.model_validate(sample_config)
        raw = sample_config

        # Empty scanned data
        choices = build_export_choices({}, config, raw)
        assert len(choices) == 0

    def test_choices_have_separators(self, sample_config, mock_claude_dir):
        """Choices include separators between categories."""
        import questionary

        from sccs.sync.item import SyncItem

        config = SccsConfig.model_validate(sample_config)
        raw = sample_config

        scanned = {
            "claude_skills": [
                SyncItem(
                    name="skill1",
                    category="claude_skills",
                    item_type=ItemType.DIRECTORY,
                    local_path=mock_claude_dir / "skills" / "skill1",
                ),
            ],
            "claude_commands": [
                SyncItem(
                    name="cmd1.md",
                    category="claude_commands",
                    item_type=ItemType.FILE,
                    local_path=mock_claude_dir / "commands" / "cmd1.md",
                ),
            ],
        }

        choices = build_export_choices(scanned, config, raw)

        separators = [c for c in choices if isinstance(c, questionary.Separator)]
        assert len(separators) == 2


class TestBuildImportChoices:
    """Test import choice building."""

    def test_choices_from_manifest(self):
        """Import choices are built from manifest."""

        manifest = ExportManifest(
            sccs_version="2.14.0",
            created_at="2026-03-26T12:00:00Z",
            created_on="macos",
            categories={
                "claude_skills": ManifestCategory(
                    description="Skills",
                    item_type="directory",
                    local_path="~/.claude/skills",
                    items=[
                        ManifestItem(
                            name="my-skill",
                            zip_path="claude_skills/my-skill/",
                            item_type="directory",
                        ),
                    ],
                ),
            },
        )

        choices = build_import_choices(manifest)

        separators = [c for c in choices if type(c).__name__ == "Separator"]
        choice_items = [c for c in choices if type(c).__name__ == "Choice"]

        assert len(separators) == 1
        assert len(choice_items) == 1
        assert choice_items[0].value == "claude_skills::my-skill"


# ── CLI Tests ───────────────────────────────────────────────────


class TestExportCLI:
    """Test export CLI command."""

    def test_export_help(self):
        """Export command has help text."""
        from click.testing import CliRunner

        from sccs.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["export", "--help"])
        assert result.exit_code == 0
        assert "Export selected items" in result.output

    def test_export_all_creates_zip(self, sample_config, mock_claude_dir, temp_dir, config_file, monkeypatch):
        """--all flag creates ZIP without interactive prompt."""
        from click.testing import CliRunner

        from sccs.cli import cli

        monkeypatch.setenv("SCCS_CONFIG", str(config_file))

        runner = CliRunner()
        output_path = temp_dir / "cli-export.zip"
        result = runner.invoke(cli, ["export", "--all", "-o", str(output_path)])

        assert result.exit_code == 0, f"Output: {result.output}"
        assert output_path.exists()


class TestImportCLI:
    """Test import CLI command."""

    def test_import_help(self):
        """Import command has help text."""
        from click.testing import CliRunner

        from sccs.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["import", "--help"])
        assert result.exit_code == 0
        assert "Import items" in result.output

    def test_import_dry_run(self, temp_dir, temp_home, config_file, monkeypatch):
        """--dry-run flag prevents file writes."""
        from click.testing import CliRunner

        from sccs.cli import cli

        monkeypatch.setenv("SCCS_CONFIG", str(config_file))

        # Create a test zip with absolute paths
        target_dir = temp_home / ".claude" / "commands"
        target_dir.mkdir(parents=True, exist_ok=True)

        manifest = ExportManifest(
            sccs_version="2.14.0",
            created_at="2026-03-26T12:00:00Z",
            created_on="macos",
            categories={
                "claude_commands": ManifestCategory(
                    description="Test",
                    item_type="file",
                    local_path=str(target_dir),
                    items=[
                        ManifestItem(
                            name="dry-run.md",
                            zip_path="claude_commands/dry-run.md",
                            item_type="file",
                        ),
                    ],
                ),
            },
        )

        zip_path = temp_dir / "dry-run-test.zip"
        _create_test_zip(
            zip_path,
            items={"claude_commands/dry-run.md": "# Dry run test\n"},
            manifest=manifest,
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["import", str(zip_path), "--all", "--dry-run"])

        assert result.exit_code == 0, f"Output: {result.output}"
        assert not (target_dir / "dry-run.md").exists()
