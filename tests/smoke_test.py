"""Smoke-test an installed distribution of the package."""

from importlib.resources import files
from importlib.util import find_spec

import uk_open_data
from uk_open_data.cli import main as cli_main


def main() -> None:
    """Verify the installed package and its bundled catalogs are usable."""
    geo_catalog = files("uk_open_data.geo").joinpath("data/arcgis_services.csv")
    ons_catalog = files("uk_open_data.ons").joinpath("data/nomis_tables.csv")

    assert uk_open_data.__version__ != "0.0.0"
    assert geo_catalog.is_file()
    assert ons_catalog.is_file()
    assert geo_catalog.read_text(encoding="utf-8").splitlines()[0] == (
        "arcgis_id,geography,year,month,region,resolution"
    )
    assert ons_catalog.read_text(encoding="utf-8").splitlines()[0] == (
        "id,name,sourceName"
    )
    # The command line and the analysis list work with no DataFrame backend.
    assert cli_main(["analysis", "list"]) == 0
    # The old name is a distribution of its own and is not part of this one.
    assert find_spec("kindtech") is None


if __name__ == "__main__":
    main()
