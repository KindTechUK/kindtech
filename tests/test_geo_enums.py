"""
Unit tests for the KindTech Geo enums.
"""

from kindtech.geo._enums import (
    BoundaryType,
    CoverageArea,
    GeographyType,
    Month,
)


def test_from_code_valid():
    """Test from_code returns the correct enum member."""
    assert GeographyType.from_code("LAD") is GeographyType.LAD
    assert BoundaryType.from_code("BGC") is BoundaryType.BGC
    assert CoverageArea.from_code("UK") is CoverageArea.UK
    assert Month.from_code("JAN") is Month.JAN


def test_from_code_invalid():
    """Test from_code returns None for unknown codes."""
    assert GeographyType.from_code("INVALID") is None
    assert BoundaryType.from_code("XXX") is None


def test_get_description_valid():
    """Test get_description returns the human-readable description."""
    assert GeographyType.get_description("LAD") == "Local Authority Districts"
    assert BoundaryType.get_description("BGC") == "Generalised Clipped Boundaries"
    assert CoverageArea.get_description("UK") == "United Kingdom"


def test_get_description_invalid():
    """Test get_description returns the code itself when not found."""
    assert GeographyType.get_description("UNKNOWN") == "UNKNOWN"


def test_enum_code_and_description_attributes():
    """Test that enum members expose code and description."""
    lad = GeographyType.LAD
    assert lad.code == "LAD"
    assert lad.description == "Local Authority Districts"

    month = Month.JAN
    assert month.code == "JAN"
    assert month.description == "January"
