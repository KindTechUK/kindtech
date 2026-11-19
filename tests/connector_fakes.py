"""Stand-ins for the connector tests: a small England and a fake analysis engine.

The deprivation rows are invented and tiny, but have the columns
``load_imd(nation="England")`` returns. The fake engine stands in for
``uk_open_data.analyses`` where a test needs an analysis the real engine does not
have: one with no counts mode, or one that breaks the contract.
"""

from types import SimpleNamespace
from typing import Any

import pandas as pd

from uk_open_data._mapping import geo_code_field
from uk_open_data.connector.places import DOMAINS

# (LSOA code, LSOA name, LAD code, LAD name, rank, decile, residents)
_AREAS = [
    ("E01000001", "Lewisham 001A", "E09000023", "Lewisham", 1, 1, 1500),
    ("E01000002", "Lewisham 001B", "E09000023", "Lewisham", 2, 2, 1700),
    ("E01000003", "Lewisham 002A", "E09000023", "Lewisham", 6, 5, 1800),
    ("E01000004", "Lewisham 002B", "E09000023", "Lewisham", 10, 10, 2000),
    (
        "E01000005",
        "Newcastle upon Tyne 001A",
        "E08000021",
        "Newcastle upon Tyne",
        3,
        3,
        1600,
    ),
    (
        "E01000006",
        "Newcastle upon Tyne 001B",
        "E08000021",
        "Newcastle upon Tyne",
        7,
        7,
        1400,
    ),
    (
        "E01000007",
        "Newcastle-under-Lyme 001A",
        "E07000195",
        "Newcastle-under-Lyme",
        8,
        8,
        1300,
    ),
    ("E01000008", "Bristol 001A", "E06000023", "Bristol, City of", 4, 4, 1900),
    ("E01000009", "Bristol 001B", "E06000023", "Bristol, City of", 5, 5, 2100),
    ("E01000010", "County Durham 001A", "E06000047", "County Durham", 9, 9, 1200),
]

# A postcode that must never appear in any tool result.
SECRET_POSTCODE = "ZZ99 9KC"


# The ONS postcode lookup in miniature: postcode, 2021 LSOA, local authority.
# The last row is in Wales, which the table keeps and the connector does not cover.
POSTCODE_LOOKUP_CSV = (
    "pcd7,lsoa21cd,ladcd\n"
    "ZZ999KC,E01000001,E09000023\n"
    "ZZ998VC,E01000005,E08000021\n"
    "CF101VC,W01000001,W06000015\n"
)


# Invented need figures for real local authority codes: code, name, people in
# need. There are sixteen, so the top quarter is the last four, and those are
# high need.
NEED = (
    ("E06000002", "Middlesbrough", 100),
    ("E06000003", "Redcar and Cleveland", 200),
    ("E06000004", "Stockton-on-Tees", 300),
    ("E06000005", "Darlington", 400),
    ("E06000006", "Halton", 500),
    ("E06000007", "Warrington", 600),
    ("E06000008", "Blackburn with Darwen", 700),
    ("E06000009", "Blackpool", 800),
    ("E06000053", "Isles of Scilly", 20),
    ("E07000223", "Adur", 1000),
    ("E06000001", "Hartlepool", 3000),
    ("E09000011", "Greenwich", 8000),
    ("E09000023", "Lewisham", 9000),
    ("W06000015", "Cardiff", 10000),
    ("E08000003", "Manchester", 20000),
    ("E08000025", "Birmingham", 40000),
)


# Invented residents by ethnic group for real local authority codes: code,
# name, residents by census group. Each place has 300,000 residents.
RESIDENTS = (
    (
        "E09000023",
        "Lewisham",
        {
            "Asian": 30000,
            "Black": 75000,
            "Mixed": 24000,
            "White": 156000,
            "Other": 15000,
        },
    ),
    (
        "E09000011",
        "Greenwich",
        {
            "Asian": 45000,
            "Black": 60000,
            "Mixed": 18000,
            "White": 165000,
            "Other": 12000,
        },
    ),
)


