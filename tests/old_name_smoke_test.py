"""Smoke-test an installed ``kindtech`` distribution, the package's old name."""

import warnings
from importlib.metadata import version


def main() -> None:
    """Verify the old name installs the package and imports the same modules."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        import kindtech.geo
    import uk_open_data

    about_the_name = [w for w in caught if "kindtech" in str(w.message)]
    assert [w.category for w in about_the_name] == [DeprecationWarning]
    assert kindtech.geo is uk_open_data.geo
    assert kindtech.__version__ == uk_open_data.__version__
    assert version("kindtech") == version("uk-open-data")


if __name__ == "__main__":
    main()
