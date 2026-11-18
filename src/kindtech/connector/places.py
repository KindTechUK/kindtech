"""Describe a place in England from open data, as totals only.

A place is a local authority (by name or code), a neighbourhood (a 2021 LSOA
code), a postcode district such as ``SE13``, or the postcode of a venue or
office. The answer comes from the English Indices of Deprivation 2025 and never
repeats a postcode that was passed in.

    >>> from kindtech.connector import describe_place
    >>> answer = describe_place("Lewisham")
    >>> answer["status"]
    'found'
"""

import logging
import re
from dataclasses import asdict
from functools import lru_cache
from typing import Any

import narwhals.stable.v2 as nw
import requests

from kindtech.connector.privacy import ensure_totals_only
from kindtech.imd import load_imd
from kindtech.lenses.sources import IOD_2025, POSTCODES_IO
from kindtech.postcodes import lookup_outcodes, lookup_postcodes

logger = logging.getLogger(__name__)

COVERAGE = "England"
MAX_MATCHES = 10

DOMAINS = {
    "income": "Income",
    "employment": "Employment",
    "education": "Education, skills and training",
    "health": "Health and disability",
    "crime": "Crime",
    "housing": "Barriers to housing and services",
    "living_environment": "Living environment",
}

CAVEATS = [
    "The Indices of Deprivation rank neighbourhoods against each other. They do "
    "not measure how deprived any one person or household is.",
    "Not everyone in a deprived neighbourhood is deprived, and many deprived "
    "people live elsewhere.",
    "Deciles compare neighbourhoods across England only. They cannot be compared "
    "with Wales, Scotland or Northern Ireland.",
]

_LSOA_CODE = re.compile(r"^E01\d{6}$")
_AUTHORITY_CODE = re.compile(r"^E0[6-9]\d{6}$")
_OTHER_NATION_CODE = re.compile(r"^[WSN]\d{8}$|^95[A-Z]{2}\d{2}(S\d)?$")
_POSTCODE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$")
_OUTCODE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?$")
_NAME_NOISE = re.compile(
    r"\b(?:(?:london |royal |metropolitan )?borough(?: council)?(?: of)?"
    r"|(?:city|county|district) council|council|(?:city|county) of|the)\b"
)

_COLUMNS = [
    "geography_code",
    "geography_name",
    "lad_code",
    "lad_name",
    "imd_rank",
    "imd_decile",
    "population",
    *(f"{domain}_decile" for domain in DOMAINS),
    *(f"{domain}_rank" for domain in DOMAINS),
]


def describe_place(place: str) -> dict[str, Any]:
    """Describe a place in England using the Indices of Deprivation 2025.

    Args:
        place: A local authority name (``"Lewisham"``) or code
            (``"E09000023"``), a 2021 LSOA code (``"E01003189"``), a postcode
            district (``"SE13"``), or the postcode of a venue or office. Do not
            pass the postcode of a client or any other individual.

    Returns:
        A dict of plain JSON types. ``status`` is one of ``found``, ``choose``
        (several places match; ``matches`` lists them), ``not_found``,
        ``not_covered`` (outside England) or ``unavailable`` (a data source
        could not be reached). When found it carries ``place``, ``figures``,
        ``tables``, ``caveats``, ``warnings``, ``sources`` and ``privacy``, in
        the same shapes a lens result uses. A postcode passed in is never
        repeated in the answer.
    """
    text = " ".join(str(place).split()).upper()
    if not text:
        return _status("not_found", "Give a place name, a postcode or an area code.")
    row_values = [text] if _POSTCODE.match(text) else []
    try:
        return ensure_totals_only(_describe(text), row_values)
    except requests.RequestException as error:
        # The error text can hold the address asked for, so only its kind is logged.
        logger.warning("A data source could not be reached: %s", type(error).__name__)
        return _status(
            "unavailable",
            "A data source could not be reached just now. Try again in a minute.",
        )


def clear_cache() -> None:
    """Forget the downloaded deprivation data, so the next call fetches it."""
    _neighbourhoods.cache_clear()


