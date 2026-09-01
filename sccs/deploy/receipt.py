# What `sccs deploy install` wrote, so `sccs deploy revoke` knows what to
# take back.
#
# The receipt is deliberately standalone: it stores absolute target paths,
# the retain list and the sweep globs, so removal works on a host that has
# no SCCS config at all.

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from sccs.utils.logging import get_logger
from sccs.utils.paths import atomic_write

logger = get_logger("sccs.deploy")

RECEIPT_VERSION = 2

# Relative to the home directory. Resolved lazily by default_receipt_path():
# a module-level `Path.home() / ...` freezes the home directory at import
# time, which is wrong in every test that patches HOME and would be wrong on
# any host where the process changes user before the CLI runs.
RECEIPT_REL_PATH = Path(".config") / "sccs" / ".deploy_receipt.yaml"


def default_receipt_path() -> Path:
    """Where the receipt lives when no explicit path is given."""
    return Path.home() / RECEIPT_REL_PATH


@dataclass
class ReceiptEntry:
    """One artefact written by an install."""

    category: str
    name: str
    target: str
    item_type: str
    content_hash: str | None = None
    # True when something already existed at `target` before SCCS ever wrote
    # there. Such an entry is NEVER written over by install and NEVER removed
    # by revoke — "written by us" and "was already here" are different facts,
    # and only the first justifies displacing or deleting anything. Same line
    # as the foreign_target guard in the Codex export.
    #
    # The value is STICKY: it is established at the first install and carried
    # forward by every later one (see install.py::_sticky_pre_existing).
    # Recomputing it per install would flip every entry to True on a refresh —
    # and a receipt where everything is "not ours" makes revoke a no-op that
    # reports a clean host.
    pre_existing: bool = False
    # The PROVENANCE RECORD, as opposed to `pre_existing`, which is an
    # inference. `pre_existing` says "the target existed, so we skipped"; it
    # is written by the same code that decides to skip, and a build that got
    # that decision wrong recorded True on artefacts it then overwrote.
    # Revoke may only exempt a leftover from failing the sweep on a POSITIVE
    # record that SCCS never wrote there — this field — never on the
    # inference. False for a skipped foreign target, True for everything
    # SCCS actually wrote. The default is True because "we wrote it" is the
    # loud answer: it keeps a leftover a failure.
    written_by_sccs: bool = True
    # For a skipped foreign target: the hash of what the bundle WOULD have
    # written there. Ownership is not the only question — if the customer's
    # own file is byte-identical to the shipped artefact, our knowledge is
    # on that host no matter who put it there, and revoke must say so.
    # None for anything SCCS wrote (`content_hash` already is that hash).
    shipped_hash: str | None = None


@dataclass
class InstallRecord:
    """One `sccs deploy install` run."""

    profile: str
    installed_at: str
    sccs_version: str
    retain: list[str] = field(default_factory=list)
    sweep_globs: dict[str, list[str]] = field(default_factory=dict)
    entries: list[ReceiptEntry] = field(default_factory=list)
    # True when ~/.config/sccs/ was already there before this install wrote
    # anything — i.e. the host user runs `sccs` themselves. Revoke then keeps
    # the directory (their config.yaml, sync state and backups are theirs) and
    # removes only our receipt. Sticky, for the same reason `pre_existing` is.
    state_dir_pre_existing: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InstallRecord:
        return cls(
            profile=data["profile"],
            installed_at=data.get("installed_at", ""),
            sccs_version=data.get("sccs_version", ""),
            retain=list(data.get("retain") or []),
            sweep_globs={k: list(v) for k, v in (data.get("sweep_globs") or {}).items()},
            entries=[ReceiptEntry(**e) for e in (data.get("entries") or [])],
            state_dir_pre_existing=bool(data.get("state_dir_pre_existing", False)),
        )


@dataclass
class DeployReceipt:
    """Everything SCCS installed on this host."""

    version: int = RECEIPT_VERSION
    installs: list[InstallRecord] = field(default_factory=list)

    def find(self, profile: str) -> InstallRecord | None:
        for record in self.installs:
            if record.profile == profile:
                return record
        return None


class ReceiptManager:
    """Loads and saves the deployment receipt."""

    def __init__(self, receipt_path: Path | None = None) -> None:
        self._path = receipt_path or default_receipt_path()

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.exists()

    def load(self) -> DeployReceipt:
        """Load the receipt, or an empty one when the file does not exist.

        Raises:
            ValueError: If the file exists but cannot be read as a receipt.
                Silently returning an empty receipt would make `revoke`
                report "nothing to remove" on a host that is full of our
                artefacts — the one failure this feature must not have.
        """
        if not self._path.exists():
            return DeployReceipt()

        try:
            data = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as e:
            raise ValueError(f"Cannot read deployment receipt at {self._path}: {e}") from e

        if not isinstance(data, dict):
            raise ValueError(f"Deployment receipt at {self._path} is not a mapping")

        version = data.get("version", RECEIPT_VERSION)
        if version != RECEIPT_VERSION:
            raise ValueError(
                f"Deployment receipt at {self._path} has version {version}; this SCCS "
                f"writes and reads version {RECEIPT_VERSION}. A version-1 receipt predates "
                f"the provenance record `written_by_sccs`, so this build cannot tell which "
                f"of its entries SCCS actually wrote and must not guess. Run `sccs deploy "
                f"revoke` from the SCCS version that produced it (see `sccs_version` in the "
                f"file), or remove the listed artefacts by hand and delete the receipt."
            )

        try:
            installs = [InstallRecord.from_dict(r) for r in (data.get("installs") or [])]
        except (KeyError, TypeError) as e:
            raise ValueError(f"Malformed deployment receipt at {self._path}: {e}") from e

        return DeployReceipt(version=version, installs=installs)

    def save(self, receipt: DeployReceipt) -> None:
        """Write the receipt atomically, owner-readable only."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": receipt.version,
            "installs": [r.to_dict() for r in receipt.installs],
        }
        content = yaml.dump(payload, default_flow_style=False, sort_keys=False, allow_unicode=True)
        atomic_write(self._path, content, mode=0o600)
        logger.debug("Wrote deployment receipt: %s", self._path)

    def record_install(self, record: InstallRecord) -> None:
        """Add or replace the record for `record.profile`."""
        receipt = self.load()
        receipt.installs = [r for r in receipt.installs if r.profile != record.profile]
        receipt.installs.append(record)
        self.save(receipt)

    def remove_install(self, profile: str) -> None:
        """Drop one profile's record; delete the file when none remain."""
        receipt = self.load()
        receipt.installs = [r for r in receipt.installs if r.profile != profile]
        if receipt.installs:
            self.save(receipt)
        elif self._path.exists():
            self._path.unlink()
            logger.debug("Removed empty deployment receipt: %s", self._path)
