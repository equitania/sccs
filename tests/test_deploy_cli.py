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


def test_a_second_run_does_not_report_a_clean_host(runner, home, tmp_path, monkeypatch):
    """End to end: a sweep-only finding must survive into the next run.

    The receipt is doctored the way a build with wrong ownership logic would
    have written it — `pre_existing` on an artefact SCCS did write. Revoke
    reports it and exits 1. The operator re-runs. If the record had been
    dropped, that second run would print "Nothing to revoke on this host",
    exit 0, and the artefact would still be there.
    """
    out = tmp_path / "b.zip"
    assert runner.invoke(cli, ["deploy", "export", "tiny", "-o", str(out)]).exit_code == 0

    target = tmp_path / "customer2"
    target.mkdir()
    monkeypatch.setenv("HOME", str(target))
    monkeypatch.setattr(Path, "home", lambda: target)
    monkeypatch.delenv("SCCS_CONFIG", raising=False)

    assert runner.invoke(cli, ["deploy", "install", str(out), "--json"]).exit_code == 0
    skill = target / ".claude" / "skills" / "odoo-common"
    assert skill.exists()

    manager = ReceiptManager(target / ".config" / "sccs" / ".deploy_receipt.yaml")
    record = manager.load().find("tiny")
    for entry in record.entries:
        entry.pre_existing = True  # the wrong inference; written_by_sccs stays True
    manager.record_install(record)

    # `.stdout`, not `.output`: a failing revoke also logs to stderr, and
    # CliRunner.output merges the two. The JSON contract is about stdout.
    first = runner.invoke(cli, ["deploy", "revoke", "--yes", "--json"])
    assert first.exit_code == 1, first.output
    assert str(skill) in _parse_clean(first.stdout)["leftovers"]
    assert skill.exists()

    second = runner.invoke(cli, ["deploy", "revoke", "--yes", "--json"])
    assert second.exit_code == 1, second.output
    payload = _parse_clean(second.stdout)
    assert str(skill) in payload["leftovers"]
    assert payload["success"] is False


