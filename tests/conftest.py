"""Shared test set-up."""

import connector_fakes as fakes
import pytest

from uk_open_data.analyses import reach_deprivation
from uk_open_data.analyses.access_distance import clear_centres_cache
from uk_open_data.analyses.need_reach import clear_need_cache
from uk_open_data.analyses.who_we_miss import clear_residents_cache
from uk_open_data.connector import lenses, places
from uk_open_data.postcodes import build_postcode_table, install_postcode_table, offline


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


@pytest.fixture
def postcode_table(tmp_path, empty_data_dir) -> None:
    """Install a three-postcode table, so postcodes are placed on this machine."""
    source = tmp_path / "lookup.csv"
    source.write_text(fakes.POSTCODE_LOOKUP_CSV, encoding="utf-8")
    packed = tmp_path / "postcodes.ktpc.gz"
    build_postcode_table(source, packed, "May 2026")
    install_postcode_table(packed)


@pytest.fixture(autouse=True)
def fresh_public_figures():
    """Start and end every test with no public figures kept from another test."""
    clear_need_cache()
    clear_residents_cache()
    clear_centres_cache()
    yield
    clear_need_cache()
    clear_residents_cache()
    clear_centres_cache()