def _describe(text: str) -> dict[str, Any]:
    """Work out what kind of place ``text`` names and describe it."""
    if _OTHER_NATION_CODE.match(text):
        return _not_covered()
    if _LSOA_CODE.match(text):
        return _describe_neighbourhood(text, matched_from="neighbourhood_code")
    if _AUTHORITY_CODE.match(text):
        return _describe_authorities(_by_authority_code(text), "local_authority_code")
    if _POSTCODE.match(text):
        return _describe_postcode(text)
    if _OUTCODE.match(text):
        return _describe_outcode(text)
    return _describe_authorities(_by_authority_name(text), "name")


def _describe_postcode(postcode: str) -> dict[str, Any]:
    """Describe the neighbourhood a full postcode sits in, without repeating it."""
    found = nw.from_native(lookup_postcodes(postcode), eager_only=True).rows(named=True)
    code = found[0]["lsoa_code"] if found and found[0]["valid"] else None
    if not code:
        return _status("not_found", "That postcode was not found.")
    if not str(code).startswith("E"):
        return _not_covered()
    answer = _describe_neighbourhood(str(code), matched_from="postcode")
    return _sent_to_postcodes_io(answer, "One postcode")


def _describe_outcode(outcode: str) -> dict[str, Any]:
    """Describe the local authority, or authorities, a postcode district covers."""
    found = nw.from_native(lookup_outcodes(outcode), eager_only=True).rows(named=True)
    districts = found[0]["admin_districts"] if found and found[0]["valid"] else None
    if not districts:
        return _status("not_found", "That postcode district was not found.")
    listed = f", {districts}, ".casefold()
    codes = sorted(
        {
            row["lad_code"]
            for row in _neighbourhoods()
            if f", {row['lad_name']}, ".casefold() in listed
        }
    )
    if not codes:
        return _not_covered()
    answer = _describe_authorities(codes, "postcode_district")
    answer.setdefault("warnings", []).append(
        "A postcode district is not a statistical area. The figures are for the "
        "whole local authority it falls in."
    )
    return _sent_to_postcodes_io(answer, "One postcode district")


def _describe_authorities(codes: list[str], matched_from: str) -> dict[str, Any]:
    """Describe one local authority, or ask the caller to choose between several."""
    if not codes:
        return _status(
            "not_found",
            "No local authority in England matched. Try the council's name, a "
            "postcode district such as SE13, or an area code.",
        )
    if len(codes) > 1:
        names = _authority_names()
        matches = [
            {"kind": "local_authority", "code": code, "name": names[code]}
            for code in codes[:MAX_MATCHES]
        ]
        answer = _status(
            "choose",
            "More than one local authority matched. Ask which one is meant, then "
            "call again with its code.",
        )
        return {**answer, "matches": matches, "privacy": _privacy()}
    return _describe_authority(codes[0], matched_from)


def _describe_authority(code: str, matched_from: str) -> dict[str, Any]:
    """Totals for one local authority."""
    rows = [row for row in _neighbourhoods() if row["lad_code"] == code]
    england = _neighbourhoods()
    return {
        "status": "found",
        "place": {
            "kind": "local_authority",
            "code": code,
            "name": rows[0]["lad_name"],
            "matched_from": matched_from,
            "coverage": COVERAGE,
        },
        "figures": _authority_figures(rows, england),
        "tables": [_decile_table(rows), _domain_table(rows)],
        "caveats": list(CAVEATS),
        "warnings": [],
        "sources": [asdict(IOD_2025)],
        "privacy": _privacy(),
    }


def _describe_neighbourhood(code: str, matched_from: str) -> dict[str, Any]:
    """Figures for one neighbourhood (2021 LSOA) and its local authority."""
    england = _neighbourhoods()
    row = next((r for r in england if r["geography_code"] == code), None)
    if row is None:
        return _status("not_found", "That neighbourhood code was not found.")
    authority = [r for r in england if r["lad_code"] == row["lad_code"]]
    return {
        "status": "found",
        "place": {
            "kind": "neighbourhood",
            "code": code,
            "name": row["geography_name"],
            "local_authority": {"code": row["lad_code"], "name": row["lad_name"]},
            "matched_from": matched_from,
            "coverage": COVERAGE,
        },
        "figures": _neighbourhood_figures(row, authority, len(england)),
        "tables": [_neighbourhood_domain_table(row)],
        "caveats": list(CAVEATS),
        "warnings": [],
        "sources": [asdict(IOD_2025)],
        "privacy": _privacy(),
    }


