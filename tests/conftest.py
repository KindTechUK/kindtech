"""Shared test set-up."""

import connector_fakes as fakes
import pytest

from kindtech.connector import lenses, places
from kindtech.lenses import reach_deprivation
from kindtech.postcodes import offline


@pytest.fixture(autouse=True)
def empty_data_dir(tmp_path, monkeypatch):
    """Point downloaded data at an empty folder, so no test sees a real table."""
    folder = tmp_path / "kindtech-data"
    monkeypatch.setenv(offline.DATA_DIR_VARIABLE, str(folder))
    return folder


@pytest.fixture
def england(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the deprivation download with a ten-neighbourhood England."""
    places.clear_cache()
    for module in (places, reach_deprivation):
        monkeypatch.setattr(
            module, "load_imd", lambda *args, **kwargs: fakes.england_frame()
        )
    yield
    places.clear_cache()


@pytest.fixture
def lens_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap the lens engine for a fake with two lenses, one without counts."""
    monkeypatch.setattr(lenses, "engine", fakes.fake_engine())


@pytest.fixture
def leaky_lens_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install a fake lens engine that repeats an input value in its result."""
    monkeypatch.setattr(lenses, "engine", fakes.fake_engine(leak=True))
