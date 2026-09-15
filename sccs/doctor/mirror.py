"""Mirror parity — keep a second Mac identical to the live workstation.

One host is the *source* (matched by hostname); every other host is a
*mirror*. The source captures its software inventory on `doctor update`,
a mirror reconciles against it on `doctor check/install/optimize`.

Two rules hold the design together and are pinned by tests:
- the source is never modified from the inventory;
- a mirror never writes the inventory.

Truth lives in two synced files: the Brewfile (category `homebrew_bundle`)
and `inventory.yaml` (category `sccs_inventory`). See
docs/superpowers/specs/2026-09-15-mirror-parity-design.md.

The config schema (`MirrorRepoSpec`, `MirrorConfig`, `_VERSION_PATTERN`,
`_REPO_URL_PATTERN`) lives in `sccs/doctor/schema.py`, not here: this module
needs `_validate_safe_name` from `schema.py`, so `schema.py` cannot import
from here without a cycle. The names are re-exported below so
`from sccs.doctor.mirror import ...` keeps working.
"""

from __future__ import annotations

import socket
from typing import Literal

from sccs.doctor.schema import (  # noqa: F401 — re-exported
    _REPO_URL_PATTERN,
    _VERSION_PATTERN,
    MirrorConfig,
    MirrorRepoSpec,
)

__all__ = [
    "MirrorConfig",
    "MirrorRepoSpec",
    "MirrorRole",
    "_VERSION_PATTERN",
    "normalize_host",
    "current_hostname",
    "resolve_role",
]

# --- roles ------------------------------------------------------------------

MirrorRole = Literal["source", "mirror", "off"]


def normalize_host(name: str) -> str:
    """`Live-Mac.local` and `live-mac` are the same host."""
    return name.split(".", 1)[0].strip().lower()


def current_hostname() -> str:
    return socket.gethostname()


def resolve_role(cfg: MirrorConfig | None, hostname: str | None = None) -> MirrorRole:
    if cfg is None or not cfg.source_host:
        return "off"
    host = hostname if hostname is not None else current_hostname()
    return "source" if normalize_host(host) == normalize_host(cfg.source_host) else "mirror"
