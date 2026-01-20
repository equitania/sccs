"""Git operations for SCCS.

Provides automated commit and push functionality after synchronization.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sccs.config import get_repo_root


@dataclass
class GitResult:
    """Result of git operations."""

    success: bool = True
    commit_hash: Optional[str] = None
    branch: Optional[str] = None
    pushed: bool = False
    remote: Optional[str] = None
    errors: list[str] = field(default_factory=list)
    message: str = ""


def _run_git_command(args: list[str], cwd: Optional[Path] = None) -> tuple[bool, str, str]:
    """Run a git command and return (success, stdout, stderr).

    Args:
        args: Git command arguments (without 'git' prefix)
        cwd: Working directory for the command

    Returns:
        Tuple of (success, stdout, stderr)
    """
    repo_root = cwd or get_repo_root()
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "Git command timed out"
    except FileNotFoundError:
        return False, "", "Git is not installed or not in PATH"
    except Exception as e:
        return False, "", str(e)


def is_git_repo(path: Optional[Path] = None) -> bool:
    """Check if the given path is inside a git repository.

    Args:
        path: Path to check. Defaults to repository root.

    Returns:
        True if inside a git repository
    """
    repo_root = path or get_repo_root()
    success, _, _ = _run_git_command(["rev-parse", "--is-inside-work-tree"], cwd=repo_root)
    return success


def get_current_branch(path: Optional[Path] = None) -> Optional[str]:
    """Get the current git branch name.

    Args:
        path: Repository path. Defaults to repository root.

    Returns:
        Branch name or None if not in a git repo
    """
    success, stdout, _ = _run_git_command(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    return stdout if success else None


def get_changed_files(path: Optional[Path] = None) -> list[str]:
    """Get list of changed files (staged and unstaged).

    Args:
        path: Repository path. Defaults to repository root.

    Returns:
        List of changed file paths relative to repo root
    """
    files = []

    # Get staged files
    success, stdout, _ = _run_git_command(["diff", "--cached", "--name-only"], cwd=path)
    if success and stdout:
        files.extend(stdout.split("\n"))

    # Get unstaged modified files
    success, stdout, _ = _run_git_command(["diff", "--name-only"], cwd=path)
    if success and stdout:
        files.extend(stdout.split("\n"))

    # Get untracked files in .claude directory
    success, stdout, _ = _run_git_command(
        ["ls-files", "--others", "--exclude-standard", ".claude/"], cwd=path
    )
    if success and stdout:
        files.extend(stdout.split("\n"))

    return list(set(f for f in files if f))  # Remove duplicates and empty strings


def stage_files(files: list[str], path: Optional[Path] = None) -> bool:
    """Stage files for commit.

    Args:
        files: List of file paths to stage
        path: Repository path. Defaults to repository root.

    Returns:
        True if staging was successful
    """
    if not files:
        return True

    success, _, stderr = _run_git_command(["add"] + files, cwd=path)
    if not success:
        print(f"Failed to stage files: {stderr}")
    return success


def stage_sync_files(path: Optional[Path] = None) -> bool:
    """Stage all sync-related files.

    Stages:
    - .sync_state.json
    - SYNC_LOG.md
    - .claude/skills/
    - .claude/commands/

    Args:
        path: Repository path. Defaults to repository root.

    Returns:
        True if staging was successful
    """
    files_to_stage = [
        ".sync_state.json",
        "SYNC_LOG.md",
        ".claude/skills/",
        ".claude/commands/",
    ]
    return stage_files(files_to_stage, path)


def commit(message: str, path: Optional[Path] = None) -> tuple[bool, Optional[str]]:
    """Create a git commit.

    Args:
        message: Commit message
        path: Repository path. Defaults to repository root.

    Returns:
        Tuple of (success, commit_hash)
    """
    success, stdout, stderr = _run_git_command(["commit", "-m", message], cwd=path)
    if not success:
        if "nothing to commit" in stderr or "nothing to commit" in stdout:
            return True, None  # Nothing to commit is not an error
        print(f"Failed to commit: {stderr}")
        return False, None

    # Get the commit hash
    hash_success, commit_hash, _ = _run_git_command(["rev-parse", "HEAD"], cwd=path)
    return success, commit_hash if hash_success else None


def push(remote: str = "origin", branch: Optional[str] = None, path: Optional[Path] = None) -> bool:
    """Push commits to remote.

    Args:
        remote: Remote name (default: origin)
        branch: Branch name. If None, pushes current branch.
        path: Repository path. Defaults to repository root.

    Returns:
        True if push was successful
    """
    if branch is None:
        branch = get_current_branch(path)

    if branch is None:
        print("Could not determine current branch")
        return False

    success, _, stderr = _run_git_command(["push", remote, branch], cwd=path)
    if not success:
        print(f"Failed to push to {remote}/{branch}: {stderr}")
    return success


def generate_commit_message(
    skills_synced: list[str],
    commands_synced: list[str],
    prefix: str = "[CHG]",
) -> str:
    """Generate a structured commit message for sync operations.

    Args:
        skills_synced: List of skill names that were synced
        commands_synced: List of command names that were synced
        prefix: Commit message prefix (default: [CHG])

    Returns:
        Formatted commit message
    """
    parts = []

    if skills_synced:
        if len(skills_synced) <= 3:
            parts.append(f"skills: {', '.join(skills_synced)}")
        else:
            parts.append(f"skills: {len(skills_synced)} items")

    if commands_synced:
        if len(commands_synced) <= 3:
            parts.append(f"commands: {', '.join(commands_synced)}")
        else:
            parts.append(f"commands: {len(commands_synced)} items")

    if not parts:
        summary = "Sync update"
    else:
        summary = " | ".join(parts)

    # Build detailed body
    body_lines = ["", "Synchronized via sccs", ""]

    if skills_synced:
        body_lines.append(f"Skills: {', '.join(skills_synced)}")
    if commands_synced:
        body_lines.append(f"Commands: {', '.join(commands_synced)}")

    body_lines.extend([
        "",
        "Generated with sccs",
    ])

    return f"{prefix} Sync {summary}\n" + "\n".join(body_lines)


def auto_commit_and_push(
    skills_synced: list[str],
    commands_synced: list[str],
    auto_push: bool = False,
    remote: str = "origin",
    prefix: str = "[CHG]",
    path: Optional[Path] = None,
) -> GitResult:
    """Perform automatic commit and optional push after sync.

    Args:
        skills_synced: List of skill names that were synced
        commands_synced: List of command names that were synced
        auto_push: Whether to push after commit
        remote: Remote name for push (default: origin)
        prefix: Commit message prefix (default: [CHG])
        path: Repository path. Defaults to repository root.

    Returns:
        GitResult with operation details
    """
    result = GitResult()
    result.branch = get_current_branch(path)

    # Check if we're in a git repo
    if not is_git_repo(path):
        result.success = False
        result.errors.append("Not a git repository")
        result.message = "Not a git repository"
        return result

    # Stage sync-related files
    if not stage_sync_files(path):
        result.success = False
        result.errors.append("Failed to stage files")
        result.message = "Failed to stage files"
        return result

    # Generate commit message
    message = generate_commit_message(skills_synced, commands_synced, prefix)

    # Create commit
    commit_success, commit_hash = commit(message, path)
    if not commit_success:
        result.success = False
        result.errors.append("Failed to create commit")
        result.message = "Failed to create commit"
        return result

    result.commit_hash = commit_hash

    if commit_hash is None:
        result.message = "Nothing to commit"
        return result

    result.message = f"Committed: {commit_hash[:8]}"

    # Push if requested
    if auto_push:
        result.remote = remote
        if push(remote, result.branch, path):
            result.pushed = True
            result.message += f" -> {remote}/{result.branch}"
        else:
            result.success = False
            result.errors.append(f"Failed to push to {remote}")
            result.message += f" (push to {remote} failed)"

    return result
