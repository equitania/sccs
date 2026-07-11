"""Machine-readable JSON output for the CLI.

The Rich ``Console`` used everywhere else is constructed with ``colored=True`` by
default (``sccs/output/console.py``), which sets ``force_terminal=True`` and emits
ANSI escape codes even when stdout is piped/redirected. Any JSON output path must
therefore bypass ``Console`` entirely and write through ``click.echo`` so the
result is clean, single-line JSON that a GUI (or ``json.loads``) can consume
directly.

Usage in a command::

    if output_json:
        emit_json({"result": some_dataclass_or_model})
        return
    console.print_something(...)  # normal Rich path
"""

from __future__ import annotations

import dataclasses
import json
from enum import Enum
from pathlib import Path
from typing import Any

import click
from pydantic import BaseModel


def to_jsonable(obj: Any) -> Any:
    """Recursively convert dataclasses, Pydantic models, enums, paths, dicts and
    collections into plain JSON-safe primitives.

    Only declared dataclass fields are serialized -- computed ``@property`` values
    (e.g. ``SyncResult.has_issues``) are intentionally excluded; callers that need
    a derived value add it explicitly to the payload dict.
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, BaseModel):
        # mode="json" also flattens nested enum fields to their .value
        return obj.model_dump(mode="json")
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v) for v in obj]
    return str(obj)  # last-resort fallback (should not normally trigger)


def emit_json(payload: Any) -> None:
    """Serialize *payload* and write one compact line of JSON to stdout.

    Goes through ``click.echo`` (never ``Console``) to guarantee no ANSI leakage
    regardless of the ``colored`` default.
    """
    click.echo(json.dumps(to_jsonable(payload), separators=(",", ":")))


def emit_json_error(message: str, **extra: Any) -> None:
    """Emit a standard error envelope for JSON-mode failure paths.

    Replaces ``console.print_error`` when a command was invoked with ``--json``.
    """
    emit_json({"success": False, "error": message, **extra})
