"""Shared test set-up."""

import logging
from collections.abc import Iterator

import connector_fakes as fakes
import pytest
import requests

from uk_open_data.analyses import reach_deprivation
from uk_open_data.analyses.access_distance import clear_centres_cache
from uk_open_data.analyses.maps import clear_outline_cache
from uk_open_data.analyses.need_reach import clear_need_cache
from uk_open_data.analyses.who_we_miss import clear_residents_cache
from uk_open_data.connector import analyses, maps, places
from uk_open_data.postcodes import build_postcode_table, install_postcode_table, offline


@pytest.fixture(autouse=True)
def empty_data_dir(tmp_path, monkeypatch):
    """Point downloaded data at an empty folder, so no test sees a real table."""
    folder = tmp_path / "kindtech-data"
    monkeypatch.setenv(offline.DATA_DIR_VARIABLE, str(folder))
    return folder


@pytest.fixture(autouse=True)
def no_outlines_from_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand in for the boundary service, which no test may ask, as if it were down."""

    def down(*args: object, **kwargs: object) -> None:
        raise requests.ConnectionError("the boundary service is not asked in tests")

    monkeypatch.setattr(maps, "load_map_boundaries", down)


@pytest.fixture(autouse=True)
def outlines_log_put_back() -> Iterator[None]:
    """Undo what a test did to the logger of the code that asks for outlines."""
    log = logging.getLogger(maps.OUTLINES_LOGGER)
    handlers, propagate = list(log.handlers), log.propagate
    yield
    log.handlers[:] = handlers
    log.propagate = propagate


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
def analysis_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap the analysis engine for a fake with two analyses, one without counts."""
    monkeypatch.setattr(analyses, "engine", fakes.fake_engine())


@pytest.fixture
def leaky_analysis_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install a fake analysis engine that repeats an input value in its result."""
    monkeypatch.setattr(analyses, "engine", fakes.fake_engine(leak=True))


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
    clear_outline_cache()
    yield
    clear_need_cache()
    clear_residents_cache()
    clear_centres_cache()
    clear_outline_cache()
