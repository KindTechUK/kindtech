"""Stand-ins for the connector tests: a small England and a fake lens engine.

The deprivation rows are invented and tiny, but have the columns
``load_imd(nation="England")`` returns. The fake engine stands in for
``kindtech.lenses`` where a test needs a lens the real engine does not have: one
with no counts mode, or one that breaks the contract.
"""

from types import SimpleNamespace
from typing import Any

import pandas as pd

from kindtech.connector.places import DOMAINS

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
SECRET_POSTCODE = "ZZ99 9ZZ"


# The ONS postcode lookup in miniature: postcode, 2021 LSOA, local authority.
# The last row is in Wales, which the table keeps and the connector does not cover.
POSTCODE_LOOKUP_CSV = (
    "pcd7,lsoa21cd,ladcd\n"
    "ZZ999ZZ,E01000001,E09000023\n"
    "ZZ998VC,E01000005,E08000021\n"
    "CF101VC,W01000001,W06000015\n"
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


def postcode_frame(lsoa_code: str | None) -> pd.DataFrame:
    """What ``lookup_postcodes`` returns for one postcode."""
    return pd.DataFrame(
        [
            {
                "postcode": SECRET_POSTCODE,
                "valid": lsoa_code is not None,
                "lsoa_code": lsoa_code,
            }
        ]
    )


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


class LensInputError(ValueError):
    """The fake engine's input error, with ``problems`` like the real one."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__(" ".join(problems))
        self.problems = problems


REACH = {
    "id": "reach-deprivation",
    "title": "Reach against deprivation",
    "question": "Are we reaching people in the most deprived neighbourhoods?",
    "summary": "Shares of the people you supplied by deprivation decile.",
    "version": "0.1",
    "roles": [
        {"name": "postcode", "description": "A postcode", "example": "SE13 7VC"},
        {"name": "lsoa_code", "description": "2021 LSOA", "example": "E01003189"},
        {"name": "count", "description": "People in the area", "example": 12},
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


def fake_engine(*, leak: bool = False) -> SimpleNamespace:
    """A stand-in for ``kindtech.lenses``.

    Args:
        leak: When true, results break the contract by repeating an input area
            code in a warning, so the privacy guard can be tested.
    """
    lenses = {REACH["id"]: REACH, VOLUNTEERS["id"]: VOLUNTEERS}

    def list_lenses() -> list[SimpleNamespace]:
        return [describe_lens(lens_id) for lens_id in lenses]

    def describe_lens(lens_id: str) -> SimpleNamespace:
        info = lenses[lens_id]
        return SimpleNamespace(id=info["id"], to_dict=lambda: info)

    def run_lens(
        lens_id: str,
        data: list[dict[str, Any]],
        columns: dict[str, str] | None = None,
        options: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        if any(not isinstance(row["count"], int) for row in data):
            raise LensInputError(["Some counts are not whole numbers."])
        total = sum(row["count"] for row in data)
        warnings = [f"{data[0]['lsoa_code']} looks unusual"] if leak else []
        payload = {
            "lens_id": lens_id,
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

        return SimpleNamespace(to_dict=to_dict)

    return SimpleNamespace(
        list_lenses=list_lenses,
        describe_lens=describe_lens,
        run_lens=run_lens,
        LensInputError=LensInputError,
    )
