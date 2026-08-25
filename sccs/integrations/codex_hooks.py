# SCCS OpenAI Codex Hooks Export
#
# Exports the `hooks` block of ~/.claude/settings.json into ~/.codex/hooks.json.
# Unlike the skill/agent/command exports (one file per artefact), this one MERGES
# into a file the user also edits, so three properties are load-bearing:
#
#   1. Entries SCCS did not write are never touched. Ownership is tracked in
#      ~/.config/sccs/.codex_hooks_state.yaml, keyed on (event, matcher, command).
#   2. Removing a hook in Claude removes it here — the state still remembers it.
#   3. Serialization is BYTE-STABLE. Codex records hook trust against the hash of
#      each definition, so a file that churns forces the user through /hooks on
#      every export. Ordering and key order are therefore fixed, not incidental.
#
# Direction is ONE-WAY (Claude is the source of truth), like the rest of the
# Codex integration.

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from sccs.utils.paths import atomic_write

DEFAULT_CODEX_HOOKS_STATE_PATH = Path.home() / ".config" / "sccs" / ".codex_hooks_state.yaml"

# (event, matcher, command). The matcher is "" when the group carries none.
HookKey = tuple[str, str, str]

# Key order inside an emitted group and handler. Fixed so the document is
# byte-stable across runs (see module docstring).
_GROUP_KEY_ORDER = ("matcher", "hooks")
_HANDLER_KEY_ORDER = ("type", "command", "timeout")


@dataclass
class CodexHooksState:
    """The hook entries SCCS wrote into ~/.codex/hooks.json."""

    keys: set[HookKey] = field(default_factory=set)

    def to_dict(self) -> dict:
        # Sorted lists keep the YAML stable, which keeps diffs readable.
        return {"managed": sorted([list(key) for key in self.keys])}

    @classmethod
    def from_dict(cls, data: dict) -> CodexHooksState:
        raw = data.get("managed")
        if not isinstance(raw, list):
            return cls()
        keys: set[HookKey] = set()
        for item in raw:
            if isinstance(item, list) and len(item) == 3 and all(isinstance(part, str) for part in item):
                keys.add((item[0], item[1], item[2]))
        return cls(keys=keys)


