"""Render wrapper-agent templates and create new agents (configuration only, nothing is run)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Literal

import yaml

from sccs.config.loader import add_supervisor_excludes, load_raw_user_data
from sccs.convert.frontmatter import parse_frontmatter_ex
from sccs.supervisor import SupervisorError
from sccs.supervisor.models import check_model, list_models
from sccs.supervisor.tools import ToolId, codex_default_model
from sccs.supervisor.wrappers import TemplateId, body_hash
from sccs.utils.paths import atomic_write

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
PI_REFUSAL = "Pi has no tested wrapper template yet."
DEFAULT_MODELS: dict[str, str] = {
    "agy": "gemini-4-argon-high",
    "opencode": "openrouter/~moonshotai/kimi-latest",
}
_TOOL_FOR_TEMPLATE: dict[str, ToolId] = {"agy": "agy", "opencode": "opencode", "codex": "codex"}
_DESCRIPTION_LINE = re.compile(r"^description: .*$", re.MULTILINE)


def preflight_config(config_path: Path | None = None) -> None:
    """Fail early (before any agent file is written) when config.yaml cannot be edited."""
    try:
        raw = load_raw_user_data(config_path)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise SupervisorError(f"config.yaml cannot be read, nothing was written: {exc}") from exc
    if not isinstance(raw, dict):
        raise SupervisorError("config.yaml is not a mapping, nothing was written.")


def add_excludes(name: str, config_path: Path | None = None) -> bool:
    """``add_supervisor_excludes`` with every config failure turned into a SupervisorError."""
    try:
        return add_supervisor_excludes(name, config_path)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise SupervisorError(f"Could not record the export excludes in config.yaml: {exc}") from exc


@dataclass(frozen=True)
class NewResult:
    path: Path
    model_status: Literal["verified", "unverified"]
    excludes_added: bool


def _load_template(template: str) -> str:
    return (resources.files("sccs.supervisor") / "templates" / f"{template}.md").read_text(encoding="utf-8")


def render_template(template: TemplateId, name: str, model: str, description: str | None = None) -> str:
    """Fill NAME and MODEL, hash the rendered body, then fill HASH.

    ``description`` replaces the template's description line (JSON string = valid YAML).
    """
    text = _load_template(template)
    if description is not None:
        line = "description: " + json.dumps(description, ensure_ascii=False)
        text = _DESCRIPTION_LINE.sub(lambda _m: line, text, count=1)
    text = text.replace("{{NAME}}", name).replace("{{MODEL}}", model)
    body = parse_frontmatter_ex(text).body
    return text.replace("{{HASH}}", body_hash(body, template))


def new_agent(
    template: str,
    name: str,
    model: str | None = None,
    home: Path | None = None,
    config_path: Path | None = None,
) -> NewResult:
    """Create ``<home>/.claude/agents/<name>.md`` from a template and exclude it from foreign exports.

    Everything is validated before anything is written.
    """
    if template == "pi":
        raise SupervisorError(PI_REFUSAL)
    if template not in _TOOL_FOR_TEMPLATE:
        raise SupervisorError(f"Unknown template '{template}'. Choose one of: agy, opencode, codex.")
    if not NAME_PATTERN.match(name):
        raise SupervisorError(f"Invalid agent name '{name}': use lowercase letters, digits and '-' (no path, no .md).")
    base = home if home is not None else Path.home()
    target = base / ".claude" / "agents" / f"{name}.md"
    if target.exists():
        raise SupervisorError(f"Agent '{name}' already exists: {target}")

    chosen = model
    if chosen is None:
        chosen = codex_default_model(base) if template == "codex" else DEFAULT_MODELS[template]
        if chosen is None:
            raise SupervisorError("No default Codex model in ~/.codex/config.toml; pass --model.")
    check = check_model(template, chosen, list_models(_TOOL_FOR_TEMPLATE[template], base))
    if not check.ok:
        raise SupervisorError(f"Model '{chosen}' refused: {check.reason}")

    preflight_config(config_path)
    content = render_template(template, name, chosen)  # type: ignore[arg-type]
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(target, content)
    try:
        added = add_excludes(name, config_path)
    except SupervisorError as exc:
        target.unlink(missing_ok=True)  # roll back the file this call just created
        raise SupervisorError(f"{exc} The new agent file was removed again.") from exc
    status: Literal["verified", "unverified"] = "verified" if check.status == "verified" else "unverified"
    return NewResult(path=target, model_status=status, excludes_added=added)