def england_frame() -> pd.DataFrame:
    """A ten-neighbourhood England in the shape ``load_imd`` returns."""
    rows = []
    for code, name, lad_code, lad_name, rank, decile, residents in _AREAS:
        row: dict[str, Any] = {
            "geography_code": code,
            "geography_name": name,
            "lad_code": lad_code,
            "lad_name": lad_name,
            "imd_score": 50.0 - rank,
            "imd_rank": rank,
            "imd_decile": decile,
            "population": float(residents),
            "nation": "E",
        }
        for position, domain in enumerate(DOMAINS):
            # Income follows the overall decile; later domains drift less deprived.
            row[f"{domain}_decile"] = min(10, decile + position)
            row[f"{domain}_rank"] = min(10, rank + position)
        rows.append(row)
    return pd.DataFrame(rows)


def square_outlines(result: Any) -> dict[str, Any]:
    """Invented outlines for a result's map: one small square for each area."""
    spec = result.map
    field = geo_code_field(spec.geography_type, spec.geography_year)
    features = [
        {
            "type": "Feature",
            "properties": {field: row[spec.code_column]},
            "geometry": {"type": "Polygon", "coordinates": [_square(number)]},
        }
        for number, row in enumerate(result.table(spec.table).rows)
    ]
    return {"type": "FeatureCollection", "features": features}


