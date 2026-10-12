"""~/Documents maps to the real Documents folder on Windows (OneDrive redirection).

PowerShell loads $PROFILE from the Documents folder Windows reports, which
OneDrive's folder backup moves to e.g. C:\\Users\\x\\OneDrive - Company\\Dokumente.
SCCS wrote powershell_profile into ~/Documents/PowerShell regardless (2.71.1).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import sccs.utils.paths as paths
from sccs.config.defaults import DEFAULT_CONFIG
from sccs.config.schema import SyncCategory
from sccs.utils.paths import expand_user_path


@pytest.fixture
def onedrive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    documents = tmp_path / "OneDrive - Company" / "Dokumente"
    monkeypatch.setattr(paths, "windows_documents_dir", lambda: documents)
    return documents


@pytest.mark.parametrize(
    ("raw", "rest"),
    [
        ("~/Documents/PowerShell", "PowerShell"),
        ("~\\Documents\\PowerShell", "PowerShell"),
        ("~/documents/PowerShell/conf.d", "PowerShell/conf.d"),
        ("~/Documents", ""),
        ("~/Documents/", ""),
    ],
)
def test_documents_prefix_maps_to_the_known_folder(onedrive, raw, rest):
    expected = onedrive / rest if rest else onedrive
    assert Path(expand_user_path(raw)) == expected


@pytest.mark.parametrize("raw", ["~/DocumentsOld/x", "~/.claude/skills", "/abs/Documents/x", "Documents/x"])
def test_other_paths_are_plain_expanduser(onedrive, raw):
    assert expand_user_path(raw) == str(Path(raw).expanduser())


def test_without_a_known_folder_documents_stays_under_home(monkeypatch):
    monkeypatch.setattr(paths, "windows_documents_dir", lambda: None)

    assert expand_user_path("~/Documents/PowerShell") == str(Path("~/Documents/PowerShell").expanduser())


def test_the_powershell_category_lands_in_the_redirected_folder(onedrive):
    category = SyncCategory.model_validate(DEFAULT_CONFIG["sync_categories"]["powershell_profile"])

    assert Path(category.local_path) == onedrive / "PowerShell"
    # repo_path is relative to the repo and never touched.
    assert category.repo_path == ".config/powershell"


def test_deploy_roots_and_targets_agree_on_the_redirected_folder(onedrive):
    # The deploy ceiling and the deploy target must name the same folder, or
    # every PowerShell item would be refused as "outside the managed roots".
    from sccs.deploy.install import _lexical, _managed_roots

    assert _lexical(Path("~/Documents/PowerShell")) in _managed_roots()


@pytest.mark.skipif(sys.platform == "win32", reason="the real lookup only answers on Windows")
def test_the_lookup_is_off_outside_windows():
    assert paths.windows_documents_dir() is None
