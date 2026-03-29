# Tests for SCCS integrations module
# Antigravity detection/migration and Claude Desktop trust registration

import json
from pathlib import Path
from unittest.mock import patch

from sccs.integrations.antigravity import migrate_skills_to_prompts
from sccs.integrations.claude_desktop import register_trusted_folder
from sccs.integrations.detectors import (
    AntigravityDetector,
    AntigravitySkillGap,
    ClaudeDesktopDetector,
)

# --- Antigravity Detector Tests ---


class TestAntigravityDetector:
    def test_not_installed(self, tmp_path: Path) -> None:
        detector = AntigravityDetector(base_dir=tmp_path / "nonexistent")
        assert detector.is_installed() is False
        assert detector.get_info() is None
        assert detector.get_skill_gaps() == []

    def test_installed_no_prompts(self, tmp_path: Path) -> None:
        ag_dir = tmp_path / ".antigravity"
        ag_dir.mkdir()
        detector = AntigravityDetector(base_dir=ag_dir)
        assert detector.is_installed() is True
        info = detector.get_info()
        assert info is not None
        assert info.installed is True
        assert info.prompts_dir_exists is False

    def test_installed_with_prompts(self, tmp_path: Path) -> None:
        ag_dir = tmp_path / ".antigravity"
        (ag_dir / "prompts").mkdir(parents=True)
        detector = AntigravityDetector(base_dir=ag_dir)
        info = detector.get_info()
        assert info is not None
        assert info.prompts_dir_exists is True

    def test_skill_gaps_no_skills(self, tmp_path: Path) -> None:
        ag_dir = tmp_path / ".antigravity"
        ag_dir.mkdir()
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        detector = AntigravityDetector(base_dir=ag_dir, skills_dir=skills_dir)
        assert detector.get_skill_gaps() == []

    def test_skill_gaps_missing(self, tmp_path: Path) -> None:
        ag_dir = tmp_path / ".antigravity"
        ag_dir.mkdir()
        skills_dir = tmp_path / "skills"
        skill = skills_dir / "my-skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# My Skill", encoding="utf-8")

        detector = AntigravityDetector(base_dir=ag_dir, skills_dir=skills_dir)
        gaps = detector.get_skill_gaps()
        assert len(gaps) == 1
        assert gaps[0].name == "my-skill"
        assert gaps[0].prompt_exists is False
        assert gaps[0].needs_update is False

    def test_skill_gaps_outdated(self, tmp_path: Path) -> None:
        ag_dir = tmp_path / ".antigravity"
        prompts_dir = ag_dir / "prompts"
        prompts_dir.mkdir(parents=True)
        (prompts_dir / "my-skill.md").write_text("# Old version", encoding="utf-8")

        skills_dir = tmp_path / "skills"
        skill = skills_dir / "my-skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# New version", encoding="utf-8")

        detector = AntigravityDetector(base_dir=ag_dir, skills_dir=skills_dir)
        gaps = detector.get_skill_gaps()
        assert len(gaps) == 1
        assert gaps[0].needs_update is True
        assert gaps[0].prompt_exists is True

    def test_skill_gaps_up_to_date(self, tmp_path: Path) -> None:
        ag_dir = tmp_path / ".antigravity"
        prompts_dir = ag_dir / "prompts"
        prompts_dir.mkdir(parents=True)
        (prompts_dir / "my-skill.md").write_text("# Same content", encoding="utf-8")

        skills_dir = tmp_path / "skills"
        skill = skills_dir / "my-skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# Same content", encoding="utf-8")

        detector = AntigravityDetector(base_dir=ag_dir, skills_dir=skills_dir)
        gaps = detector.get_skill_gaps()
        assert len(gaps) == 0

    def test_skill_gaps_excludes(self, tmp_path: Path) -> None:
        ag_dir = tmp_path / ".antigravity"
        ag_dir.mkdir()
        skills_dir = tmp_path / "skills"

        for name in ["good-skill", "_archive", "_deprecated", ".hidden"]:
            d = skills_dir / name
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(f"# {name}", encoding="utf-8")

        detector = AntigravityDetector(base_dir=ag_dir, skills_dir=skills_dir)
        gaps = detector.get_skill_gaps()
        assert len(gaps) == 1
        assert gaps[0].name == "good-skill"

    def test_skill_gaps_no_marker(self, tmp_path: Path) -> None:
        """Directories without SKILL.md are skipped."""
        ag_dir = tmp_path / ".antigravity"
        ag_dir.mkdir()
        skills_dir = tmp_path / "skills"
        (skills_dir / "no-marker").mkdir(parents=True)
        (skills_dir / "no-marker" / "README.md").write_text("no marker", encoding="utf-8")

        detector = AntigravityDetector(base_dir=ag_dir, skills_dir=skills_dir)
        assert detector.get_skill_gaps() == []


