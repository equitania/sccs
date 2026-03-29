# SCCS Claude Desktop Integration
# Register SCCS repository as trusted folder in Claude Desktop

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sccs.utils.paths import create_backup
from sccs.utils.platform import get_current_platform


@dataclass
class TrustRegistrationResult:
    """Result of trusted folder registration."""

    success: bool
    already_trusted: bool
    repo_path: str
    error: str | None = None


def register_trusted_folder(
    repo_path: str,
    *,
    config_file: Path | None = None,
    dry_run: bool = False,
) -> TrustRegistrationResult:
    """
    Register a repository path as trusted in Claude Desktop.

    Args:
        repo_path: Repository path to register.
        config_file: Path to claude_desktop_config.json (auto-detected if None).
        dry_run: Preview only, no file writes.

    Returns:
        Registration result.
    """
    if get_current_platform() != "macos":
        return TrustRegistrationResult(
            success=False,
            already_trusted=False,
            repo_path=repo_path,
            error="Claude Desktop integration is only available on macOS",
        )

    if config_file is None:
        config_file = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"

    resolved_path = str(Path(repo_path).expanduser().resolve())

    if not config_file.is_file():
        return TrustRegistrationResult(
            success=False,
            already_trusted=False,
            repo_path=resolved_path,
            error=f"Config file not found: {config_file}",
        )

    # Read existing config
    try:
        data = json.loads(config_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return TrustRegistrationResult(
            success=False,
            already_trusted=False,
            repo_path=resolved_path,
            error=f"Failed to read config: {e}",
        )

    # Navigate to trusted folders list
    preferences = data.setdefault("preferences", {})
    trusted_folders: list[str] = preferences.setdefault("localAgentModeTrustedFolders", [])

    # Check if already trusted
    if resolved_path in trusted_folders:
        return TrustRegistrationResult(
            success=True,
            already_trusted=True,
            repo_path=resolved_path,
        )

    if dry_run:
        return TrustRegistrationResult(
            success=True,
            already_trusted=False,
            repo_path=resolved_path,
        )

    # Backup before modification
    create_backup(config_file, category="claude_desktop")

    # Add and write
    trusted_folders.append(resolved_path)
    try:
        config_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as e:
        return TrustRegistrationResult(
            success=False,
            already_trusted=False,
            repo_path=resolved_path,
            error=f"Failed to write config: {e}",
        )

    return TrustRegistrationResult(
        success=True,
        already_trusted=False,
        repo_path=resolved_path,
    )
