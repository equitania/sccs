# Shared filesystem helpers for doctor detectors and installer.
# Lives in its own module to keep detectors.py free of an installer import
# (installer.py already imports from detectors.py — pulling _is_home_path
# from installer would create a cycle).

from __future__ import annotations

from pathlib import Path


def is_home_path(resolved: str) -> bool:
    """True when `resolved` lives under the current user's home directory.

    Distinguishes a user-local npm prefix (`~/.npm-global` — `sudo chown` is
    safe AND complete because the sibling bin dir is also under home) from a
    system prefix (`/usr` — chowning the lib dir alone leaves `/usr/bin`
    root-owned, and chowning `/usr/bin` is dangerous). On systems without a
    resolvable home (unlikely) we conservatively treat the path as a system
    path so we never recommend chowning it.
    """
    try:
        return Path(resolved).expanduser().resolve().is_relative_to(Path.home().resolve())
    except (OSError, ValueError, RuntimeError):
        return False
