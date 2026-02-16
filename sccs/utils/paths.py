# SCCS Path Utilities
# Safe file operations with atomic writes and pattern matching

import fnmatch
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path


def expand_path(path: str | Path) -> Path:
    """
    Expand ~ and environment variables in path.

    Args:
        path: Path string or Path object.

    Returns:
        Expanded Path object.
    """
    path_str = str(path)
    # Expand ~ first, then environment variables
    path_str = os.path.expanduser(path_str)
    path_str = os.path.expandvars(path_str)
    return Path(path_str).resolve()


def ensure_dir(path: Path) -> Path:
    """
    Ensure directory exists, creating if necessary.

    Args:
        path: Directory path.

    Returns:
        The path that was ensured.
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_backup_dir() -> Path:
    """Get the backup directory path."""
    backup_dir = Path.home() / ".config" / "sccs" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def create_backup(path: Path, category: str = "unknown") -> Path | None:
    """
    Create a backup of a file or directory before overwriting.

    Args:
        path: Path to backup.
        category: Category name for organizing backups.

    Returns:
        Path to backup, or None if source doesn't exist.
    """
    if not path.exists():
        return None

    backup_dir = get_backup_dir() / category
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Create timestamped backup name
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{path.name}.{timestamp}.bak"
    backup_path = backup_dir / backup_name

    if path.is_dir():
        shutil.copytree(path, backup_path)
    else:
        shutil.copy2(path, backup_path)

    return backup_path


def safe_copy(
    source: Path,
    dest: Path,
    *,
    preserve_metadata: bool = True,
    backup: bool = False,
    backup_category: str = "unknown",
) -> Path | None:
    """
    Atomically copy file or directory.

    Uses a temporary file/directory and atomic rename to prevent
    partial copies in case of failure.

    Args:
        source: Source path.
        dest: Destination path.
        preserve_metadata: Whether to preserve file metadata (default True).
        backup: Whether to create backup before overwriting (default False).
        backup_category: Category name for organizing backups.

    Returns:
        Path to backup file if created, None otherwise.

    Raises:
        FileNotFoundError: If source doesn't exist.
        IsADirectoryError: If source is directory but dest is file.
    """
    if not source.exists():
        raise FileNotFoundError(f"Source does not exist: {source}")

    # Create backup if destination exists and backup requested
    backup_path = None
    if backup and dest.exists():
        backup_path = create_backup(dest, backup_category)

    # Ensure parent directory exists
    ensure_dir(dest.parent)

    # Create temp destination in same directory for atomic rename
    temp_suffix = f".tmp.{os.getpid()}"

    if source.is_dir():
        temp_dest = dest.with_suffix(temp_suffix)
        try:
            if temp_dest.exists():
                shutil.rmtree(temp_dest)
            shutil.copytree(source, temp_dest)
            # Remove existing destination if it exists
            if dest.exists():
                shutil.rmtree(dest)
            temp_dest.rename(dest)
        except (FileExistsError, PermissionError, OSError):
            # Cleanup on failure
            if temp_dest.exists():
                shutil.rmtree(temp_dest)
            raise
    else:
        temp_dest = dest.with_suffix(dest.suffix + temp_suffix)
        try:
            if preserve_metadata:
                shutil.copy2(source, temp_dest)
            else:
                shutil.copy(source, temp_dest)
            # Atomic rename
            temp_dest.rename(dest)
        except (FileExistsError, PermissionError, OSError):
            # Cleanup on failure
            if temp_dest.exists():
                temp_dest.unlink()
            raise

    return backup_path


def safe_delete(path: Path, *, missing_ok: bool = False) -> bool:
    """
    Safely delete file or directory.

    Args:
        path: Path to delete.
        missing_ok: If True, don't raise error if path doesn't exist.

    Returns:
        True if something was deleted, False if path didn't exist.

    Raises:
        FileNotFoundError: If path doesn't exist and missing_ok is False.
    """
    if not path.exists():
        if missing_ok:
            return False
        raise FileNotFoundError(f"Path does not exist: {path}")

    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return True


def atomic_write(path: Path, content: str | bytes, *, encoding: str = "utf-8") -> None:
    """
    Atomically write content to file.

    Uses a temporary file and atomic rename.

    Args:
        path: Target file path.
        content: Content to write (str or bytes).
        encoding: Encoding for string content (default utf-8).
    """
    ensure_dir(path.parent)

    # Create temp file in same directory for atomic rename
    fd, temp_path = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        if isinstance(content, str):
            with os.fdopen(fd, "w", encoding=encoding) as f:
                f.write(content)
        else:
            with os.fdopen(fd, "wb") as f:
                f.write(content)
        # Atomic rename
        os.rename(temp_path, path)
    except Exception:
        # Cleanup on failure
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def get_relative_path(path: Path, base: Path) -> Path | None:
    """
    Get path relative to base, or None if not relative.

    Args:
        path: Path to make relative.
        base: Base path.

    Returns:
        Relative path or None if not relative.
    """
    try:
        return path.relative_to(base)
    except ValueError:
        return None


def matches_pattern(path: str | Path, pattern: str) -> bool:
    """
    Check if path matches a glob pattern.

    Supports:
    - * for any characters within path component
    - ** for any path components
    - ? for single character

    Args:
        path: Path to check.
        pattern: Glob pattern.

    Returns:
        True if path matches pattern.
    """
    path_str = str(path)

    # Handle ** patterns specially
    if "**" in pattern:
        # Convert ** to regex-like matching
        parts = pattern.split("**")
        if len(parts) == 2:
            prefix, suffix = parts
            # Check if path starts with prefix and ends with suffix
            if prefix and not fnmatch.fnmatch(path_str, f"{prefix}*"):
                return False
            if suffix:
                suffix = suffix.lstrip("/")
                if not fnmatch.fnmatch(path_str, f"*{suffix}"):
                    return False
            return True

    return fnmatch.fnmatch(path_str, pattern)


def matches_any_pattern(path: str | Path, patterns: list[str]) -> bool:
    """
    Check if path matches any of the given patterns.

    Args:
        path: Path to check.
        patterns: List of glob patterns.

    Returns:
        True if path matches any pattern.
    """
    return any(matches_pattern(path, p) for p in patterns)


def find_files(
    directory: Path,
    *,
    pattern: str | None = None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    recursive: bool = True,
) -> list[Path]:
    """
    Find files in directory matching criteria.

    Args:
        directory: Directory to search.
        pattern: Optional glob pattern filter.
        include: Optional include patterns.
        exclude: Optional exclude patterns.
        recursive: Whether to search recursively.

    Returns:
        List of matching file paths.
    """
    if not directory.exists():
        return []

    results: list[Path] = []

    if recursive:
        iterator = directory.rglob("*")
    else:
        iterator = directory.glob("*")

    for path in iterator:
        if not path.is_file():
            continue

        rel_path = get_relative_path(path, directory)
        if rel_path is None:
            continue

        rel_str = str(rel_path)

        # Check pattern
        if pattern and not fnmatch.fnmatch(path.name, pattern):
            continue

        # Check include patterns
        if include and not matches_any_pattern(rel_str, include):
            continue

        # Check exclude patterns
        if exclude and matches_any_pattern(rel_str, exclude):
            continue

        results.append(path)

    return sorted(results)


def find_directories(
    directory: Path,
    *,
    marker: str | None = None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> list[Path]:
    """
    Find directories, optionally with a marker file.

    Args:
        directory: Directory to search.
        marker: Optional marker file that must exist in directory.
        include: Optional include patterns.
        exclude: Optional exclude patterns.

    Returns:
        List of matching directory paths.
    """
    if not directory.exists():
        return []

    results: list[Path] = []

    for path in directory.iterdir():
        if not path.is_dir():
            continue

        rel_str = path.name

        # Check marker
        if marker and not (path / marker).exists():
            continue

        # Check include patterns
        if include and not matches_any_pattern(rel_str, include):
            continue

        # Check exclude patterns
        if exclude and matches_any_pattern(rel_str, exclude):
            continue

        results.append(path)

    return sorted(results)
