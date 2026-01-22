# SCCS Output Module
# Rich console output and diff display

from sccs.output.console import Console, create_console
from sccs.output.diff import show_diff, show_conflict, DiffResult

__all__ = [
    "Console",
    "create_console",
    "show_diff",
    "show_conflict",
    "DiffResult",
]
