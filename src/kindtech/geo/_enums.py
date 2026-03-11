"""
Strongly-typed enums for ONS geographic data.

These enums represent the different dimensions of geographic boundary datasets
available from the ONS Geoportal (https://geoportal.statistics.gov.uk/).
"""

from enum import Enum
from typing import TypeVar

T = TypeVar("T", bound="ONSGeoEnum")


class ONSGeoEnum(Enum):
    """Base class for ONS geography enums.

    Each enum value has:
      - code: The string code used in API requests and service names
      - description: Human-readable description
    """

    def __init__(self, code, description):
        self.code = code
        self.description = description

    @classmethod
    def from_code(cls: type[T], code) -> T | None:
        """Convert a string code to the corresponding enum value."""
        for item in cls:
            if item.code == code:
                return item
        return None

    @classmethod
    def get_description(cls, code) -> str:
        """Get the human-readable description for a code."""
        item = cls.from_code(code)
        return item.description if item else code


class BoundaryType(ONSGeoEnum):
    """Boundary types/resolutions available from the ONS."""

    BFC = ("BFC", "Full Clipped Boundaries")
    BFE = ("BFE", "Full Extent Boundaries")
    BGC = ("BGC", "Generalised Clipped Boundaries")
    BSC = ("BSC", "Super Generalised Clipped Boundaries")
    BUC = ("BUC", "Ultra Generalised Clipped Boundaries")
    NC = ("NC", "Names and Codes")


class CoverageArea(ONSGeoEnum):
    """Geographic coverage areas."""

    UK = ("UK", "United Kingdom")
    GB = ("GB", "Great Britain")
    EW = ("EW", "England and Wales")
    EN = ("EN", "England")
    WA = ("WA", "Wales")
    SC = ("SC", "Scotland")
    NI = ("NI", "Northern Ireland")


class GeographyType(ONSGeoEnum):
    """Administrative and statistical geography types."""

    # Administrative
    CTRY = ("CTRY", "Countries")
    RGN = ("RGN", "Regions")
    CTY = ("CTY", "Counties")
    CTYUA = ("CTYUA", "Counties and Unitary Authorities")
    LAD = ("LAD", "Local Authority Districts")
    WD = ("WD", "Wards")
    CED = ("CED", "County Electoral Divisions")

    # Statistical
    LSOA = ("LSOA", "Lower Super Output Areas")
    MSOA = ("MSOA", "Middle Super Output Areas")
    OA = ("OA", "Output Areas")
    BUA = ("BUA", "Built-up Areas")
    BUASD = ("BUASD", "Built-up Area Sub-Divisions")
    DZ = ("DZ", "Data Zones")
    IZ = ("IZ", "Intermediate Zones")
    ED = ("ED", "Enumeration Districts")

    # Health
    CCG = ("CCG", "Clinical Commissioning Groups")
    ICB = ("ICB", "Integrated Care Boards")
    CAL = ("CAL", "Cancer Alliances")
    NHSER = ("NHSER", "NHS England Regions")

    # Other
    CAUTH = ("CAUTH", "Combined Authorities")
    CSP = ("CSP", "Community Safety Partnerships")
    FRA = ("FRA", "Fire and Rescue Authorities")
    DCELLS = ("DCELLS", "Dept for Children, Education, Lifelong Learning and Skills")
    EER = ("EER", "European Electoral Regions")
    TTWA = ("TTWA", "Travel to Work Areas")
    ITL = ("ITL", "International Territorial Level")


class Month(ONSGeoEnum):
    """Month indicators used in dataset release dates."""

    JAN = ("JAN", "January")
    FEB = ("FEB", "February")
    MAR = ("MAR", "March")
    APR = ("APR", "April")
    MAY = ("MAY", "May")
    JUN = ("JUN", "June")
    JUL = ("JUL", "July")
    AUG = ("AUG", "August")
    SEP = ("SEP", "September")
    OCT = ("OCT", "October")
    NOV = ("NOV", "November")
    DEC = ("DEC", "December")
