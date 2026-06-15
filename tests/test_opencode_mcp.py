# Tests for SCCS OpenCode MCP merge + JSONC loading

import json
from pathlib import Path

from sccs.integrations.opencode import (
    OpenCodeDetector,
    _load_jsonc,
    merge_mcp_to_opencode,
)

CC_SETTINGS = {
    "mcpServers": {
        "context7": {"command": "npx", "args": ["-y", "context7"], "env": {"K": "V"}},
        "remote-srv": {"type": "sse", "url": "https://x/mcp"},
    }
}


def _write_cc(tmp_path: Path) -> Path:
    f = tmp_path / "settings.json"
    f.write_text(json.dumps(CC_SETTINGS), encoding="utf-8")
    return f


def _config_dir(tmp_path: Path, content: str = '{"$schema": "x"}') -> tuple[Path, Path]:
    config_dir = tmp_path / ".config" / "opencode"
    config_dir.mkdir(parents=True)
    oc_file = config_dir / "opencode.jsonc"
    oc_file.write_text(content, encoding="utf-8")
    return config_dir, oc_file


class TestLoadJsonc:
    def test_plain_json(self) -> None:
        assert _load_jsonc('{"a": 1}') == {"a": 1}

    def test_line_comments(self) -> None:
        assert _load_jsonc('{\n  // a comment\n  "a": 1\n}') == {"a": 1}

    def test_block_comments(self) -> None:
        assert _load_jsonc('/* header */ {"a": 1}') == {"a": 1}

    def test_empty(self) -> None:
        assert _load_jsonc("   ") == {}


class TestMcpMerge:
    def test_adds_servers(self, tmp_path: Path) -> None:
        cc = _write_cc(tmp_path)
        config_dir, oc_file = _config_dir(tmp_path)
        result = merge_mcp_to_opencode(cc_settings_file=cc, oc_config_file=oc_file)
        assert result.success is True
        assert set(result.added) == {"context7", "remote-srv"}
        data = json.loads(oc_file.read_text(encoding="utf-8"))
        assert data["mcp"]["context7"]["command"] == ["npx", "-y", "context7"]
        assert data["mcp"]["remote-srv"]["type"] == "remote"
        # $schema preserved
        assert data["$schema"] == "x"

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        cc = _write_cc(tmp_path)
        _, oc_file = _config_dir(tmp_path)
        before = oc_file.read_text(encoding="utf-8")
        result = merge_mcp_to_opencode(cc_settings_file=cc, oc_config_file=oc_file, dry_run=True)
        assert set(result.added) == {"context7", "remote-srv"}
        assert oc_file.read_text(encoding="utf-8") == before

    def test_already_present_not_overwritten(self, tmp_path: Path) -> None:
        cc = _write_cc(tmp_path)
        _, oc_file = _config_dir(
            tmp_path,
            content=json.dumps({"mcp": {"context7": {"type": "local", "command": ["old"]}}}),
        )
        result = merge_mcp_to_opencode(cc_settings_file=cc, oc_config_file=oc_file)
        assert "context7" in result.already_present
        assert "remote-srv" in result.added
        data = json.loads(oc_file.read_text(encoding="utf-8"))
        assert data["mcp"]["context7"]["command"] == ["old"]

    def test_overwrite_updates(self, tmp_path: Path) -> None:
        cc = _write_cc(tmp_path)
        _, oc_file = _config_dir(
            tmp_path,
            content=json.dumps({"mcp": {"context7": {"type": "local", "command": ["old"]}}}),
        )
        result = merge_mcp_to_opencode(cc_settings_file=cc, oc_config_file=oc_file, overwrite_existing=True)
        assert "context7" in result.updated
        data = json.loads(oc_file.read_text(encoding="utf-8"))
        assert data["mcp"]["context7"]["command"] == ["npx", "-y", "context7"]

    def test_server_filter(self, tmp_path: Path) -> None:
        cc = _write_cc(tmp_path)
        _, oc_file = _config_dir(tmp_path)
        result = merge_mcp_to_opencode(cc_settings_file=cc, oc_config_file=oc_file, server_names=["context7"])
        assert result.added == ["context7"]

    def test_backup_created_on_existing(self, tmp_path: Path, monkeypatch) -> None:
        # Isolate the backup directory (Path.home()/.config/sccs/backups) so the
        # test never writes into the real home dir.
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
        cc = _write_cc(tmp_path)
        _, oc_file = _config_dir(tmp_path)
        merge_mcp_to_opencode(cc_settings_file=cc, oc_config_file=oc_file)
        backups = list((fake_home / ".config" / "sccs" / "backups" / "opencode").glob("opencode.jsonc.*.bak"))
        assert backups, "expected a timestamped backup of the opencode config"

    def test_no_cc_servers_errors(self, tmp_path: Path) -> None:
        cc = tmp_path / "settings.json"
        cc.write_text("{}", encoding="utf-8")
        _, oc_file = _config_dir(tmp_path)
        result = merge_mcp_to_opencode(cc_settings_file=cc, oc_config_file=oc_file)
        assert result.success is False
        assert result.error is not None

    def test_unknown_requested_server_errors(self, tmp_path: Path) -> None:
        cc = _write_cc(tmp_path)
        _, oc_file = _config_dir(tmp_path)
        result = merge_mcp_to_opencode(cc_settings_file=cc, oc_config_file=oc_file, server_names=["nope"])
        assert result.success is False

    def test_creates_config_when_missing(self, tmp_path: Path) -> None:
        cc = _write_cc(tmp_path)
        config_dir = tmp_path / ".config" / "opencode"
        config_dir.mkdir(parents=True)
        # no opencode.jsonc on disk -> resolver defaults to opencode.jsonc
        result = merge_mcp_to_opencode(cc_settings_file=cc, config_dir=config_dir)
        assert result.success is True
        assert (config_dir / "opencode.jsonc").is_file()


class TestMcpStatus:
    def test_status_reports_missing(self, tmp_path: Path) -> None:
        cc = _write_cc(tmp_path)
        config_dir, _ = _config_dir(tmp_path)
        detector = OpenCodeDetector(config_dir=config_dir)
        status = detector.get_mcp_status(cc_settings_file=cc)
        assert set(status["cc_servers"]) == {"context7", "remote-srv"}
        assert set(status["missing"]) == {"context7", "remote-srv"}
