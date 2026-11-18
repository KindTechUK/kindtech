"""Shared test set-up."""

import pytest

from kindtech.postcodes import offline


@pytest.fixture(autouse=True)
def empty_data_dir(tmp_path, monkeypatch):
    """Point downloaded data at an empty folder, so no test sees a real table."""
    folder = tmp_path / "kindtech-data"
    monkeypatch.setenv(offline.DATA_DIR_VARIABLE, str(folder))
    return folder
