"""Describe a place in England from open data, as totals only.

A place is a local authority (by name or code), a neighbourhood (a 2021 LSOA
code) or a postcode district such as ``SE13``. A full postcode is not accepted,
because nothing tells a venue's postcode from a person's home; it is not looked
up and the answer asks for the district or the place name. The answer comes
from the English Indices of Deprivation 2025. A postcode district is looked up
in the postcode table on this machine when one is installed, and through
postcodes.io when not; the answer says which.

    >>> from uk_open_data.connector import describe_place
    >>> answer = describe_place("Lewisham")
    >>> answer["status"]
    'found'
"""

import logging
import re
from dataclasses import asdict, replace
from functools import lru_cache
from typing import Any

import narwhals.stable.v2 as nw
import requests

from uk_open_data.analyses.sources import IOD_2025, POSTCODES_IO, ons_postcode_lookup
from uk_open_data.connector.privacy import ensure_totals_only, looks_like_postcode
from uk_open_data.imd import imd_path, kept_imd_note, load_imd
from uk_open_data.postcodes import (
    PostcodeTableError,
    district_to_local_authorities,
    lookup_outcodes,
    postcode_table_info,
    postcode_table_path,
)

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

# The 22 local authorities of Wales. The analyses cover them and this tool does
# not, so a Welsh council's name is answered "not covered", not "not found".
WELSH_AUTHORITIES = (
    "Blaenau Gwent",
    "Bridgend",
    "Caerphilly",
    "Cardiff",
    "Carmarthenshire",
    "Ceredigion",
    "Conwy",
    "Denbighshire",
    "Flintshire",
    "Gwynedd",
    "Isle of Anglesey",
    "Merthyr Tydfil",
    "Monmouthshire",
    "Neath Port Talbot",
    "Newport",
    "Pembrokeshire",
    "Powys",
    "Rhondda Cynon Taf",
    "Swansea",
    "Torfaen",
    "Vale of Glamorgan",
    "Wrexham",
)
IN_WALES = (
    "That place is in Wales. This tool describes places in England only, because "
    "the deprivation index it reads is England's. The analyses that cover England "
    "and Wales still work for it."
)
FULL_POSTCODE = (
    "A full postcode is not accepted here, because this tool cannot tell a "
    "venue's postcode from a person's home. It was not looked up or sent "
    "anywhere. Give the first half of the postcode, such as SE13, or the name "
    "of the council area."
)
ADDRESS = (
    "That looks like a street address. Do not send an address to this tool: it "
    "describes areas, not buildings, and an address can be a person's home. It "
    "was not looked up or sent anywhere. Give the name of the council area, or "
    "the first half of the postcode, such as SE13."
)

NO_DOMAINS = (
    "The copy of the deprivation index kept on this machine does not hold the "
    "types of deprivation, so that table is left out."
)

