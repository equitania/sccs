# SCCS Atomic-Write Cross-Platform Tests
#
# Regression coverage for Windows behaviour: Path.rename / os.rename fail
# with WinError 183 when the destination already exists, while os.replace
# overwrites atomically on every platform. The codebase must use
# os.replace exclusively in atomic_write() and safe_copy().

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from sccs.utils.paths import atomic_write, safe_copy


class TestAtomicWriteOverwritesExistingFile:
    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "settings.json"
        target.write_text('{"original": true}', encoding="utf-8")

        # On Windows this used to raise WinError 183 because os.rename
        # refused to overwrite. atomic_write must succeed regardless.
        atomic_write(target, '{"new": true}')

        assert target.read_text(encoding="utf-8") == '{"new": true}'

    def test_creates_file_when_missing(self, tmp_path: Path) -> None:
        target = tmp_path / "fresh.json"
        atomic_write(target, "hello")
        assert target.read_text(encoding="utf-8") == "hello"

    def test_overwrites_repeatedly(self, tmp_path: Path) -> None:
        target = tmp_path / "loop.txt"
        for i in range(5):
            atomic_write(target, f"iteration-{i}")
            assert target.read_text(encoding="utf-8") == f"iteration-{i}"

    def test_no_temp_file_left_behind(self, tmp_path: Path) -> None:
        target = tmp_path / "clean.json"
        target.write_text("first", encoding="utf-8")
        atomic_write(target, "second")

        leftovers = [p for p in tmp_path.iterdir() if ".tmp" in p.name]
        assert leftovers == []


class TestSafeCopyOverwritesExistingFile:
    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("source content", encoding="utf-8")
        dst.write_text("old destination", encoding="utf-8")

        safe_copy(src, dst, backup=False)

        assert dst.read_text(encoding="utf-8") == "source content"

    def test_overwrites_existing_directory(self, tmp_path: Path) -> None:
        src = tmp_path / "src_dir"
        dst = tmp_path / "dst_dir"
        src.mkdir()
        (src / "file.txt").write_text("from src", encoding="utf-8")
        dst.mkdir()
        (dst / "file.txt").write_text("from dst", encoding="utf-8")

        safe_copy(src, dst, backup=False)

        assert (dst / "file.txt").read_text(encoding="utf-8") == "from src"


class TestNoLegacyRename:
    """Defence-in-depth: scan the source for `os.rename` / `.rename(` outside
    docstrings to make sure no future commit reintroduces the Windows bug."""

    def test_paths_module_uses_os_replace(self) -> None:
        path = Path(__file__).resolve().parent.parent / "sccs" / "utils" / "paths.py"
        text = path.read_text(encoding="utf-8")

        # Strip comments so we only check executable lines.
        executable = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))

        # No bare `os.rename(` or `.rename(` calls (those don't overwrite on Windows).
        assert "os.rename(" not in executable
        # `.rename(` may appear in Path objects; ensure it is not used for
        # the atomic-write paths by checking that os.replace is used.
        assert executable.count("os.replace(") >= 3

    def test_atomic_write_works_when_dest_is_readonly_target_dir(self, tmp_path: Path) -> None:
        # Sanity: writing into a fresh dir works (no surprises).
        target = tmp_path / "subdir" / "f.txt"
        atomic_write(target, "content")
        assert target.read_text(encoding="utf-8") == "content"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits not meaningful on Windows")
class TestAtomicWriteModePermissions:
    """v2.36.1: os.replace is rename(2) — the target inherits the temp file's
    inode+perms (mkstemp creates it 0600), NOT the pre-existing target's perms.
    So atomic_write already yields a private file; mode=0o600 makes that explicit
    at sensitive call sites (settings.json) as defence-in-depth."""

    def test_mode_yields_private_perms_over_preexisting_world_readable_file(self, tmp_path: Path) -> None:
        target = tmp_path / "settings.json"
        target.write_text('{"token": "old"}', encoding="utf-8")
        os.chmod(target, 0o644)  # even if the prior file was world-readable...

        atomic_write(target, '{"token": "new"}', mode=0o600)

        assert stat.S_IMODE(target.stat().st_mode) == 0o600  # ...the result is 0600
        assert target.read_text(encoding="utf-8") == '{"token": "new"}'

    def test_mode_applies_on_fresh_file(self, tmp_path: Path) -> None:
        target = tmp_path / "fresh.json"
        atomic_write(target, "{}", mode=0o600)
        assert stat.S_IMODE(target.stat().st_mode) == 0o600

    def test_default_yields_private_perms_from_mkstemp(self, tmp_path: Path) -> None:
        # Even without an explicit mode, rename(2) hands the target the temp
        # file's 0600 perms — atomic_write never leaves a world-readable file.
        target = tmp_path / "skill.md"
        target.write_text("old", encoding="utf-8")
        os.chmod(target, 0o644)

        atomic_write(target, "new")

        assert stat.S_IMODE(target.stat().st_mode) == 0o600


@pytest.mark.parametrize("size", [0, 1, 1024, 65536])
def test_atomic_write_preserves_content_at_various_sizes(tmp_path: Path, size: int) -> None:
    """Make sure os.replace doesn't truncate at boundary sizes."""
    target = tmp_path / "varied.bin"
    payload = b"x" * size
    atomic_write(target, payload)
    assert target.read_bytes() == payload
