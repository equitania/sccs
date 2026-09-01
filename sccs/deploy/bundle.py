# Build a deployment bundle: the profile's items plus a self-describing
# manifest and a generated cleanup command.

from __future__ import annotations

import copy
import tempfile
from pathlib import Path

from sccs.config.schema import ItemType, SccsConfig
from sccs.deploy.resolve import ResolvedProfile
from sccs.sync.item import SyncItem
from sccs.transfer.exporter import Exporter, ExportResult, ExportSelection
from sccs.transfer.manifest import DeploymentSection
from sccs.utils.logging import get_logger

logger = get_logger("sccs.deploy")

CLEANUP_COMMAND_NAME = "sccs-cleanup.md"
CLEANUP_CATEGORY = "claude_commands"

_CLEANUP_TEMPLATE = """---
description: Entfernt die von SCCS eingespielten Skills und Arbeitsspuren wieder
---

# Aufräumen

Auf diesem Host wurde das SCCS-Deployment-Profil `{profile}` eingespielt.

Gehe in genau dieser Reihenfolge vor:

1. Zeige `sccs deploy status`, damit sichtbar ist, was noch liegt.
2. Zeige `sccs deploy revoke --dry-run` und lege die Liste vor.
3. Frage nach ausdrücklicher Bestätigung.
4. Erst danach `sccs deploy revoke`.

Entferne niemals etwas von Hand. Wenn `sccs` fehlt oder der Rückbau
fehlschlägt, melde das und warte auf Anweisung — kein `rm`, kein `find -delete`.

Die Shell-Konfiguration bleibt absichtlich stehen; `revoke` weiß, was davon
betroffen ist.
"""


def build_cleanup_command(profile_name: str) -> str:
    """Render the cleanup slash command for a bundle.

    Generated rather than synced: a file in ~/.claude/commands would end up
    in every bundle and on our own machines.
    """
    return _CLEANUP_TEMPLATE.format(profile=profile_name)


def _portable_raw_config(selections: list[ExportSelection], raw_config: dict) -> dict:
    """Force home-relative local_paths for every selected category.

    A deployment bundle exists to travel to another machine. SyncCategory
    expands `~` eagerly, so a manifest built from the model carries THIS
    host's absolute paths — useless, or quietly wrong, on a host whose home
    directory differs. Categories that genuinely live outside home keep their
    absolute path; the install-side home guard refuses those, which is the
    right answer for them.
    """
    home = Path.home()
    raw = copy.deepcopy(raw_config) if raw_config else {}
    categories = raw.setdefault("sync_categories", {})
    for selection in selections:
        expanded = Path(selection.category.local_path).expanduser()
        try:
            relative = expanded.relative_to(home)
        except ValueError:
            continue
        entry = categories.setdefault(selection.category_name, {})
        entry["local_path"] = "~" if relative == Path(".") else f"~/{relative}"
    return raw


def _deployment_section(resolved: ResolvedProfile) -> DeploymentSection:
    return DeploymentSection(
        profile=resolved.name,
        target_platform=resolved.profile.target_platform,
        retain=list(resolved.profile.retain),
        purge_traces=True,
        sweep_globs={
            selection.category_name: [item.name for item in selection.items] for selection in resolved.selections
        },
    )


def build_bundle(
    config: SccsConfig,
    resolved: ResolvedProfile,
    output_path: Path,
    raw_config: dict,
) -> ExportResult:
    """Create the deployment ZIP for a resolved profile.

    Adds a generated cleanup command when the profile ships skills — a
    profile that carries no knowledge has nothing to revoke.
    """
    if not resolved.selections:
        return ExportResult(success=False, error=f"Profile '{resolved.name}' selects no items")

    ships_skills = any(s.category_name == "claude_skills" and s.items for s in resolved.selections)
    section = _deployment_section(resolved)
    exporter = Exporter(config, target_platform=resolved.profile.target_platform)

    with tempfile.TemporaryDirectory() as tmp_dir:
        selections = list(resolved.selections)

        if ships_skills:
            cleanup_path = Path(tmp_dir) / CLEANUP_COMMAND_NAME
            cleanup_path.write_text(build_cleanup_command(resolved.name), encoding="utf-8")

            cleanup_item = SyncItem(
                name=CLEANUP_COMMAND_NAME,
                category=CLEANUP_CATEGORY,
                item_type=ItemType.FILE,
                local_path=cleanup_path,
            )
            category = config.sync_categories.get(CLEANUP_CATEGORY)
            if category is None:
                logger.warning(
                    "Category %s not configured — bundle ships without a cleanup command",
                    CLEANUP_CATEGORY,
                )
            else:
                for index, selection in enumerate(selections):
                    if selection.category_name == CLEANUP_CATEGORY:
                        selections[index] = ExportSelection(
                            category_name=CLEANUP_CATEGORY,
                            category=selection.category,
                            items=[*selection.items, cleanup_item],
                        )
                        break
                else:
                    selections.append(
                        ExportSelection(
                            category_name=CLEANUP_CATEGORY,
                            category=category,
                            items=[cleanup_item],
                        )
                    )
                section.sweep_globs.setdefault(CLEANUP_CATEGORY, []).append(CLEANUP_COMMAND_NAME)

        portable_raw_config = _portable_raw_config(selections, raw_config)
        return exporter.export_to_zip(selections, output_path, portable_raw_config, deployment=section)