_LSOA_CODE = re.compile(r"^E01\d{6}$")
_AUTHORITY_CODE = re.compile(r"^E0[6-9]\d{6}$")
_OTHER_NATION_CODE = re.compile(r"^[WSN]\d{8}$|^95[A-Z]{2}\d{2}(S\d)?$")
_OUTCODE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?$")
_POSTCODE_INSIDE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}\b")
_BUILDING_NUMBER = re.compile(r"\b\d+[A-Z]?\b")
_STREET_WORD = re.compile(
    r"\b(?:STREET|ST|ROAD|RD|LANE|LN|AVENUE|AVE|CLOSE|DRIVE|WAY|COURT|CRESCENT"
    r"|TERRACE|GARDENS|GROVE|SQUARE|PLACE|WALK|MEWS|ROW|HILL|FLAT|UNIT"
    r"|APARTMENT|HOUSE)\b"
)
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
            (``"E09000023"``), a 2021 LSOA code (``"E01003189"``) or a
            postcode district (``"SE13"``). Not a full postcode and not a
            street address.

    Returns:
        A dict of plain JSON types. ``status`` is one of ``found``, ``choose``
        (several places match; ``matches`` lists them), ``not_found``,
        ``not_covered`` (outside England), ``not_accepted`` (a full postcode or
        a street address, which is never looked up or repeated) or
        ``unavailable`` (a data source could not be reached). When found it
        carries ``place``, ``figures``, ``tables``, ``caveats``, ``warnings``,
        ``sources`` and ``privacy``, in the same shapes an analysis result uses.
    """
    text = " ".join(str(place).split()).upper()
    if not text:
        return _status(
            "not_found", "Give a place name, a postcode district or an area code."
        )
    if looks_like_postcode(text):
        return _status("not_accepted", FULL_POSTCODE)
    if _looks_like_address(text):
        return _status("not_accepted", ADDRESS)
    try:
        return ensure_totals_only(_describe(text))
    except _IndexCopyError:
        logger.warning("The kept copy of the deprivation index could not be read.")
        return _status(
            "unavailable",
            "The deprivation figures kept on this server could not be read. This "
            "is a fault on the server, not in what you asked.",
        )
    except (requests.RequestException, PostcodeTableError) as error:
        # The error text can hold the address asked for, so only its kind is logged.
        logger.warning("A data source could not be reached: %s", type(error).__name__)
        return _status(
            "unavailable",
            "A data source could not be reached just now. Try again in a minute.",
        )


def clear_cache() -> None:
    """Forget the deprivation data held in memory, so the next call loads it."""
    _index.cache_clear()


class _IndexCopyError(RuntimeError):
    """The copy of the index kept on this machine could not be read."""


def _looks_like_address(text: str) -> bool:
    """Whether upper-case ``text`` reads as the address of a building.

    That is a postcode inside other words, or a number beside a word a street
    or building name ends in. No council's name holds a number, so a place
    this tool can describe is never taken for an address.
    """
    if _POSTCODE_INSIDE.search(text):
        return True
    return bool(_BUILDING_NUMBER.search(text) and _STREET_WORD.search(text))


def _describe(text: str) -> dict[str, Any]:
    """Work out what kind of place ``text`` names and describe it."""
    if _OTHER_NATION_CODE.match(text):
        return _not_covered(in_wales=text.startswith("W"))
    if _LSOA_CODE.match(text):
        return _describe_neighbourhood(text, matched_from="neighbourhood_code")
    if _AUTHORITY_CODE.match(text):
        return _describe_authorities(_by_authority_code(text), "local_authority_code")
    if _OUTCODE.match(text):
        return _describe_outcode(text)
    codes = _by_authority_name(text)
    if not codes and _names_welsh_authority(text):
        return _not_covered(in_wales=True)
    return _describe_authorities(codes, "name")


def _describe_outcode(outcode: str) -> dict[str, Any]:
    """Describe the local authority, or authorities, a postcode district covers."""
    found = _authorities_for_outcode(outcode)
    if not found:
        return _status("not_found", "That postcode district was not found.")
    names = _authority_names()
    codes = [code for code in found if code in names]
    if not codes:
        return _not_covered()
    answer = _describe_authorities(codes, "postcode_district")
    answer.setdefault("warnings", []).append(
        "A postcode district is not a statistical area. The figures are for the "
        "whole local authority it falls in."
    )
    return _record_lookup(answer, "One postcode district")


def _authorities_for_outcode(outcode: str) -> list[str]:
    """Local authority codes a postcode district reaches, in and out of England.

    Read from the postcode table on this machine when one is installed.
    Otherwise postcodes.io is asked; it answers with names, so an authority
    outside England comes back as its name and is dropped by the caller.
    """
    if postcode_table_path() is not None:
        return district_to_local_authorities(outcode)
    found = nw.from_native(lookup_outcodes(outcode), eager_only=True).rows(named=True)
    districts = found[0]["admin_districts"] if found and found[0]["valid"] else None
    if not districts:
        return []
    listed = f", {districts}, ".casefold()
    codes = {
        code
        for code, name in _authority_names().items()
        if f", {name}, ".casefold() in listed
    }
    return sorted(codes) or [districts]


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
    domains = [_domain_table(rows)] if _holds_domains(rows) else []
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
        "tables": [_decile_table(rows), *domains],
        "caveats": list(CAVEATS),
        "warnings": [] if domains else [NO_DOMAINS],
        "sources": [_index_source()],
        "privacy": _privacy(),
    }


def _describe_neighbourhood(code: str, matched_from: str) -> dict[str, Any]:
    """Figures for one neighbourhood (2021 LSOA) and its local authority."""
    england = _neighbourhoods()
    row = next((r for r in england if r["geography_code"] == code), None)
    if row is None:
        return _status("not_found", "That neighbourhood code was not found.")
    authority = [r for r in england if r["lad_code"] == row["lad_code"]]
    domains = [_neighbourhood_domain_table(row)] if _holds_domains([row]) else []
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
        "tables": domains,
        "caveats": list(CAVEATS),
        "warnings": [] if domains else [NO_DOMAINS],
        "sources": [_index_source()],
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


def _names_welsh_authority(text: str) -> bool:
    """Whether ``text`` names a local authority in Wales, matched as in England."""
    wanted = _name_key(text)
    keys = [_name_key(name) for name in WELSH_AUTHORITIES]
    return bool(wanted) and any(f" {wanted} " in f" {key} " for key in keys)


def _name_key(name: str) -> str:
    """Reduce a council or area name to the words that identify it."""
    plain = re.sub(r"[^a-z0-9 ]", " ", name.casefold().replace("&", " and "))
    return " ".join(_NAME_NOISE.sub(" ", " ".join(plain.split())).split())


def _authority_names() -> dict[str, str]:
    """Local authority code to name, in name order."""
    names = {row["lad_code"]: row["lad_name"] for row in _neighbourhoods()}
    return dict(sorted(names.items(), key=lambda item: item[1]))


def _neighbourhoods() -> list[dict[str, Any]]:
    """Every neighbourhood in England with its deprivation figures."""
    return _index()[0]


def _index_source() -> dict[str, Any]:
    """The source to cite for the index, which says when a kept copy was read."""
    return dict(_index()[1])


@lru_cache(maxsize=1)
def _index() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load the index for England once: its rows, and the source to cite.

    A copy kept on this machine is read when there is one (see
    :func:`uk_open_data.imd.keep_imd`), and the source then says so.
    """
    kept = imd_path() is not None
    try:
        loaded = load_imd(nation="England")
        note = kept_imd_note()
    except ValueError as error:
        if not kept:
            raise
        raise _IndexCopyError from error
    frame = nw.from_native(loaded, eager_only=True)
    rows = [
        {key: _plain(value) for key, value in row.items()}
        for row in frame.select(_COLUMNS).rows(named=True)
    ]
    source = IOD_2025
    if note is not None:
        edition = f"{IOD_2025.edition}. A copy kept on this machine, {note}"
        source = replace(IOD_2025, edition=edition)
    return rows, asdict(source)


