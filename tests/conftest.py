# SCCS Test Fixtures
# Pytest fixtures for SCCS tests

import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_home(temp_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temporary home directory."""
    home = temp_dir / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.fixture
def mock_claude_dir(temp_home: Path) -> Path:
    """Create a mock ~/.claude directory structure."""
    claude_dir = temp_home / ".claude"
    claude_dir.mkdir()

    # Create subdirectories
    (claude_dir / "skills").mkdir()
    (claude_dir / "commands").mkdir()
    (claude_dir / "hooks").mkdir()
    (claude_dir / "scripts").mkdir()
    (claude_dir / "mcp").mkdir()

    # Create some framework files
    framework_files = [
        "CLAUDE.md",
        "COMMANDS.md",
        "FLAGS.md",
        "MCP.md",
        "MODES.md",
        "ORCHESTRATOR.md",
        "PERSONAS.md",
        "PRINCIPLES.md",
        "RULES.md",
    ]
    for f in framework_files:
        (claude_dir / f).write_text(f"# {f}\n\nTest content for {f}", encoding="utf-8")

    # Create a sample skill
    skill_dir = claude_dir / "skills" / "test-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: test-skill
description: A test skill
---

# Test Skill

This is a test skill.
""",
        encoding="utf-8",
    )

    # Create sample commands
    (claude_dir / "commands" / "test-command.md").write_text(
        """---
name: test-command
description: A test command
---

# Test Command

This is a test command.
""",
        encoding="utf-8",
    )

    return claude_dir


@pytest.fixture
def mock_repo(temp_dir: Path) -> Path:
    """Create a mock repository directory."""
    repo = temp_dir / "repo"
    repo.mkdir()

    # Create .claude directory in repo
    claude_dir = repo / ".claude"
    claude_dir.mkdir()

    # Create subdirectories
    (claude_dir / "framework").mkdir()
    (claude_dir / "skills").mkdir()
    (claude_dir / "commands").mkdir()

    return repo


@pytest.fixture
def sample_config(temp_home: Path, mock_repo: Path) -> dict:
    """Create sample configuration dict."""
    return {
        "repository": {
            "path": str(mock_repo),
            "remote": "origin",
            "auto_commit": False,
            "auto_push": False,
            "commit_prefix": "[SYNC]",
        },
        "sync_categories": {
            "claude_framework": {
                "enabled": True,
                "description": "Test framework files",
                "local_path": str(temp_home / ".claude"),
                "repo_path": ".claude/framework",
                "sync_mode": "bidirectional",
                "item_type": "file",
                "include": ["CLAUDE.md", "COMMANDS.md"],
                "exclude": [],
            },
            "claude_skills": {
                "enabled": True,
                "description": "Test skills",
                "local_path": str(temp_home / ".claude" / "skills"),
                "repo_path": ".claude/skills",
                "sync_mode": "bidirectional",
                "item_type": "directory",
                "item_marker": "SKILL.md",
                "include": ["*"],
                "exclude": [],
            },
            "claude_commands": {
                "enabled": True,
                "description": "Test commands",
                "local_path": str(temp_home / ".claude" / "commands"),
                "repo_path": ".claude/commands",
                "sync_mode": "bidirectional",
                "item_type": "file",
                "item_pattern": "*.md",
                "include": ["*"],
                "exclude": [],
            },
        },
        "global_exclude": [".DS_Store", "*.tmp"],
        "output": {"verbose": False, "colored": True},
    }


@pytest.fixture
def config_file(temp_home: Path, sample_config: dict) -> Path:
    """Create a configuration file."""
    config_dir = temp_home / ".config" / "sccs"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config.yaml"

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_config, f, default_flow_style=False)

    return config_path


@pytest.fixture
def state_file(temp_home: Path) -> Path:
    """Create a state file path."""
    config_dir = temp_home / ".config" / "sccs"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / ".sync_state.yaml"