class CodexHooksStateManager:
    """Read/write wrapper around ~/.config/sccs/.codex_hooks_state.yaml.

    Mirrors ProfileStateManager: a missing or corrupt file degrades to an empty
    state rather than raising. Empty is the safe default here — SCCS then claims
    nothing and touches nothing, at the cost of possibly leaving one stale entry
    behind, which the user can delete.
    """

    def __init__(self, state_path: Path | None = None) -> None:
        self.state_path = state_path or DEFAULT_CODEX_HOOKS_STATE_PATH

    def load(self) -> CodexHooksState:
        if not self.state_path.exists():
            return CodexHooksState()
        try:
            with open(self.state_path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except (yaml.YAMLError, OSError):
            return CodexHooksState()
        if not isinstance(data, dict):
            return CodexHooksState()
        return CodexHooksState.from_dict(data)

    def save(self, state: CodexHooksState) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(
            self.state_path,
            yaml.safe_dump(state.to_dict(), default_flow_style=False, sort_keys=True, allow_unicode=True),
            mode=0o600,
        )


def group_keys(event: str, group: dict) -> list[HookKey]:
    """Ownership keys for every command handler in one group."""
    matcher = group.get("matcher")
    matcher_str = matcher if isinstance(matcher, str) else ""
    handlers = group.get("hooks")
    if not isinstance(handlers, list):
        return []
    keys: list[HookKey] = []
    for handler in handlers:
        if isinstance(handler, dict) and isinstance(handler.get("command"), str):
            keys.append((event, matcher_str, handler["command"]))
    return keys


def _is_managed(event: str, group: dict, state: CodexHooksState) -> bool:
    """True when every handler in the group is one SCCS wrote.

    All-or-nothing on purpose: a group mixing managed and foreign handlers was
    hand-edited, and rewriting half of it would mangle the user's work.
    """
    keys = group_keys(event, group)
    return bool(keys) and all(key in state.keys for key in keys)


def merge_hooks(
    existing: dict,
    managed: dict[str, list[dict]],
    state: CodexHooksState,
) -> tuple[dict, CodexHooksState, list[str]]:
    """Merge converted Claude hooks into an existing Codex hooks document.

    Foreign groups keep their relative order and come first; managed groups
    follow in source order. That rule is what makes the output byte-stable when
    nothing changed.

    Returns (document, new_state, warnings).
    """
    existing_hooks = existing.get("hooks") if isinstance(existing, dict) else None
    if not isinstance(existing_hooks, dict):
        existing_hooks = {}

    warnings: list[str] = []
    seen_state_keys: set[HookKey] = set()
    merged: dict[str, list[dict]] = {}

    events = set(existing_hooks) | set(managed)
    for event in sorted(events):
        foreign: list[dict] = []
        for group in existing_hooks.get(event, []) or []:
            if not isinstance(group, dict):
                continue
            if _is_managed(event, group, state):
                seen_state_keys.update(group_keys(event, group))
                continue  # replaced by the current conversion below
            foreign.append(group)

        # Keys already present in a foreign group at this event: the group was
        # hand-edited (e.g. the user added a second handler to a group we used
        # to own outright), which is why _is_managed above no longer classifies
        # it as ours. Re-appending the managed copy of such a key would fire it
        # twice, deterministically, forever — so it must be suppressed here
        # rather than appended below. A key found this way is not vanished
        # either, so it must not trigger the "no longer found" warning.
        foreign_keys: set[HookKey] = set()
        for group in foreign:
            foreign_keys.update(group_keys(event, group))
        seen_state_keys.update(state.keys & foreign_keys)

        managed_groups: list[dict] = []
        for group in managed.get(event, []):
            handlers = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(handlers, list):
                managed_groups.append(group)
                continue
            matcher = group.get("matcher")
            matcher_str = matcher if isinstance(matcher, str) else ""
            kept_handlers = []
            for handler in handlers:
                handler_key = None
                if isinstance(handler, dict) and isinstance(handler.get("command"), str):
                    handler_key = (event, matcher_str, handler["command"])
                if handler_key is not None and handler_key in foreign_keys:
                    warnings.append(
                        f"managed hook not re-exported: {event} / {handler['command']} — found inside a "
                        "group that was edited inside Codex, left as is to avoid duplicating it"
                    )
                    continue
                kept_handlers.append(handler)
            if kept_handlers:
                managed_groups.append({**group, "hooks": kept_handlers})

        groups = foreign + managed_groups
        if groups:
            merged[event] = groups

    # A key we own but cannot find in the target: it is no longer there under the
    # identity we tracked it by. This only reports the fact — it does not say
    # whether the entry is about to be re-created, since that depends on whether
    # the source (managed) still has it too. Keys found inside a foreign group
    # (see above) are excluded via seen_state_keys — they are present, just no
    # longer exclusively ours.
    for key in sorted(state.keys - seen_state_keys):
        warnings.append(
            f"previously exported hook no longer found in hooks.json: {key[0]} / {key[2]} — "
            "it may have been edited or removed inside Codex"
        )

    new_keys: set[HookKey] = set()
    for event, groups in managed.items():
        for group in groups:
            new_keys.update(group_keys(event, group))

    return {"hooks": merged}, CodexHooksState(keys=new_keys), warnings


def _ordered(source: dict, order: tuple[str, ...]) -> dict:
    """Copy `source` with `order` first, then any remaining keys sorted."""
    result = {key: source[key] for key in order if key in source}
    for key in sorted(source):
        if key not in result:
            result[key] = source[key]
    return result


def serialize_hooks_document(document: dict) -> str:
    """Render the hooks document byte-stably.

    Events sorted, group order preserved (the merge already fixed it), key order
    pinned, two-space indent, unicode kept literal, one trailing newline.
    """
    hooks = document.get("hooks") or {}
    normalized: dict[str, list[dict]] = {}
    for event in sorted(hooks):
        groups = []
        for group in hooks[event]:
            ordered_group = _ordered(group, _GROUP_KEY_ORDER)
            handlers = ordered_group.get("hooks")
            if isinstance(handlers, list):
                ordered_group["hooks"] = [
                    _ordered(handler, _HANDLER_KEY_ORDER) if isinstance(handler, dict) else handler
                    for handler in handlers
                ]
            groups.append(ordered_group)
        normalized[event] = groups
    return json.dumps({"hooks": normalized}, indent=2, ensure_ascii=False) + "\n"
