# SCCS Utilities Module
# Helper functions for path handling and content hashing

from sccs.utils.hashing import (
    content_hash,
    directory_hash,
    file_hash,
    quick_compare,
)
from sccs.utils.paths import (
    atomic_write,
    ensure_dir,
    expand_path,
    get_relative_path,
    matches_any_pattern,
    matches_pattern,
    safe_copy,
    safe_delete,
)
from sccs.utils.platform import (
    get_current_platform,
    is_platform_match,
)

__all__ = [
    # Platform
    "get_current_platform",
    "is_platform_match",
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
