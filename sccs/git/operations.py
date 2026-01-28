# SCCS Git Operations
# Git command execution and repository management

import subprocess
from pathlib import Path
from typing import Optional


class GitError(Exception):
    """Exception raised for git operation errors."""

    def __init__(self, message: str, returncode: int = 1, stderr: str = ""):
        self.message = message
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(message)


def _run_git(
    *args: str,
    cwd: Optional[Path] = None,
    check: bool = True,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    """
    Run a git command.

    Args:
        *args: Git command arguments.
        cwd: Working directory.
        check: Whether to raise on non-zero exit.
        capture_output: Whether to capture stdout/stderr.

    Returns:
        CompletedProcess with result.

    Raises:
        GitError: If command fails and check is True.
    """
    cmd = ["git", *args]
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            check=False,
            capture_output=capture_output,
            text=True,
        )
        if check and result.returncode != 0:
            raise GitError(
                f"Git command failed: {' '.join(cmd)}",
                returncode=result.returncode,
                stderr=result.stderr.strip() if result.stderr else "",
            )
        return result
    except FileNotFoundError:
        raise GitError("git command not found. Is git installed?")


def get_repo_root(path: Optional[Path] = None) -> Optional[Path]:
    """
    Get the root directory of a git repository.

    Args:
        path: Starting path (defaults to current directory).

    Returns:
        Path to repo root, or None if not in a repo.
    """
    try:
        result = _run_git("rev-parse", "--show-toplevel", cwd=path)
        return Path(result.stdout.strip())
    except GitError:
        return None


def is_git_repo(path: Optional[Path] = None) -> bool:
    """
    Check if path is within a git repository.

    Args:
        path: Path to check (defaults to current directory).

    Returns:
        True if in a git repo.
    """
    return get_repo_root(path) is not None


def git_status(path: Optional[Path] = None, *, porcelain: bool = True) -> str:
    """
    Get git status output.

    Args:
        path: Repository path.
        porcelain: Use machine-readable format.

    Returns:
        Status output string.
    """
    args = ["status"]
    if porcelain:
        args.append("--porcelain")
    result = _run_git(*args, cwd=path)
    return result.stdout


def has_uncommitted_changes(path: Optional[Path] = None) -> bool:
    """
    Check if repository has uncommitted changes.

    Args:
        path: Repository path.

    Returns:
        True if there are uncommitted changes.
    """
    status = git_status(path, porcelain=True)
    return len(status.strip()) > 0


def get_current_branch(path: Optional[Path] = None) -> Optional[str]:
    """
    Get current branch name.

    Args:
        path: Repository path.

    Returns:
        Branch name or None if detached.
    """
    try:
        result = _run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=path)
        branch = result.stdout.strip()
        return None if branch == "HEAD" else branch
    except GitError:
        return None


def stage_files(
    files: list[Path],
    path: Optional[Path] = None,
) -> bool:
    """
    Stage files for commit.

    Args:
        files: List of file paths to stage.
        path: Repository path.

    Returns:
        True if successful.
    """
    if not files:
        return True

    args = ["add", "--"]
    args.extend(str(f) for f in files)

    try:
        _run_git(*args, cwd=path)
        return True
    except GitError:
        return False


def stage_all(path: Optional[Path] = None) -> bool:
    """
    Stage all changes.

    Args:
        path: Repository path.

    Returns:
        True if successful.
    """
    try:
        _run_git("add", "-A", cwd=path)
        return True
    except GitError:
        return False


def commit(
    message: str,
    path: Optional[Path] = None,
    *,
    author: Optional[str] = None,
) -> Optional[str]:
    """
    Create a commit.

    Args:
        message: Commit message.
        path: Repository path.
        author: Optional author string (format: "Name <email>").

    Returns:
        Commit hash if successful, None otherwise.
    """
    args = ["commit", "-m", message]

    if author:
        args.extend(["--author", author])

    try:
        _run_git(*args, cwd=path)
        # Get the commit hash
        result = _run_git("rev-parse", "HEAD", cwd=path)
        return result.stdout.strip()
    except GitError:
        return None


