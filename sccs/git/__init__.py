# SCCS Git Module
# Git operations for repository management

from sccs.git.operations import (
    commit,
    fetch,
    get_current_branch,
    get_remote_status,
    get_repo_root,
    git_status,
    has_uncommitted_changes,
    is_git_repo,
    pull,
    push,
    stage_all,
    stage_files,
)

__all__ = [
    "get_repo_root",
    "is_git_repo",
    "git_status",
    "stage_files",
    "stage_all",
    "commit",
    "push",
    "pull",
    "fetch",
    "get_remote_status",
    "get_current_branch",
    "has_uncommitted_changes",
]
