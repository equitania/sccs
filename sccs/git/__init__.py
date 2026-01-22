# SCCS Git Module
# Git operations for repository management

from sccs.git.operations import (
    get_repo_root,
    is_git_repo,
    git_status,
    stage_files,
    stage_all,
    commit,
    push,
    get_current_branch,
    has_uncommitted_changes,
)

__all__ = [
    "get_repo_root",
    "is_git_repo",
    "git_status",
    "stage_files",
    "stage_all",
    "commit",
    "push",
    "get_current_branch",
    "has_uncommitted_changes",
]
