# SCCS Interactive Divergence Resolver
# Prompts the user to pick a strategy when local and remote have diverged.

from __future__ import annotations

import sys
from enum import Enum
from pathlib import Path
from typing import Protocol

import questionary

from sccs.git.operations import force_push, pull


class DivergenceStrategy(str, Enum):
    """Strategies offered to the user when the branch has diverged from its remote."""

    REBASE = "rebase"  # pull --rebase  — replays local commits on top of remote
    MERGE = "merge"  # pull (merge)   — creates a merge commit
    FORCE_PUSH = "force"  # push --force-with-lease — local wins, remote commits dropped
    ABORT = "abort"  # leave the repo untouched and exit


class _ConsoleLike(Protocol):
    """Subset of the Console API used by the resolver (kept minimal for testability)."""

    def print_info(self, message: str) -> None: ...
    def print_error(self, message: str) -> None: ...
    def print_success(self, message: str) -> None: ...
    def print_warning(self, message: str) -> None: ...


def _is_interactive() -> bool:
    """Return True if stdin AND stdout are TTYs (otherwise prompts would hang)."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def prompt_divergence_strategy(
    *,
    ahead: int,
    behind: int,
    remote: str,
    interactive: bool | None = None,
) -> DivergenceStrategy:
    """
    Ask the user how to resolve a diverged branch.

    Args:
        ahead: Local commits not in remote.
        behind: Remote commits not in local.
        remote: Remote name (shown in the prompt, not used to run git).
        interactive: Override the TTY check. ``None`` = auto-detect.

    Returns:
        The chosen strategy. Defaults to ``ABORT`` in non-interactive contexts
        so CI/pipe usage keeps the previous fail-loud behaviour.
    """
    if interactive is False or (interactive is None and not _is_interactive()):
        return DivergenceStrategy.ABORT

    choices = [
        questionary.Choice(
            title=f"Rebase — replay your {ahead} commit(s) on top of {remote} (linear history)",
            value=DivergenceStrategy.REBASE.value,
        ),
        questionary.Choice(
            title=f"Merge — pull {remote} and create a merge commit",
            value=DivergenceStrategy.MERGE.value,
        ),
        questionary.Choice(
            title=(
                f"Force-push — overwrite {remote} with local (drops {behind} remote commit(s); uses --force-with-lease)"
            ),
            value=DivergenceStrategy.FORCE_PUSH.value,
        ),
        questionary.Choice(
            title="Abort — leave the repository unchanged",
            value=DivergenceStrategy.ABORT.value,
        ),
    ]

    answer = questionary.select(
        f"Repository diverged: {ahead} ahead, {behind} behind. How should SCCS resolve it?",
        choices=choices,
        default=DivergenceStrategy.REBASE.value,
    ).ask()

    if answer is None:  # Ctrl-C / EOF
        return DivergenceStrategy.ABORT

    return DivergenceStrategy(answer)


def apply_divergence_strategy(
    strategy: DivergenceStrategy,
    repo_path: Path,
    console: _ConsoleLike,
    *,
    remote: str = "origin",
    branch: str | None = None,
) -> bool:
    """
    Execute the chosen divergence strategy.

    Args:
        strategy: Strategy returned by ``prompt_divergence_strategy``.
        repo_path: Working copy the git commands run against.
        console: Output helper (anything with the Console ``print_*`` API).
        remote: Remote name for push operations (validated downstream).
        branch: Branch for push operations (uses current branch if None).

    Returns:
        True if the strategy succeeded and sync may continue.
        False if the strategy failed or the user aborted.
    """
    if strategy is DivergenceStrategy.ABORT:
        console.print_warning("Divergence resolution aborted — repository left unchanged")
        return False

    if strategy is DivergenceStrategy.REBASE:
        console.print_info("Rebasing local commits on top of remote...")
        if pull(repo_path, rebase=True):
            console.print_success("Rebase successful")
            return True
        console.print_error("Rebase failed — resolve conflicts manually and re-run 'sccs sync'")
        return False

    if strategy is DivergenceStrategy.MERGE:
        console.print_info("Merging remote changes into local...")
        if pull(repo_path):
            console.print_success("Merge successful")
            return True
        console.print_error("Merge failed — resolve conflicts manually and re-run 'sccs sync'")
        return False

    if strategy is DivergenceStrategy.FORCE_PUSH:
        console.print_warning(f"Force-pushing local to {remote} (with lease)...")
        if force_push(repo_path, remote=remote, branch=branch):
            console.print_success(f"Force-push to {remote} successful")
            return True
        console.print_error(
            "Force-push rejected — the remote advanced since the last fetch. Run 'sccs sync' again to re-evaluate."
        )
        return False

    # Exhaustive; keeps mypy and future additions honest.
    raise ValueError(f"Unknown divergence strategy: {strategy}")