def _square(number: int) -> list[list[float]]:
    """A small square, laid out in a row of five."""
    west = -0.05 + 0.01 * (number % 5)
    south = 51.40 + 0.01 * (number // 5)
    return [
        [west, south],
        [west + 0.01, south],
        [west + 0.01, south + 0.01],
        [west, south + 0.01],
        [west, south],
    ]


def outcode_frame(admin_districts: str | None) -> pd.DataFrame:
    """What ``lookup_outcodes`` returns for one postcode district."""
    return pd.DataFrame(
        [
            {
                "outcode": "ZZ99",
                "valid": admin_districts is not None,
                "admin_districts": admin_districts,
            }
        ]
    )


class AnalysisInputError(ValueError):
    """The fake engine's input error, with ``problems`` like the real one."""

    def __init__(
        self,
        problems: list[str],
        *,
        option: str | None = None,
        role: str | None = None,
    ) -> None:
        super().__init__(" ".join(problems))
        self.problems = problems
        self.option = option
        self.role = role


REACH = {
    "id": "reach-deprivation",
    "title": "Reach against deprivation",
    "question": "Are we reaching people in the most deprived neighbourhoods?",
    "summary": "Shares of the people you supplied by deprivation decile.",
    "version": "0.1",
    "roles": [
        {"name": "postcode", "description": "A postcode", "example": "SE13 7VC"},
        {"name": "lsoa_code", "description": "2021 LSOA", "example": "E01003189"},
        {
            "name": "count",
            "description": "People in the area",
            "example": 12,
            "amount": True,
        },
    ],
    "input_modes": [
        {
            "name": "postcodes",
            "description": "One row per person",
            "roles": ["postcode"],
            "aggregated": False,
        },
        {
            "name": "neighbourhood_counts",
            "description": "Already totalled by neighbourhood",
            "roles": ["lsoa_code", "count"],
            "aggregated": True,
        },
    ],
    "options": [{"name": "suppress_below", "description": "Hide below", "default": 5}],
    "coverage": "England",
}
VOLUNTEERS = {
    "id": "volunteer-travel",
    "title": "Volunteer travel",
    "question": "How far do our volunteers travel?",
    "summary": "Distance bands for volunteers.",
    "version": "0.1",
    "roles": [{"name": "postcode", "description": "A postcode", "example": "SE13 7VC"}],
    "input_modes": [
        {
            "name": "postcodes",
            "description": "One row per person",
            "roles": ["postcode"],
            "aggregated": False,
        }
    ],
    "options": [],
    "coverage": "England",
}


COUNCILS = {
    "id": "reach-by-council",
    "title": "Reach by council",
    "question": "Which councils do the people we help live in?",
    "summary": "People you supplied by local authority.",
    "version": "0.1",
    "roles": [
        {
            "name": "local_authority",
            "description": "A local authority name or code",
            "example": "Lewisham",
            "reported": True,
        },
        {
            "name": "count",
            "description": "People in the area",
            "example": 12,
            "amount": True,
        },
    ],
    "input_modes": [
        {
            "name": "area_counts",
            "description": "Already totalled by local authority",
            "roles": ["local_authority", "count"],
            "aggregated": True,
        }
    ],
    "options": [],
    "coverage": "England",
}


GROUPS = {
    "id": "reach-by-group",
    "title": "Reach by group",
    "question": "Which groups do the people we help belong to?",
    "summary": "People you supplied by census group.",
    "version": "0.1",
    "roles": [
        {
            "name": "group",
            "description": "The group, in the charity's own words",
            "example": "Black Caribbean",
            "reported": True,
            "reported_values": ["Asian", "Black", "Mixed", "White", "Other"],
        },
        {
            "name": "count",
            "description": "People in the group",
            "example": 12,
            "amount": True,
        },
    ],
    "input_modes": [
        {
            "name": "group_counts",
            "description": "Already totalled by group",
            "roles": ["group", "count"],
            "aggregated": True,
        }
    ],
    "options": [],
    "coverage": "England",
}


def fake_engine(*, leak: bool = False) -> SimpleNamespace:
    """A stand-in for ``uk_open_data.analyses``.

    Args:
        leak: When true, results repeat the first row's area or group in a
            warning. That breaks the contract unless the role is marked
            ``reported`` and allows the value, so the privacy guard can be
            tested both ways. The council and group analyses are only offered
            here, so a search still finds two analyses otherwise.

    ``runs`` on the stand-in lists each answer counted through ``record_run``.
    """
    analyses = {REACH["id"]: REACH, VOLUNTEERS["id"]: VOLUNTEERS}
    if leak:
        analyses[COUNCILS["id"]] = COUNCILS
        analyses[GROUPS["id"]] = GROUPS

    def list_analyses() -> list[SimpleNamespace]:
        return [describe_analysis(analysis_id) for analysis_id in analyses]

    def describe_analysis(analysis_id: str) -> SimpleNamespace:
        info = analyses[analysis_id]
        return SimpleNamespace(id=info["id"], to_dict=lambda: info)

    def run_analysis(
        analysis_id: str,
        data: list[dict[str, Any]],
        columns: dict[str, str] | None = None,
        options: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        if any(not isinstance(row["count"], int) for row in data):
            raise AnalysisInputError(
                ["Some counts are not whole numbers."], role="count"
            )
        total = sum(row["count"] for row in data)
        area = next(value for value in data[0].values() if isinstance(value, str))
        warnings = [f"{area} looks unusual"] if leak else []
        payload = {
            "analysis_id": analysis_id,
            "input_mode": "neighbourhood_counts",
            "figures": [
                {
                    "id": "people_supplied",
                    "label": "People supplied",
                    "value": total,
                    "unit": "people",
                    "note": "",
                    "suppressed": False,
                }
            ],
            "tables": [
                {
                    "id": "by_neighbourhood",
                    "title": "By neighbourhood",
                    "columns": ["lsoa_code", "band"],
                    "rows": [],
                    "detail": True,
                }
            ],
            "checks": [{"id": "period", "question": "Which period?", "why": "Context"}],
            "caveats": ["Counts are not need."],
            "warnings": warnings,
            "sources": [],
            "privacy": {
                "suppress_below": (options or {}).get("suppress_below", 5),
                "cells_suppressed": 0,
                "row_level_output": False,
                "sent_to_third_parties": [],
                "notes": [],
            },
        }

        def to_dict(include_detail: bool = True) -> dict[str, Any]:
            if include_detail:
                rows = [{"lsoa_code": r["lsoa_code"], "band": "1-9"} for r in data]
                detailed = {**payload["tables"][0], "rows": rows}
                return {**payload, "tables": [detailed]}
            return payload

        return SimpleNamespace(
            to_dict=to_dict,
            map=None,
            analysis_id=analysis_id,
            input_mode=payload["input_mode"],
        )

    runs: list[tuple[str, str, str]] = []

    def record_run(analysis_id: str, input_mode: str, door: str) -> None:
        runs.append((analysis_id, input_mode, door))

    return SimpleNamespace(
        list_analyses=list_analyses,
        describe_analysis=describe_analysis,
        run_analysis=run_analysis,
        record_run=record_run,
        runs=runs,
        AnalysisInputError=AnalysisInputError,
    )
