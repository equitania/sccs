# SCCS Hashing Utilities
# Content hashing for change detection

import hashlib
from pathlib import Path


def content_hash(content: str | bytes, *, algorithm: str = "sha256") -> str:
    """
    Calculate hash of content.

    Args:
        content: String or bytes content.
        algorithm: Hash algorithm (default sha256).

    Returns:
        Hex digest of hash.
    """
    if isinstance(content, str):
        content = content.encode("utf-8")

    hasher = hashlib.new(algorithm)
    hasher.update(content)
    return hasher.hexdigest()


def file_hash(path: Path, *, algorithm: str = "sha256", chunk_size: int = 8192) -> str | None:
    """
    Calculate hash of file content.

    Args:
        path: Path to file.
        algorithm: Hash algorithm (default sha256).
        chunk_size: Chunk size for reading large files.

    Returns:
        Hex digest of hash, or None if file doesn't exist.
    """
    if not path.exists() or not path.is_file():
        return None

    hasher = hashlib.new(algorithm)

    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)

    return hasher.hexdigest()


def directory_hash(
    path: Path,
    *,
    algorithm: str = "sha256",
    include_names: bool = True,
    exclude_patterns: list[str] | None = None,
) -> str | None:
    """
    Calculate hash of directory contents.

    Includes file names and contents to detect both content changes
    and file additions/deletions.

    Args:
        path: Path to directory.
        algorithm: Hash algorithm (default sha256).
        include_names: Whether to include file names in hash.
        exclude_patterns: Patterns to exclude from hashing.

    Returns:
        Hex digest of hash, or None if directory doesn't exist.
    """
    if not path.exists() or not path.is_dir():
        return None

    hasher = hashlib.new(algorithm)

    # Collect all files sorted by relative path for deterministic hash
    files: list[tuple[str, Path]] = []

    for file_path in path.rglob("*"):
        if not file_path.is_file():
            continue

        rel_path = str(file_path.relative_to(path))

        # Check exclude patterns
        if exclude_patterns:
            from sccs.utils.paths import matches_any_pattern

            if matches_any_pattern(rel_path, exclude_patterns):
                continue

        files.append((rel_path, file_path))

    # Sort by relative path for deterministic ordering
    files.sort(key=lambda x: x[0])

    for rel_path, file_path in files:
        if include_names:
            # Include relative path in hash
            hasher.update(rel_path.encode("utf-8"))
            hasher.update(b"\x00")  # Separator

        # Include file content
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        hasher.update(b"\x00")  # File separator

    return hasher.hexdigest()


def quick_compare(path1: Path, path2: Path) -> bool:
    """
    Quickly compare two files/directories for equality.

    Uses size first, then hash for confirmation.

    Args:
        path1: First path.
        path2: Second path.

    Returns:
        True if contents are equal.
    """
    if not path1.exists() or not path2.exists():
        return path1.exists() == path2.exists()

    # Both are files
    if path1.is_file() and path2.is_file():
        # Quick size check first
        if path1.stat().st_size != path2.stat().st_size:
            return False
        # Hash comparison
        return file_hash(path1) == file_hash(path2)

    # Both are directories
    if path1.is_dir() and path2.is_dir():
        return directory_hash(path1) == directory_hash(path2)

    # Type mismatch
    return False


def get_mtime(path: Path) -> float | None:
    """
    Get modification time of file or directory.

    For directories, returns the most recent mtime of any file within.

    Args:
        path: Path to check.

    Returns:
        Modification time as float, or None if path doesn't exist.
    """
    if not path.exists():
        return None

    if path.is_file():
        return path.stat().st_mtime

    # For directories, find most recent file
    max_mtime = path.stat().st_mtime
    for file_path in path.rglob("*"):
        if file_path.is_file():
            max_mtime = max(max_mtime, file_path.stat().st_mtime)

    return max_mtime