def test_a_never_ours_leftover_is_reported_without_failing(runner, home, tmp_path, monkeypatch):
    """Case 3 in the CLI: shown, labelled, exit 0.

    The customer already had their own `odoo-common`, so install skipped it.
    Revoke reports the name it ships and still finds — under
    `benign_leftovers`, not `leftovers` — and succeeds.
    """
    out = tmp_path / "b.zip"
    assert runner.invoke(cli, ["deploy", "export", "tiny", "-o", str(out)]).exit_code == 0

    target = tmp_path / "customer3"
    theirs = target / ".claude" / "skills" / "odoo-common"
    theirs.mkdir(parents=True)
    (theirs / "SKILL.md").write_text("# the customer's own\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(target))
    monkeypatch.setattr(Path, "home", lambda: target)
    monkeypatch.delenv("SCCS_CONFIG", raising=False)

    assert runner.invoke(cli, ["deploy", "install", str(out), "--json"]).exit_code == 0

    result = runner.invoke(cli, ["deploy", "revoke", "--yes", "--json"])
    assert result.exit_code == 0, result.output
    payload = _parse_clean(result.output)
    assert payload["leftovers"] == []
    assert payload["benign_leftovers"] == [str(theirs)]
    assert (theirs / "SKILL.md").read_text(encoding="utf-8") == "# the customer's own\n"


def test_text_mode_separates_a_never_ours_leftover_from_a_real_one(runner, home, tmp_path, monkeypatch):
    """The operator has to be able to tell the two blocks apart at a glance.

    Both kinds of finding appear on this host: the customer's own
    `odoo-common` (never ours) and, after doctoring the receipt, an
    artefact SCCS did write but recorded as pre-existing.
    """
    import re

    out = tmp_path / "b.zip"
    assert runner.invoke(cli, ["deploy", "export", "tiny", "-o", str(out)]).exit_code == 0

    target = tmp_path / "customer4"
    theirs = target / ".claude" / "skills" / "odoo-common"
    theirs.mkdir(parents=True)
    (theirs / "SKILL.md").write_text("# the customer's own\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(target))
    monkeypatch.setattr(Path, "home", lambda: target)
    monkeypatch.delenv("SCCS_CONFIG", raising=False)

    assert runner.invoke(cli, ["deploy", "install", str(out), "--json"]).exit_code == 0

    manager = ReceiptManager(target / ".config" / "sccs" / ".deploy_receipt.yaml")
    record = manager.load().find("tiny")
    record.sweep_globs["claude_skills"] = ["odoo-common", "ghost"]
    manager.record_install(record)
    ghost = target / ".claude" / "skills" / "ghost"
    ghost.mkdir(parents=True)
    (ghost / "SKILL.md").write_text("# left behind\n", encoding="utf-8")

    result = runner.invoke(cli, ["deploy", "revoke", "--yes"])
    output = re.sub(r"\x1b\[[0-9;]*m", "", result.output)

    assert result.exit_code == 1
    assert "artefacts of ours are still on this host" in output
    assert "no receipt entry" in output
    assert "never written by SCCS" in output


# --- Final review, CRITICAL 3: an unknown --profile must not read as clean ---


def _tiny_record(home: Path) -> InstallRecord:
    return InstallRecord(
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


def test_revoke_with_an_unknown_profile_fails_and_names_what_is_installed(runner, home):
    """A typo used to filter to nothing and report a clean host, exit 0."""
    manager = ReceiptManager(home / ".config" / "sccs" / ".deploy_receipt.yaml")
    manager.record_install(_tiny_record(home))

    result = runner.invoke(cli, ["deploy", "revoke", "--profile", "tinny", "--yes"])

    assert result.exit_code == 1
    assert "tinny" in result.output
    assert "tiny" in result.output
    assert (home / ".claude" / "skills" / "odoo-common").exists()


def test_revoke_with_an_unknown_profile_emits_the_json_error_envelope(runner, home):
    manager = ReceiptManager(home / ".config" / "sccs" / ".deploy_receipt.yaml")
    manager.record_install(_tiny_record(home))

    result = runner.invoke(cli, ["deploy", "revoke", "--profile", "nope", "--yes", "--json"])

    assert result.exit_code == 1
    payload = _parse_clean(result.output)
    assert payload["success"] is False
    assert "nope" in payload["error"]


def test_revoke_without_a_profile_filter_still_succeeds_on_a_clean_host(runner, home):
    """The legitimate "nothing installed here" case keeps exit 0."""
    result = runner.invoke(cli, ["deploy", "revoke", "--yes", "--json"])
    assert result.exit_code == 0
    assert _parse_clean(result.output)["removed"] == 0


# --- Final review, CRITICAL 1: foreign targets are visible in both modes ---


def test_install_reports_skipped_foreign_targets(runner, home, tmp_path, monkeypatch):
    out = tmp_path / "b.zip"
    assert runner.invoke(cli, ["deploy", "export", "tiny", "-o", str(out)]).exit_code == 0

    target = tmp_path / "customer-foreign"
    (target / ".claude" / "skills" / "odoo-common").mkdir(parents=True)
    (target / ".claude" / "skills" / "odoo-common" / "SKILL.md").write_text("theirs\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(target))
    monkeypatch.setattr(Path, "home", lambda: target)
    monkeypatch.delenv("SCCS_CONFIG", raising=False)

    result = runner.invoke(cli, ["deploy", "install", str(out), "--json"])
    assert result.exit_code == 0, result.output
    payload = _parse_clean(result.output)
    assert "claude_skills/odoo-common" in payload["skipped_foreign"]

    text = runner.invoke(cli, ["deploy", "install", str(out)])
    assert text.exit_code == 0, text.output
    assert "odoo-common" in text.output
    assert "not written by SCCS" in text.output
    assert (target / ".claude" / "skills" / "odoo-common" / "SKILL.md").read_text(encoding="utf-8") == "theirs\n"


# --- Final review, IMPORTANT 3: the host user's own ~/.config/sccs/ stays ---


def _install_on(runner, out: Path, target: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(target))
    monkeypatch.setattr(Path, "home", lambda: target)
    monkeypatch.delenv("SCCS_CONFIG", raising=False)
    result = runner.invoke(cli, ["deploy", "install", str(out), "--json"])
    assert result.exit_code == 0, result.output


def test_revoke_keeps_a_pre_existing_sccs_state_dir(runner, home, tmp_path, monkeypatch):
    """The host user runs `sccs` themselves — their state is not ours."""
    out = tmp_path / "b.zip"
    assert runner.invoke(cli, ["deploy", "export", "tiny", "-o", str(out)]).exit_code == 0

    target = tmp_path / "host-with-sccs"
    (target / ".config" / "sccs").mkdir(parents=True)
    (target / ".config" / "sccs" / "config.yaml").write_text("repository:\n  path: ~/x\n", encoding="utf-8")
    (target / ".config" / "sccs" / ".sync_state.yaml").write_text("categories: {}\n", encoding="utf-8")
    _install_on(runner, out, target, monkeypatch)

    result = runner.invoke(cli, ["deploy", "revoke", "--yes", "--json"])
    assert result.exit_code == 0, result.output
    payload = _parse_clean(result.output)
    assert payload["state_dir_kept"] is True

    assert (target / ".config" / "sccs" / "config.yaml").exists()
    assert (target / ".config" / "sccs" / ".sync_state.yaml").exists()
    assert not (target / ".config" / "sccs" / ".deploy_receipt.yaml").exists()
    assert not (target / ".claude" / "skills" / "odoo-common").exists()


def test_revoke_purges_a_state_dir_we_created(runner, home, tmp_path, monkeypatch):
    out = tmp_path / "b.zip"
    assert runner.invoke(cli, ["deploy", "export", "tiny", "-o", str(out)]).exit_code == 0

    target = tmp_path / "host-without-sccs"
    target.mkdir()
    _install_on(runner, out, target, monkeypatch)
    # Something SCCS itself would leave behind in that directory.
    (target / ".config" / "sccs" / ".sync_state.yaml").write_text("categories: {}\n", encoding="utf-8")

    result = runner.invoke(cli, ["deploy", "revoke", "--yes", "--json"])
    assert result.exit_code == 0, result.output
    assert _parse_clean(result.output)["state_dir_kept"] is False
    assert not (target / ".config" / "sccs" / ".sync_state.yaml").exists()
