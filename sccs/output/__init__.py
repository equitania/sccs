# SCCS Output Module
# Rich console output and diff display

from sccs.output.console import Console, create_console
from sccs.output.diff import show_diff, show_conflict, DiffResult
from sccs.output.merge import interactive_merge, MergeResult

__all__ = [
    "Console",
    "create_console",
    "show_diff",
    "show_conflict",
    "DiffResult",
    "interactive_merge",
    "MergeResult",
]