def _authority_figures(
    rows: list[dict[str, Any]], england: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Headline figures for a local authority."""
    residents = _residents(rows)
    most_10 = [row for row in rows if row["imd_decile"] == 1]
    most_20 = [row for row in rows if row["imd_decile"] <= 2]
    england_20 = [row for row in england if row["imd_decile"] <= 2]
    return [
        _figure("neighbourhoods", "Neighbourhoods (2021 LSOAs)", len(rows), "count"),
        _figure("residents", "Residents", residents, "people", "Mid-2022 estimate."),
        _figure(
            "share_neighbourhoods_most_deprived_10",
            "Neighbourhoods among the most deprived 10% in England",
            _percent(len(most_10), len(rows)),
            "percent",
        ),
        _figure(
            "share_neighbourhoods_most_deprived_20",
            "Neighbourhoods among the most deprived 20% in England",
            _percent(len(most_20), len(rows)),
            "percent",
        ),
        _figure(
            "share_residents_most_deprived_20",
            "Residents living in those most deprived 20% of neighbourhoods",
            _percent(_residents(most_20), residents),
            "percent",
        ),
        _figure(
            "england_share_residents_most_deprived_20",
            "The same share for England as a whole, for comparison",
            _percent(_residents(england_20), _residents(england)),
            "percent",
        ),
    ]


def _neighbourhood_figures(
    row: dict[str, Any], authority: list[dict[str, Any]], england_total: int
) -> list[dict[str, Any]]:
    """Headline figures for one neighbourhood."""
    most_20 = [r for r in authority if r["imd_decile"] <= 2]
    return [
        _figure(
            "imd_decile",
            "Deprivation decile",
            row["imd_decile"],
            "decile",
            "1 is the most deprived 10% of neighbourhoods in England, 10 the least.",
        ),
        _figure(
            "imd_rank",
            "Deprivation rank",
            row["imd_rank"],
            "rank",
            f"Out of {england_total:,} neighbourhoods in England. 1 is the most "
            "deprived.",
        ),
        _figure(
            "residents", "Residents", row["population"], "people", "Mid-2022 estimate."
        ),
        _figure(
            "local_authority_share_neighbourhoods_most_deprived_20",
            f"Neighbourhoods in {row['lad_name']} among the most deprived 20% in "
            "England",
            _percent(len(most_20), len(authority)),
            "percent",
        ),
    ]


def _decile_table(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Neighbourhoods and residents by national deprivation decile."""
    residents = _residents(rows)
    table_rows = []
    for decile in range(1, 11):
        in_decile = [row for row in rows if row["imd_decile"] == decile]
        table_rows.append(
            {
                "imd_decile": decile,
                "neighbourhoods": len(in_decile),
                "residents": _residents(in_decile),
                "share_of_residents": _percent(_residents(in_decile), residents),
            }
        )
    return {
        "id": "by_decile",
        "title": "Neighbourhoods and residents by deprivation decile (1 is the "
        "most deprived)",
        "columns": [
            "imd_decile",
            "neighbourhoods",
            "residents",
            "share_of_residents",
        ],
        "rows": table_rows,
        "detail": False,
    }


def _domain_table(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Share of neighbourhoods in the most deprived 20% for each domain."""
    table_rows = []
    for domain, label in DOMAINS.items():
        most_20 = [row for row in rows if row[f"{domain}_decile"] <= 2]
        table_rows.append(
            {
                "domain": label,
                "neighbourhoods_most_deprived_20": len(most_20),
                "share_of_neighbourhoods": _percent(len(most_20), len(rows)),
            }
        )
    table_rows.sort(key=lambda r: r["neighbourhoods_most_deprived_20"], reverse=True)
    return {
        "id": "by_domain",
        "title": "Neighbourhoods among the most deprived 20% in England, by type "
        "of deprivation",
        "columns": [
            "domain",
            "neighbourhoods_most_deprived_20",
            "share_of_neighbourhoods",
        ],
        "rows": table_rows,
        "detail": False,
    }


def _neighbourhood_domain_table(row: dict[str, Any]) -> dict[str, Any]:
    """One neighbourhood's decile and rank for each type of deprivation."""
    table_rows = [
        {
            "domain": label,
            "decile": row[f"{domain}_decile"],
            "rank": row[f"{domain}_rank"],
        }
        for domain, label in DOMAINS.items()
    ]
    return {
        "id": "by_domain",
        "title": "Decile and rank by type of deprivation (1 is the most deprived)",
        "columns": ["domain", "decile", "rank"],
        "rows": sorted(table_rows, key=lambda r: r["rank"]),
        "detail": False,
    }


def _by_authority_code(code: str) -> list[str]:
    """The code itself, when it is a local authority in the data."""
    return [code] if code in _authority_names() else []


def _by_authority_name(text: str) -> list[str]:
    """Codes of the local authorities whose name matches ``text``."""
    wanted = _name_key(text)
    if not wanted:
        return []
    keys = {code: _name_key(name) for code, name in _authority_names().items()}
    exact = [code for code, key in keys.items() if key == wanted]
    if exact:
        return exact
    return [code for code, key in keys.items() if f" {wanted} " in f" {key} "]


def _name_key(name: str) -> str:
    """Reduce a council or area name to the words that identify it."""
    plain = re.sub(r"[^a-z0-9 ]", " ", name.casefold().replace("&", " and "))
    return " ".join(_NAME_NOISE.sub(" ", " ".join(plain.split())).split())


def _authority_names() -> dict[str, str]:
    """Local authority code to name, in name order."""
    names = {row["lad_code"]: row["lad_name"] for row in _neighbourhoods()}
    return dict(sorted(names.items(), key=lambda item: item[1]))


@lru_cache(maxsize=1)
def _neighbourhoods() -> list[dict[str, Any]]:
    """Every neighbourhood in England with its deprivation figures (cached)."""
    frame = nw.from_native(load_imd(nation="England"), eager_only=True)
    return [
        {key: _plain(value) for key, value in row.items()}
        for row in frame.select(_COLUMNS).rows(named=True)
    ]


def _plain(value: Any) -> Any:
    """Turn a DataFrame cell into a plain ``str``, ``int`` or ``None``."""
    if value is None or isinstance(value, str):
        return value
    if value != value:  # NaN
        return None
    return int(value)


def _residents(rows: list[dict[str, Any]]) -> int:
    """Total residents across ``rows``."""
    return sum(row["population"] or 0 for row in rows)


def _percent(part: int, whole: int) -> float | None:
    """``part`` as a percentage of ``whole``, to one decimal place."""
    return round(100 * part / whole, 1) if whole else None


def _figure(
    figure_id: str, label: str, value: Any, unit: str, note: str = ""
) -> dict[str, Any]:
    """One headline figure, in the shape a lens result uses."""
    return {
        "id": figure_id,
        "label": label,
        "value": value,
        "unit": unit,
        "note": note,
        "suppressed": False,
    }


def _privacy() -> dict[str, Any]:
    """The privacy block for an answer built only from published totals."""
    return {
        "row_level_output": False,
        "sent_to_third_parties": [],
        "notes": [
            "Built from published statistics about areas. Nothing here is about "
            "an individual."
        ],
    }


def _sent_to_postcodes_io(answer: dict[str, Any], what: str) -> dict[str, Any]:
    """Record that a lookup was sent to postcodes.io, when the answer has figures."""
    if "privacy" not in answer:
        return answer
    answer["privacy"]["sent_to_third_parties"] = [
        f"{what} was sent to postcodes.io to find its area. It is not repeated "
        "in this answer."
    ]
    if answer["status"] == "found":
        answer["sources"] = [*answer["sources"], asdict(POSTCODES_IO)]
    return answer


def _not_covered() -> dict[str, Any]:
    """The answer for a place outside England."""
    return _status(
        "not_covered",
        "That place is outside England. Only England is covered so far.",
    )


def _status(status: str, message: str) -> dict[str, Any]:
    """An answer that carries no figures, only what happened."""
    return {"status": status, "message": message, "coverage": COVERAGE}
