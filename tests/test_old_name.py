"""
Unit tests for the package's old name, ``kindtech``.

Each check that depends on a fresh import runs in a new Python process, so the
result does not depend on which test imported the old name first.
"""

import subprocess
import sys
import unittest.mock as mock
import warnings

import pytest

import uk_open_data
from uk_open_data.postcodes import offline


def _python(code: str, *flags: str) -> subprocess.CompletedProcess:
    """Run a few lines in a new Python process."""
    return subprocess.run(
        [sys.executable, *flags, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.fixture
def old_name():
    """Import the old name without the warning it gives the first time."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        import kindtech

        return kindtech


def test_the_old_name_is_the_same_package(old_name):
    assert old_name is uk_open_data
    assert old_name.__version__ == uk_open_data.__version__
    assert old_name.load_ons is uk_open_data.load_ons


def test_modules_under_the_old_name_are_the_same_objects(old_name):
    import kindtech.analyses.need_reach
    import kindtech.geo
    import kindtech.postcodes.offline

    import uk_open_data.analyses.need_reach
    import uk_open_data.geo

    assert kindtech.geo is uk_open_data.geo
    assert kindtech.analyses.need_reach is uk_open_data.analyses.need_reach
    assert kindtech.postcodes.offline is offline
    # Each module still knows itself by its real name.
    assert offline.__name__ == "uk_open_data.postcodes.offline"
    assert offline.__spec__.name == "uk_open_data.postcodes.offline"


def test_names_can_be_imported_from_the_old_name(old_name):
    from kindtech.analyses import run_analysis
    from kindtech.geo import load_geodata

    assert load_geodata is uk_open_data.geo.load_geodata
    assert run_analysis is uk_open_data.analyses.run_analysis


def test_a_patch_by_the_old_name_patches_the_real_module(old_name):
    with mock.patch("kindtech.postcodes.offline.TABLE_FILE_NAME", "other.ktpc"):
        assert offline.TABLE_FILE_NAME == "other.ktpc"
    assert offline.TABLE_FILE_NAME == "postcodes.ktpc"


def test_a_module_that_does_not_exist_is_not_found(old_name):
    with pytest.raises(ModuleNotFoundError, match="kindtech.nothing"):
        import kindtech.nothing  # noqa: F401


def test_importing_the_old_name_warns_once():
    code = (
        "import warnings\n"
        "with warnings.catch_warnings(record=True) as caught:\n"
        "    warnings.simplefilter('always')\n"
        "    import kindtech\n"
        "    import kindtech.geo\n"
        "    from kindtech.ons import load_ons\n"
        "print(len(caught), caught[0].category.__name__, caught[0].message)\n"
    )
    done = _python(code)
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("1 DeprecationWarning The 'kindtech' package is now")
    assert "uk_open_data" in done.stdout


def test_a_submodule_imported_first_by_the_old_name_is_loaded_once():
    code = (
        "import warnings; warnings.simplefilter('ignore')\n"
        "import kindtech.analyses.need_reach as old\n"
        "import sys, uk_open_data.analyses.need_reach as new\n"
        "print(old is new, sys.modules['kindtech.analyses'] is sys.modules"
        "['uk_open_data.analyses'])\n"
    )
    done = _python(code)
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["True", "True"]


def test_the_new_name_gives_no_warning():
    done = _python("import uk_open_data.analyses", "-W", "error::DeprecationWarning")
    assert done.returncode == 0, done.stderr


def test_the_connector_command_runs_by_the_old_module_name():
    pytest.importorskip("mcp")
    done = subprocess.run(
        [sys.executable, "-W", "ignore", "-m", "kindtech.connector", "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert "--transport" in done.stdout


# --- the data folder --------------------------------------------------------


@pytest.fixture
def no_folder_named(monkeypatch, tmp_path):
    """Name no data folder, and keep the cache under a temporary folder."""
    monkeypatch.delenv(offline.DATA_DIR_VARIABLE, raising=False)
    monkeypatch.delenv(offline.OLD_DATA_DIR_VARIABLE, raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    return tmp_path


def test_the_new_variable_names_the_data_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("UK_OPEN_DATA_DIR", str(tmp_path / "new"))
    monkeypatch.setenv("KINDTECH_DATA_DIR", str(tmp_path / "old"))
    assert offline.data_dir() == tmp_path / "new"


def test_the_old_variable_still_names_the_data_folder(monkeypatch, tmp_path):
    monkeypatch.delenv("UK_OPEN_DATA_DIR", raising=False)
    monkeypatch.setenv("KINDTECH_DATA_DIR", str(tmp_path / "old"))
    assert offline.data_dir() == tmp_path / "old"


def test_the_data_folder_has_the_new_name_by_default(no_folder_named):
    assert offline.data_dir() == no_folder_named / "uk-open-data"


def test_an_old_data_folder_is_used_until_there_is_a_new_one(no_folder_named):
    (no_folder_named / "kindtech").mkdir()
    assert offline.data_dir() == no_folder_named / "kindtech"
    (no_folder_named / "uk-open-data").mkdir()
    assert offline.data_dir() == no_folder_named / "uk-open-data"