# --- Antigravity Migration Tests ---


class TestAntigravityMigration:
    def _make_gap(
        self, tmp_path: Path, name: str, *, existing: bool = False, outdated: bool = False
    ) -> AntigravitySkillGap:
        skill_dir = tmp_path / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(f"# {name} skill content", encoding="utf-8")

        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = prompts_dir / f"{name}.md"

        if existing:
            prompt_path.write_text("# old content" if outdated else f"# {name} skill content", encoding="utf-8")

        return AntigravitySkillGap(
            name=name,
            skill_md_path=skill_md,
            prompt_path=prompt_path,
            prompt_exists=existing,
            needs_update=outdated,
        )

    def test_migrate_creates_new(self, tmp_path: Path) -> None:
        gap = self._make_gap(tmp_path, "new-skill")
        result = migrate_skills_to_prompts([gap])
        assert "new-skill" in result.created
        assert result.updated == []
        assert gap.prompt_path.read_text(encoding="utf-8") == "# new-skill skill content"

    def test_migrate_updates_outdated(self, tmp_path: Path) -> None:
        gap = self._make_gap(tmp_path, "outdated-skill", existing=True, outdated=True)
        result = migrate_skills_to_prompts([gap])
        assert "outdated-skill" in result.updated
        assert gap.prompt_path.read_text(encoding="utf-8") == "# outdated-skill skill content"

    def test_migrate_dry_run(self, tmp_path: Path) -> None:
        gap = self._make_gap(tmp_path, "dry-skill")
        # Remove the prompts dir to test creation
        prompt_path = gap.prompt_path
        result = migrate_skills_to_prompts([gap], dry_run=True)
        assert "dry-skill" in result.created
        assert not prompt_path.exists()

    def test_migrate_no_overwrite(self, tmp_path: Path) -> None:
        gap = self._make_gap(tmp_path, "skip-skill", existing=True, outdated=True)
        result = migrate_skills_to_prompts([gap], overwrite_existing=False)
        assert "skip-skill" in result.skipped
        assert result.created == []
        assert gap.prompt_path.read_text(encoding="utf-8") == "# old content"

    def test_migrate_selected_skills(self, tmp_path: Path) -> None:
        gap1 = self._make_gap(tmp_path, "skill-a")
        gap2 = self._make_gap(tmp_path, "skill-b")
        result = migrate_skills_to_prompts([gap1, gap2], selected=["skill-a"])
        assert "skill-a" in result.created
        assert "skill-b" not in result.created
        assert not gap2.prompt_path.exists()

    def test_migrate_creates_prompts_dir(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "skills" / "test"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("content", encoding="utf-8")
        new_prompts = tmp_path / "new_prompts"
        gap = AntigravitySkillGap(
            name="test",
            skill_md_path=skill_dir / "SKILL.md",
            prompt_path=new_prompts / "test.md",
            prompt_exists=False,
            needs_update=False,
        )
        result = migrate_skills_to_prompts([gap])
        assert result.prompts_dir_created is True
        assert new_prompts.is_dir()

    def test_migrate_empty_gaps(self) -> None:
        result = migrate_skills_to_prompts([])
        assert result.created == []
        assert result.updated == []


# --- Claude Desktop Detector Tests ---


class TestClaudeDesktopDetector:
    @patch("sccs.integrations.detectors.get_current_platform", return_value="linux")
    def test_not_macos(self, mock_platform: object) -> None:
        detector = ClaudeDesktopDetector()
        assert detector.is_installed() is False
        assert detector.get_info() is None

    @patch("sccs.integrations.detectors.get_current_platform", return_value="macos")
    def test_not_installed(self, mock_platform: object, tmp_path: Path) -> None:
        detector = ClaudeDesktopDetector(app_path=tmp_path / "Claude.app")
        assert detector.is_installed() is False

    @patch("sccs.integrations.detectors.get_current_platform", return_value="macos")
    def test_installed_no_config(self, mock_platform: object, tmp_path: Path) -> None:
        app = tmp_path / "Claude.app"
        app.mkdir()
        config_dir = tmp_path / "Claude"
        config_dir.mkdir()
        detector = ClaudeDesktopDetector(app_path=app, config_dir=config_dir)
        info = detector.get_info()
        assert info is not None
        assert info.installed is True
        assert info.config_file is None
        assert info.trusted_folders == []

    @patch("sccs.integrations.detectors.get_current_platform", return_value="macos")
    def test_installed_with_config(self, mock_platform: object, tmp_path: Path) -> None:
        app = tmp_path / "Claude.app"
        app.mkdir()
        config_dir = tmp_path / "Claude"
        config_dir.mkdir()
        config_file = config_dir / "claude_desktop_config.json"
        config_file.write_text(
            json.dumps({"preferences": {"localAgentModeTrustedFolders": ["/path/to/repo"]}}),
            encoding="utf-8",
        )
        detector = ClaudeDesktopDetector(app_path=app, config_dir=config_dir)
        info = detector.get_info()
        assert info is not None
        assert info.trusted_folders == ["/path/to/repo"]

    @patch("sccs.integrations.detectors.get_current_platform", return_value="macos")
    def test_is_repo_trusted(self, mock_platform: object, tmp_path: Path) -> None:
        app = tmp_path / "Claude.app"
        app.mkdir()
        config_dir = tmp_path / "Claude"
        config_dir.mkdir()
        repo = tmp_path / "my-repo"
        repo.mkdir()
        config_file = config_dir / "claude_desktop_config.json"
        config_file.write_text(
            json.dumps({"preferences": {"localAgentModeTrustedFolders": [str(repo)]}}),
            encoding="utf-8",
        )
        detector = ClaudeDesktopDetector(app_path=app, config_dir=config_dir)
        assert detector.is_repo_trusted(str(repo)) is True
        assert detector.is_repo_trusted("/other/path") is False


# --- Claude Desktop Trust Registration Tests ---


class TestClaudeDesktopTrustRegistration:
    @patch("sccs.integrations.claude_desktop.get_current_platform", return_value="linux")
    def test_not_macos(self, mock_platform: object) -> None:
        result = register_trusted_folder("/some/path")
        assert result.success is False
        assert "macOS" in (result.error or "")

    @patch("sccs.integrations.claude_desktop.get_current_platform", return_value="macos")
    def test_config_not_found(self, mock_platform: object, tmp_path: Path) -> None:
        result = register_trusted_folder(
            "/some/path",
            config_file=tmp_path / "nonexistent.json",
        )
        assert result.success is False
        assert "not found" in (result.error or "")

    @patch("sccs.integrations.claude_desktop.get_current_platform", return_value="macos")
    def test_already_trusted(self, mock_platform: object, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps({"preferences": {"localAgentModeTrustedFolders": [str(repo)]}}),
            encoding="utf-8",
        )
        result = register_trusted_folder(str(repo), config_file=config_file)
        assert result.success is True
        assert result.already_trusted is True

    @patch("sccs.integrations.claude_desktop.get_current_platform", return_value="macos")
    def test_register_new(self, mock_platform: object, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps({"preferences": {"localAgentModeTrustedFolders": []}}),
            encoding="utf-8",
        )
        result = register_trusted_folder(str(repo), config_file=config_file)
        assert result.success is True
        assert result.already_trusted is False

        # Verify config was updated
        data = json.loads(config_file.read_text(encoding="utf-8"))
        assert str(repo) in data["preferences"]["localAgentModeTrustedFolders"]

    @patch("sccs.integrations.claude_desktop.get_current_platform", return_value="macos")
    def test_register_dry_run(self, mock_platform: object, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps({"preferences": {"localAgentModeTrustedFolders": []}}),
            encoding="utf-8",
        )
        result = register_trusted_folder(str(repo), config_file=config_file, dry_run=True)
        assert result.success is True
        assert result.already_trusted is False

        # Config should NOT be modified
        data = json.loads(config_file.read_text(encoding="utf-8"))
        assert data["preferences"]["localAgentModeTrustedFolders"] == []

    @patch("sccs.integrations.claude_desktop.get_current_platform", return_value="macos")
    def test_register_creates_preferences(self, mock_platform: object, tmp_path: Path) -> None:
        """Config with empty JSON gets preferences structure created."""
        repo = tmp_path / "repo"
        repo.mkdir()
        config_file = tmp_path / "config.json"
        config_file.write_text("{}", encoding="utf-8")
        result = register_trusted_folder(str(repo), config_file=config_file)
        assert result.success is True
        data = json.loads(config_file.read_text(encoding="utf-8"))
        assert str(repo) in data["preferences"]["localAgentModeTrustedFolders"]

    @patch("sccs.integrations.claude_desktop.get_current_platform", return_value="macos")
    def test_preserves_existing_config(self, mock_platform: object, tmp_path: Path) -> None:
        """Other config keys are preserved when adding trusted folder."""
        repo = tmp_path / "repo"
        repo.mkdir()
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "preferences": {
                        "quickEntryDictationShortcut": "capslock",
                        "localAgentModeTrustedFolders": ["/existing/path"],
                        "sidebarMode": "task",
                    }
                }
            ),
            encoding="utf-8",
        )
        result = register_trusted_folder(str(repo), config_file=config_file)
        assert result.success is True

        data = json.loads(config_file.read_text(encoding="utf-8"))
        prefs = data["preferences"]
        assert prefs["quickEntryDictationShortcut"] == "capslock"
        assert prefs["sidebarMode"] == "task"
        assert "/existing/path" in prefs["localAgentModeTrustedFolders"]
        assert str(repo) in prefs["localAgentModeTrustedFolders"]
