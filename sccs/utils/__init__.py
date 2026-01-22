# SCCS Utilities Module
# Helper functions for path handling and content hashing

from sccs.utils.paths import (
    expand_path,
    safe_copy,
    safe_delete,
    ensure_dir,
    atomic_write,
    get_relative_path,
    matches_pattern,
    matches_any_pattern,
)
from sccs.utils.hashing import (
    content_hash,
    file_hash,
    directory_hash,
    quick_compare,
)

__all__ = [
    # Paths
    "expand_path",
    "safe_copy",
    "safe_delete",
    "ensure_dir",
    "atomic_write",
    "get_relative_path",
    "matches_pattern",
    "matches_any_pattern",
    # Hashing
    "content_hash",
    "file_hash",
    "directory_hash",
    "quick_compare",
]
