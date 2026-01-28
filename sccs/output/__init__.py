# SCCS Output Module
# Rich console output and diff display

from sccs.output.console import Console, create_console
from sccs.output.diff import DiffResult, show_conflict, show_diff
from sccs.output.merge import MergeResult, interactive_merge

__all__ = [
    "Console",
    "create_console",
    "show_diff",
    "show_conflict",
    "DiffResult",
    "interactive_merge",
    "MergeResult",
]
