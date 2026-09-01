"""CLI surface for `sccs deploy`."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from sccs.cli import cli
from sccs.deploy.receipt import InstallRecord, ReceiptEntry, ReceiptManager


def _parse_clean(output: str) -> dict:
    """Assert output is exactly one clean (ANSI-free) JSON object and return it."""
    import json

    assert "\x1b" not in output, f"ANSI escape leaked into JSON output: {output!r}"
    lines = [line for line in output.splitlines() if line.strip()]
    assert len(lines) == 1, f"expected exactly one JSON line, got {len(lines)}: {lines!r}"
    return json.loads(lines[0])


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    skills = tmp_path / ".claude" / "skills"
    for name in ("odoo-common", "odoo19"):
        (skills / name).mkdir(parents=True)
        (skills / name / "SKILL.md").write_text(f"---\nname: {name}\ndescription: t\n---\n\nBody.\n", encoding="utf-8")

    config_dir = tmp_path / ".config" / "sccs"
    config_dir.mkdir(parents=True)
    (config_dir / "config.yaml").write_text(
        "repository:\n"
        f"  path: {tmp_path}/repo\n"
        "sync_categories:\n"
        "  claude_skills:\n"
        "    enabled: true\n"
        "    local_path: ~/.claude/skills\n"
        "    repo_path: .claude/skills\n"
        "    item_type: directory\n"
        "    item_marker: SKILL.md\n"
        "    include: ['*']\n"
        "deployment_profiles:\n"
        "  tiny:\n"
        "    description: tiny test profile\n"
        "    target_platform: linux\n"
        "    include:\n"
        "      claude_skills: ['odoo-common']\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SCCS_CONFIG", str(config_dir / "config.yaml"))
    return tmp_path


def test_list_json_includes_bundled_and_user_profiles(runner, home):
    result = runner.invoke(cli, ["deploy", "list", "--json"])
    assert result.exit_code == 0
    payload = _parse_clean(result.output)
    names = {p["name"] for p in payload["profiles"]}
    assert {"odoo-server", "odoo-dev-full", "fastreport", "shell-only", "tiny"} <= names


def test_show_reports_resolved_items(runner, home):
    result = runner.invoke(cli, ["deploy", "show", "tiny", "--json"])
    assert result.exit_code == 0
    payload = _parse_clean(result.output)
    assert payload["total_items"] == 1
    assert payload["categories"]["claude_skills"] == ["odoo-common"]


def test_show_unknown_profile_exits_nonzero(runner, home):
    result = runner.invoke(cli, ["deploy", "show", "ghost", "--json"])
    assert result.exit_code == 1
    assert _parse_clean(result.output)["success"] is False


def test_export_creates_a_bundle(runner, home, tmp_path):
    out = tmp_path / "b.zip"
    result = runner.invoke(cli, ["deploy", "export", "tiny", "-o", str(out), "--json"])
    assert result.exit_code == 0
    assert out.exists()
    assert _parse_clean(result.output)["success"] is True


def test_export_dry_run_writes_no_file(runner, home, tmp_path):
    out = tmp_path / "b.zip"
    result = runner.invoke(cli, ["deploy", "export", "tiny", "-o", str(out), "--dry-run", "--json"])
    assert result.exit_code == 0
    assert not out.exists()


def test_export_blocks_on_missing_dependency(runner, home, tmp_path):
    """odoo-merge-to without odoo-common is refused by default."""
    skills = home / ".claude" / "skills" / "odoo-merge-to"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text(
        "---\nname: odoo-merge-to\ndescription: t\n---\n\n**INHERITS FROM:** odoo-common (commit prefixes)\n",
        encoding="utf-8",
    )
    config = home / ".config" / "sccs" / "config.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "claude_skills: ['odoo-common']", "claude_skills: ['odoo-merge-to']"
        ),
        encoding="utf-8",
    )

    out = tmp_path / "b.zip"
    result = runner.invoke(cli, ["deploy", "export", "tiny", "-o", str(out), "--json"])
    assert result.exit_code == 1
    assert not out.exists()

    result = runner.invoke(
        cli,
        ["deploy", "export", "tiny", "-o", str(out), "--allow-missing-deps", "--json"],
    )
    assert result.exit_code == 0
    assert out.exists()


def test_status_on_a_clean_host(runner, home):
    result = runner.invoke(cli, ["deploy", "status", "--json"])
    assert result.exit_code == 0
    payload = _parse_clean(result.output)
    assert payload["installs"] == []


def test_status_reports_an_install(runner, home):
    manager = ReceiptManager(home / ".config" / "sccs" / ".deploy_receipt.yaml")
    manager.record_install(
        InstallRecord(
            profile="tiny",
            installed_at="2026-09-01T10:00:00+00:00",
            sccs_version="2.65.0",
            retain=[],
            sweep_globs={"claude_skills": ["odoo-common"]},
            entries=[
                ReceiptEntry(
                    category="claude_skills",
                    name="odoo-common",
                    target=str(home / ".claude" / "skills" / "odoo-common"),
                    item_type="directory",
                    content_hash="sha256:x",
                )
            ],
        )
    )
    result = runner.invoke(cli, ["deploy", "status", "--json"])
    payload = _parse_clean(result.output)
    assert payload["installs"][0]["profile"] == "tiny"
    assert payload["installs"][0]["artefacts"] == 1


def test_revoke_without_yes_aborts(runner, home, monkeypatch):
    manager = ReceiptManager(home / ".config" / "sccs" / ".deploy_receipt.yaml")
    manager.record_install(
        InstallRecord(
            profile="tiny",
            installed_at="2026-09-01T10:00:00+00:00",
            sccs_version="2.65.0",
            entries=[
                ReceiptEntry(
                    category="claude_skills",
                    name="odoo-common",
                    target=str(home / ".claude" / "skills" / "odoo-common"),
                    item_type="directory",
                )
            ],
        )
    )
    # Force the interactive branch: under CliRunner stdout is a
    # `click.testing._NamedTextIOWrapper`, a *new* instance created when
    # `invoke()` swaps `sys.stdout` — patching the pre-invoke stdout object
    # directly (as one might expect) patches an object the command never
    # sees. Patching the class is what survives the swap.
    monkeypatch.setattr("click.testing._NamedTextIOWrapper.isatty", lambda self: True)

    result = runner.invoke(cli, ["deploy", "revoke"], input="nein\n")
    assert result.exit_code == 1
    assert "Aborted" in result.output
    assert (home / ".claude" / "skills" / "odoo-common").exists()


def test_revoke_dry_run_needs_no_confirmation(runner, home):
    result = runner.invoke(cli, ["deploy", "revoke", "--dry-run", "--json"])
    assert result.exit_code == 0
    assert _parse_clean(result.output)["dry_run"] is True


def test_revoke_json_without_yes_refuses_rather_than_prompting(runner, home, monkeypatch):
    """Finding 2: --json must never reach the confirmation prompt.

    Even on a TTY (forced here the same way as the without-yes-aborts test),
    --json without --yes must refuse outright: prompting, or printing
    "Aborted", would write plain text into what is supposed to be one clean
    JSON line.
    """
    manager = ReceiptManager(home / ".config" / "sccs" / ".deploy_receipt.yaml")
    manager.record_install(
        InstallRecord(
            profile="tiny",
            installed_at="2026-09-01T10:00:00+00:00",
            sccs_version="2.65.0",
            entries=[
                ReceiptEntry(
                    category="claude_skills",
                    name="odoo-common",
                    target=str(home / ".claude" / "skills" / "odoo-common"),
                    item_type="directory",
                )
            ],
        )
    )
    monkeypatch.setattr("click.testing._NamedTextIOWrapper.isatty", lambda self: True)

    result = runner.invoke(cli, ["deploy", "revoke", "--json"])

    assert result.exit_code == 1
    payload = _parse_clean(result.output)
    assert payload["success"] is False
    assert (home / ".claude" / "skills" / "odoo-common").exists()


def test_revoke_reports_shared_artefacts_kept(runner, home):
    """Amendment 1: a fifth bucket for artefacts another install still claims."""
    manager = ReceiptManager(home / ".config" / "sccs" / ".deploy_receipt.yaml")
    shared_entry = ReceiptEntry(
        category="claude_skills",
        name="odoo-common",
        target=str(home / ".claude" / "skills" / "odoo-common"),
        item_type="directory",
    )
    manager.record_install(
        InstallRecord(
            profile="tiny",
            installed_at="2026-09-01T10:00:00+00:00",
            sccs_version="2.65.0",
            entries=[shared_entry],
        )
    )
    manager.record_install(
        InstallRecord(
            profile="also-tiny",
            installed_at="2026-09-01T10:00:00+00:00",
            sccs_version="2.65.0",
            entries=[shared_entry],
        )
    )

    result = runner.invoke(cli, ["deploy", "revoke", "--profile", "tiny", "--yes", "--json"])
    assert result.exit_code == 0, result.output
    payload = _parse_clean(result.output)
    assert payload["shared"] == ["claude_skills/odoo-common"]
    # Still claimed by "also-tiny" — must survive this revoke.
    assert (home / ".claude" / "skills" / "odoo-common").exists()


def test_roundtrip_export_install_revoke_leaves_nothing(runner, home, tmp_path, monkeypatch):
    """The whole point of the feature, end to end.

    Switching hosts means re-patching BOTH `HOME` and `Path.home` — the
    `home` fixture patched `Path.home` to the source host, and the receipt
    manager resolves its path through `Path.home()`. Setting the
    environment variable alone leaves the receipt on the wrong machine.
    """
    out = tmp_path / "b.zip"
    assert runner.invoke(cli, ["deploy", "export", "tiny", "-o", str(out)]).exit_code == 0

    target = tmp_path / "customer"
    target.mkdir()
    monkeypatch.setenv("HOME", str(target))
    monkeypatch.setattr(Path, "home", lambda: target)
    # The customer host has no config of ours — that is the normal case.
    monkeypatch.delenv("SCCS_CONFIG", raising=False)

    result = runner.invoke(cli, ["deploy", "install", str(out), "--json"])
    assert result.exit_code == 0, result.output
    assert (target / ".claude" / "skills" / "odoo-common").exists()
    assert (target / ".config" / "sccs" / ".deploy_receipt.yaml").exists()

    result = runner.invoke(cli, ["deploy", "revoke", "--yes", "--json"])
    assert result.exit_code == 0, result.output
    assert not (target / ".claude" / "skills" / "odoo-common").exists()
    assert _parse_clean(result.output)["leftovers"] == []
