# Tests for sccs.output.console
# Rich-based console output

from io import StringIO

from rich.console import Console as RichConsole

from sccs.output.console import Console, create_console
from sccs.sync.actions import ActionType
from sccs.sync.category import CategoryStatus, CategorySyncResult
from sccs.sync.engine import SyncResult


def _make_console(verbose: bool = False) -> Console:
    """Create a console with captured output."""
    console = Console(verbose=verbose, colored=False)
    console._console = RichConsole(file=StringIO(), no_color=True)
    return console


def _get_output(console: Console) -> str:
    """Get captured output from console."""
    console._console.file.seek(0)
    return console._console.file.read()


class TestConsoleBasic:
    """Tests for basic console methods."""

    def test_print(self):
        c = _make_console()
        c.print("hello world")
        assert "hello world" in _get_output(c)

    def test_print_error(self):
        c = _make_console()
        c.print_error("something failed")
        output = _get_output(c)
        assert "Error:" in output
        assert "something failed" in output

    def test_print_warning(self):
        c = _make_console()
        c.print_warning("be careful")
        output = _get_output(c)
        assert "Warning:" in output
        assert "be careful" in output

    def test_print_success(self):
        c = _make_console()
        c.print_success("all good")
        assert "all good" in _get_output(c)

    def test_print_info(self):
        c = _make_console()
        c.print_info("fyi")
        assert "fyi" in _get_output(c)


class TestConsoleStatus:
    """Tests for status display."""

    def test_print_empty_statuses(self):
        c = _make_console()
        c.print_status({})
        assert "No categories" in _get_output(c)

    def test_print_status_with_category(self):
        c = _make_console()
        status = CategoryStatus(
            name="test_cat",
            enabled=True,
            total_items=3,
            unchanged=2,
            to_sync=1,
            conflicts=0,
            errors=0,
            actions=[],
        )
        c.print_status({"test_cat": status})
        output = _get_output(c)
        assert "test_cat" in output
        assert "3 items" in output

    def test_print_disabled_category(self):
        c = _make_console()
        status = CategoryStatus(
            name="disabled_cat",
            enabled=False,
        )
        c.print_status({"disabled_cat": status})
        output = _get_output(c)
        assert "Disabled" in output

    def test_print_empty_category(self):
        c = _make_console()
        status = CategoryStatus(
            name="empty_cat",
            enabled=True,
            total_items=0,
        )
        c.print_status({"empty_cat": status})
        assert "No items found" in _get_output(c)

    def test_print_status_with_platform(self):
        c = _make_console()
        status = CategoryStatus(
            name="plat_cat",
            enabled=True,
            total_items=1,
            unchanged=1,
            platforms=["macos", "linux"],
        )
        c.print_status({"plat_cat": status})
        output = _get_output(c)
        assert "macos" in output


class TestConsoleActionIcons:
    """Tests for action icon mapping."""

    def test_all_action_types_have_icons(self):
        c = _make_console()
        for action_type in ActionType:
            icon = c._get_action_icon(action_type)
            assert icon is not None
            assert icon != "?"


class TestConsoleSyncResult:
    """Tests for sync result display."""

    def test_print_successful_result(self):
        c = _make_console()
        result = SyncResult(
            success=True,
            total_categories=2,
            synced_categories=2,
            synced_items=5,
            conflicts=0,
            errors=0,
            category_results={},
        )
        c.print_sync_result(result)
        output = _get_output(c)
        assert "Sync completed" in output
        assert "5 synced" in output

    def test_print_dry_run_result(self):
        c = _make_console()
        result = SyncResult(
            success=True,
            total_categories=1,
            synced_categories=1,
            synced_items=3,
            conflicts=0,
            errors=0,
            category_results={},
        )
        c.print_sync_result(result, dry_run=True)
        output = _get_output(c)
        assert "Dry run completed" in output
        assert "would sync" in output

    def test_print_failed_result(self):
        c = _make_console()
        result = SyncResult(
            success=False,
            total_categories=1,
            synced_categories=0,
            synced_items=0,
            conflicts=0,
            errors=2,
            category_results={},
        )
        c.print_sync_result(result)
        output = _get_output(c)
        assert "with errors" in output


class TestConsoleCategoryResult:
    """Tests for category result display."""

    def test_no_changes_result(self):
        c = _make_console()
        cat_result = CategorySyncResult(name="test", success=True, synced=0, conflicts=0, errors=0, results=[])
        c._print_category_result("test", cat_result)
        assert "no changes" in _get_output(c)

    def test_synced_result(self):
        c = _make_console()
        cat_result = CategorySyncResult(name="test", success=True, synced=3, conflicts=0, errors=0, results=[])
        c._print_category_result("test", cat_result)
        assert "3 synced" in _get_output(c)


class TestConsoleCategoriesList:
    """Tests for categories list display."""

    def test_print_categories(self):
        c = _make_console()
        cats = {
            "skills": {"enabled": True, "description": "Claude skills", "platforms": None},
            "fish": {"enabled": False, "description": "Fish config", "platforms": ["macos"]},
        }
        c.print_categories_list(cats, show_all=True)
        output = _get_output(c)
        assert "skills" in output
        assert "fish" in output

    def test_print_only_enabled(self):
        c = _make_console()
        cats = {
            "skills": {"enabled": True, "description": "Claude skills", "platforms": None},
            "fish": {"enabled": False, "description": "Fish config", "platforms": None},
        }
        c.print_categories_list(cats, show_all=False)
        output = _get_output(c)
        assert "skills" in output


class TestCreateConsole:
    """Tests for create_console factory."""

    def test_default(self):
        c = create_console()
        assert isinstance(c, Console)
        assert c.verbose is False

    def test_verbose(self):
        c = create_console(verbose=True)
        assert c.verbose is True