def _holds_domains(rows: list[dict[str, Any]]) -> bool:
    """Whether ``rows`` hold the types of deprivation. A kept copy may not."""
    return all(
        row[f"{domain}_{part}"] is not None
        for row in rows
        for domain in DOMAINS
        for part in ("decile", "rank")
    )


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
    """One headline figure, in the shape an analysis result uses."""
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


def _record_lookup(answer: dict[str, Any], what: str) -> dict[str, Any]:
    """Say how a postcode was placed, and whether it left this machine."""
    if "privacy" not in answer:
        return answer
    if postcode_table_path() is not None:
        info = postcode_table_info()
        source = ons_postcode_lookup(str(info["edition"]), tuple(info["attribution"]))
        answer["privacy"]["notes"].append(
            f"{what} was looked up on this machine. It was not sent anywhere and "
            "is not repeated in this answer."
        )
    else:
        source = POSTCODES_IO
        answer["privacy"]["sent_to_third_parties"] = [
            f"{what} was sent to postcodes.io to find its area. It is not "
            "repeated in this answer."
        ]
    if answer["status"] == "found":
        answer["sources"] = [*answer["sources"], asdict(source)]
    return answer


def _not_covered(*, in_wales: bool = False) -> dict[str, Any]:
    """The answer for a place outside England."""
    if in_wales:
        return _status("not_covered", IN_WALES)
    return _status(
        "not_covered",
        "That place is outside England. Only England is covered so far.",
    )


def _status(status: str, message: str) -> dict[str, Any]:
    """An answer that carries no figures, only what happened."""
    return {"status": status, "message": message, "coverage": COVERAGE}
