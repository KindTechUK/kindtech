"""Smoke-test an installed KindTech distribution with one DataFrame backend."""

import sys

from kindtech.ons import list_tables


def main() -> None:
    """Verify KindTech selects and uses the requested isolated backend."""
    expected_backend = sys.argv[1]
    tables = list_tables()
    actual_backend = type(tables).__module__.partition(".")[0]

    assert actual_backend == expected_backend
    assert len(tables) > 0
    assert set(tables.columns) == {"id", "name", "sourceName"}


if __name__ == "__main__":
    main()
