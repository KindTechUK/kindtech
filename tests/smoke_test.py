"""Smoke-test an installed KindTech distribution."""

from importlib.resources import files

import kindtech
from kindtech.cli import main as cli_main


def main() -> None:
    """Verify the installed package and its bundled catalogs are usable."""
    geo_catalog = files("kindtech.geo").joinpath("data/arcgis_services.csv")
    ons_catalog = files("kindtech.ons").joinpath("data/nomis_tables.csv")

    assert kindtech.__version__ != "0.0.0"
    assert geo_catalog.is_file()
    assert ons_catalog.is_file()
    assert geo_catalog.read_text(encoding="utf-8").splitlines()[0] == (
        "arcgis_id,geography,year,month,region,resolution"
    )
    assert ons_catalog.read_text(encoding="utf-8").splitlines()[0] == (
        "id,name,sourceName"
    )
    # The command line and the lens list work with no DataFrame backend.
    assert cli_main(["lens", "list"]) == 0


if __name__ == "__main__":
    main()
