"""Tests for kindtech.ons._ingestion helpers."""

import pytest

from kindtech.ons._ingestion import (
    _extract_source,
    _fetch_all,
    ingest_nomis_tables,
)

# -- _extract_source ---------------------------------------------------------


def test_extract_source_returns_matching_text() -> None:
    kf = {
        "annotations": {
            "annotation": [
                {
                    "annotationtitle": "contenttype/sources",
                    "annotationtext": "Census 2021",
                },
            ],
        },
    }
    assert _extract_source(kf) == "Census 2021"


def test_extract_source_skips_non_matching_annotations() -> None:
    kf = {
        "annotations": {
            "annotation": [
                {
                    "annotationtitle": "other/title",
                    "annotationtext": "Ignored",
                },
            ],
        },
    }
    assert _extract_source(kf) == ""


def test_extract_source_no_annotations() -> None:
    assert _extract_source({}) == ""


def test_extract_source_empty_annotation_list() -> None:
    kf: dict = {"annotations": {"annotation": []}}
    assert _extract_source(kf) == ""


def test_extract_source_skips_non_dict_annotation() -> None:
    """Non-dict entries in the annotation list are safely skipped."""
    kf = {
        "annotations": {
            "annotation": [
                "just a string",
                {
                    "annotationtitle": "contenttype/sources",
                    "annotationtext": "Census",
                },
            ],
        },
    }
    assert _extract_source(kf) == "Census"


def test_extract_source_missing_text_returns_empty() -> None:
    kf = {
        "annotations": {
            "annotation": [
                {"annotationtitle": "contenttype/sources"},
            ],
        },
    }
    assert _extract_source(kf) == ""


# -- _fetch_all error handling ------------------------------------------------


def test_fetch_all_raises_on_bad_structure(monkeypatch) -> None:
    """_fetch_all raises RuntimeError on unexpected response shape."""

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"unexpected": "shape"}

    monkeypatch.setattr(
        "kindtech.ons._ingestion.requests.get",
        lambda *a, **kw: FakeResponse(),
    )
    with pytest.raises(RuntimeError, match="Unexpected NOMIS API response"):
        _fetch_all()


# -- ingest_nomis_tables guard -----------------------------------------------


def test_ingest_raises_on_empty_result(monkeypatch) -> None:
    """ingest_nomis_tables raises when _fetch_all returns nothing."""
    monkeypatch.setattr(
        "kindtech.ons._ingestion._fetch_all",
        lambda base_url: [],
    )
    with pytest.raises(RuntimeError, match="No datasets returned"):
        ingest_nomis_tables()
