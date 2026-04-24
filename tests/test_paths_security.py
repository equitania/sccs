# Tests for symlink-rejection in sccs.utils.paths
# Defence-in-depth against hostile symlinks in tracked sync directories.

import os
import sys

import pytest

from sccs.utils.paths import create_backup, safe_copy

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Symlink semantics differ on Windows and require elevated privileges",
)


class TestSafeCopyRejectsSymlinks:
    """safe_copy() must refuse symlink sources to prevent link-following leaks."""

    def test_rejects_file_symlink(self, temp_dir):
        real = temp_dir / "secret.txt"
        real.write_text("sensitive", encoding="utf-8")
        link = temp_dir / "link.txt"
        os.symlink(real, link)

        with pytest.raises(ValueError, match="Refusing to copy symlink"):
            safe_copy(link, temp_dir / "dest.txt")

    def test_rejects_directory_symlink(self, temp_dir):
        real = temp_dir / "real_dir"
        real.mkdir()
        (real / "file.txt").write_text("x", encoding="utf-8")
        link = temp_dir / "link_dir"
        os.symlink(real, link, target_is_directory=True)

        with pytest.raises(ValueError, match="Refusing to copy symlink"):
            safe_copy(link, temp_dir / "dest_dir")

    def test_accepts_regular_file(self, temp_dir):
        source = temp_dir / "src.txt"
        source.write_text("content", encoding="utf-8")
        dest = temp_dir / "dst.txt"

        safe_copy(source, dest)

        assert dest.read_text(encoding="utf-8") == "content"
        assert not dest.is_symlink()


class TestCreateBackupRejectsSymlinks:
    """create_backup() must refuse symlink sources to prevent link-following leaks."""

    def test_rejects_symlink(self, temp_dir, temp_home):
        real = temp_dir / "secret.txt"
        real.write_text("sensitive", encoding="utf-8")
        link = temp_dir / "link.txt"
        os.symlink(real, link)

        with pytest.raises(ValueError, match="Refusing to backup symlink"):
            create_backup(link, category="test")

    def test_accepts_regular_file(self, temp_dir, temp_home):
        source = temp_dir / "plain.txt"
        source.write_text("data", encoding="utf-8")

        backup = create_backup(source, category="test")

        assert backup is not None
        assert backup.exists()
        assert not backup.is_symlink()

    def test_missing_path_returns_none(self, temp_dir, temp_home):
        assert create_backup(temp_dir / "nope.txt", category="test") is None
