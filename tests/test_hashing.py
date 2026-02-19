# Tests for sccs.utils.hashing
# Content hashing for change detection

from sccs.utils.hashing import (
    content_hash,
    directory_hash,
    file_hash,
    get_mtime,
    quick_compare,
)


class TestContentHash:
    """Tests for content_hash."""

    def test_string_input(self):
        h = content_hash("hello")
        assert isinstance(h, str)
        assert len(h) == 64  # SHA256 hex length

    def test_bytes_input(self):
        h = content_hash(b"hello")
        assert h == content_hash("hello")

    def test_deterministic(self):
        assert content_hash("test") == content_hash("test")

    def test_different_content(self):
        assert content_hash("a") != content_hash("b")

    def test_empty_string(self):
        h = content_hash("")
        assert isinstance(h, str)
        assert len(h) == 64


class TestFileHash:
    """Tests for file_hash."""

    def test_existing_file(self, temp_dir):
        f = temp_dir / "test.txt"
        f.write_text("hello", encoding="utf-8")
        h = file_hash(f)
        assert h is not None
        assert len(h) == 64

    def test_nonexistent_file(self, temp_dir):
        assert file_hash(temp_dir / "missing.txt") is None

    def test_directory_returns_none(self, temp_dir):
        assert file_hash(temp_dir) is None

    def test_same_content_same_hash(self, temp_dir):
        f1 = temp_dir / "a.txt"
        f2 = temp_dir / "b.txt"
        f1.write_text("same", encoding="utf-8")
        f2.write_text("same", encoding="utf-8")
        assert file_hash(f1) == file_hash(f2)

    def test_different_content_different_hash(self, temp_dir):
        f1 = temp_dir / "a.txt"
        f2 = temp_dir / "b.txt"
        f1.write_text("one", encoding="utf-8")
        f2.write_text("two", encoding="utf-8")
        assert file_hash(f1) != file_hash(f2)


class TestDirectoryHash:
    """Tests for directory_hash."""

    def test_existing_directory(self, temp_dir):
        d = temp_dir / "testdir"
        d.mkdir()
        (d / "a.txt").write_text("content a", encoding="utf-8")
        (d / "b.txt").write_text("content b", encoding="utf-8")
        h = directory_hash(d)
        assert h is not None
        assert len(h) == 64

    def test_nonexistent_directory(self, temp_dir):
        assert directory_hash(temp_dir / "missing") is None

    def test_file_returns_none(self, temp_dir):
        f = temp_dir / "file.txt"
        f.write_text("test", encoding="utf-8")
        assert directory_hash(f) is None

    def test_deterministic(self, temp_dir):
        d = temp_dir / "testdir"
        d.mkdir()
        (d / "a.txt").write_text("content", encoding="utf-8")
        assert directory_hash(d) == directory_hash(d)

    def test_content_change_changes_hash(self, temp_dir):
        d = temp_dir / "testdir"
        d.mkdir()
        f = d / "a.txt"
        f.write_text("v1", encoding="utf-8")
        h1 = directory_hash(d)
        f.write_text("v2", encoding="utf-8")
        h2 = directory_hash(d)
        assert h1 != h2

    def test_exclude_patterns(self, temp_dir):
        d = temp_dir / "testdir"
        d.mkdir()
        (d / "keep.txt").write_text("keep", encoding="utf-8")
        (d / "skip.tmp").write_text("skip", encoding="utf-8")
        h_all = directory_hash(d)
        h_filtered = directory_hash(d, exclude_patterns=["*.tmp"])
        assert h_all != h_filtered

    def test_without_names(self, temp_dir):
        d = temp_dir / "testdir"
        d.mkdir()
        (d / "file.txt").write_text("content", encoding="utf-8")
        h_with = directory_hash(d, include_names=True)
        h_without = directory_hash(d, include_names=False)
        assert h_with != h_without

    def test_empty_directory(self, temp_dir):
        d = temp_dir / "empty"
        d.mkdir()
        h = directory_hash(d)
        assert h is not None


class TestQuickCompare:
    """Tests for quick_compare."""

    def test_same_files(self, temp_dir):
        f1 = temp_dir / "a.txt"
        f2 = temp_dir / "b.txt"
        f1.write_text("same", encoding="utf-8")
        f2.write_text("same", encoding="utf-8")
        assert quick_compare(f1, f2) is True

    def test_different_files(self, temp_dir):
        f1 = temp_dir / "a.txt"
        f2 = temp_dir / "b.txt"
        f1.write_text("one", encoding="utf-8")
        f2.write_text("two two", encoding="utf-8")
        assert quick_compare(f1, f2) is False

    def test_both_missing(self, temp_dir):
        assert quick_compare(temp_dir / "a", temp_dir / "b") is True

    def test_one_missing(self, temp_dir):
        f = temp_dir / "a.txt"
        f.write_text("test", encoding="utf-8")
        assert quick_compare(f, temp_dir / "missing") is False

    def test_same_directories(self, temp_dir):
        d1 = temp_dir / "dir1"
        d2 = temp_dir / "dir2"
        d1.mkdir()
        d2.mkdir()
        (d1 / "f.txt").write_text("same", encoding="utf-8")
        (d2 / "f.txt").write_text("same", encoding="utf-8")
        assert quick_compare(d1, d2) is True

    def test_different_directories(self, temp_dir):
        d1 = temp_dir / "dir1"
        d2 = temp_dir / "dir2"
        d1.mkdir()
        d2.mkdir()
        (d1 / "f.txt").write_text("one", encoding="utf-8")
        (d2 / "f.txt").write_text("two", encoding="utf-8")
        assert quick_compare(d1, d2) is False

    def test_type_mismatch(self, temp_dir):
        f = temp_dir / "file.txt"
        d = temp_dir / "dir"
        f.write_text("test", encoding="utf-8")
        d.mkdir()
        assert quick_compare(f, d) is False


class TestGetMtime:
    """Tests for get_mtime."""

    def test_file_mtime(self, temp_dir):
        f = temp_dir / "test.txt"
        f.write_text("test", encoding="utf-8")
        mtime = get_mtime(f)
        assert mtime is not None
        assert isinstance(mtime, float)

    def test_missing_path(self, temp_dir):
        assert get_mtime(temp_dir / "missing") is None

    def test_directory_mtime(self, temp_dir):
        d = temp_dir / "testdir"
        d.mkdir()
        (d / "file.txt").write_text("content", encoding="utf-8")
        mtime = get_mtime(d)
        assert mtime is not None

    def test_empty_directory_mtime(self, temp_dir):
        d = temp_dir / "empty"
        d.mkdir()
        mtime = get_mtime(d)
        assert mtime is not None