def push(
    path: Optional[Path] = None,
    *,
    remote: str = "origin",
    branch: Optional[str] = None,
    set_upstream: bool = False,
) -> bool:
    """
    Push commits to remote.

    Args:
        path: Repository path.
        remote: Remote name.
        branch: Branch name (uses current if not specified).
        set_upstream: Set upstream tracking.

    Returns:
        True if successful.
    """
    args = ["push"]

    if set_upstream:
        args.append("-u")

    args.append(remote)

    if branch:
        args.append(branch)

    try:
        _run_git(*args, cwd=path)
        return True
    except GitError:
        return False


def get_changed_files(
    path: Optional[Path] = None,
    *,
    staged: bool = False,
    unstaged: bool = False,
    untracked: bool = False,
) -> list[Path]:
    """
    Get list of changed files.

    Args:
        path: Repository path.
        staged: Include staged files.
        unstaged: Include unstaged files.
        untracked: Include untracked files.

    Returns:
        List of changed file paths.
    """
    files: set[Path] = set()
    repo_root = get_repo_root(path) or Path.cwd()

    status = git_status(path, porcelain=True)

    for line in status.strip().split("\n"):
        if not line:
            continue

        # Format: XY filename
        # X = index status, Y = worktree status
        status_code = line[:2]
        filename = line[3:]

        # Handle renamed files (format: "R  old -> new")
        if " -> " in filename:
            filename = filename.split(" -> ")[1]

        file_path = repo_root / filename

        # Check if we should include this file
        index_status = status_code[0]
        worktree_status = status_code[1]

        if staged and index_status not in (" ", "?"):
            files.add(file_path)
        if unstaged and worktree_status not in (" ", "?"):
            files.add(file_path)
        if untracked and status_code == "??":
            files.add(file_path)

    return sorted(files)


def init_repo(path: Path) -> bool:
    """
    Initialize a new git repository.

    Args:
        path: Directory to initialize.

    Returns:
        True if successful.
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
        _run_git("init", cwd=path)
        return True
    except GitError:
        return False


def clone_repo(
    url: str,
    dest: Path,
    *,
    branch: Optional[str] = None,
    depth: Optional[int] = None,
) -> bool:
    """
    Clone a repository.

    Args:
        url: Repository URL.
        dest: Destination directory.
        branch: Optional branch to checkout.
        depth: Optional depth for shallow clone.

    Returns:
        True if successful.
    """
    args = ["clone"]

    if branch:
        args.extend(["-b", branch])

    if depth:
        args.extend(["--depth", str(depth)])

    args.extend([url, str(dest)])

    try:
        _run_git(*args)
        return True
    except GitError:
        return False


def fetch(path: Optional[Path] = None) -> bool:
    """
    Fetch remote changes without merging.

    Args:
        path: Repository path.

    Returns:
        True if successful.
    """
    try:
        _run_git("fetch", cwd=path)
        return True
    except GitError:
        return False


def get_remote_status(path: Optional[Path] = None) -> dict:
    """
    Check if local branch is behind/ahead of remote.

    Args:
        path: Repository path.

    Returns:
        dict with keys: ahead, behind, diverged, up_to_date, error (if any)
    """
    try:
        # Fetch first to get latest remote state
        fetch(path)

        # Get current branch
        branch = get_current_branch(path)
        if not branch:
            return {"error": "No branch or detached HEAD"}

        # Check ahead/behind
        result = _run_git("rev-list", "--left-right", "--count", f"HEAD...origin/{branch}", cwd=path)
        parts = result.stdout.strip().split()
        if len(parts) != 2:
            return {"error": "Unexpected rev-list output"}

        ahead, behind = int(parts[0]), int(parts[1])

        return {
            "ahead": ahead,
            "behind": behind,
            "diverged": ahead > 0 and behind > 0,
            "up_to_date": ahead == 0 and behind == 0,
        }
    except GitError as e:
        return {"error": str(e)}


def pull(
    path: Optional[Path] = None,
    *,
    rebase: bool = False,
) -> bool:
    """
    Pull changes from remote.

    Args:
        path: Repository path.
        rebase: Use rebase instead of merge.

    Returns:
        True if successful.
    """
    args = ["pull"]
    if rebase:
        args.append("--rebase")

    try:
        _run_git(*args, cwd=path)
        return True
    except GitError:
        return False
