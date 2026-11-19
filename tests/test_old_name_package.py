"""
Unit tests for the ``kindtech`` distribution kept for the package's old name.

It is built from ``packaging/kindtech`` and published beside ``uk-open-data``.
"""

from importlib.metadata import requires, version
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).parent.parent
OLD_NAME_FOLDER = REPOSITORY / "packaging" / "kindtech"


def test_the_old_name_has_the_same_version_as_the_package():
    assert version("kindtech") == version("uk-open-data")


def test_the_old_name_depends_on_exactly_that_version():
    pinned = version("uk-open-data")
    assert requires("kindtech") == [
        f"uk-open-data=={pinned}",
        f'uk-open-data[connector]=={pinned}; extra == "connector"',
    ]


@pytest.mark.parametrize("name", ["LICENSE", "NOTICE"])
def test_the_old_name_carries_the_same_licence_files(name):
    assert (OLD_NAME_FOLDER / name).read_bytes() == (REPOSITORY / name).read_bytes()
