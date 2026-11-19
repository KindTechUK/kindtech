"""
Unit tests for the provision gap analysis.

The need figures and the postcode lookup are replaced with small invented
tables, so the tests are isolated and repeatable.
"""

import json
import unittest.mock as mock
import xml.etree.ElementTree as ET

import pandas as pd
import pytest
from working_checks import check_working

from uk_open_data.analyses import (
    AnalysisInputError,
    describe_analysis,
    render_map,
    run_analysis,
)
from uk_open_data.analyses._need import FEW_PLACES, ONE_PLACE
from uk_open_data.analyses.need_reach import NEED_BANDS, keep_need_figures
from uk_open_data.analyses.provision_gap import NO_PROVISION, PROVISION_BANDS
from uk_open_data.cli import EXIT_OK, main
from uk_open_data.connector.privacy import find_row_values
from uk_open_data.postcodes import build_postcode_table, install_postcode_table

ANALYSIS_ID = "provision-gap"
COLUMNS = {"local_authority": "Area", "volume": "Sessions"}

# Invented need figures for real local authority codes. There are sixteen, so
# the top quarter is the last four, and those are high need.
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


class _Nomis:
    """Stands in for Nomis and records what it was asked."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, dict]] = []

    def load(self, dataset: str, **query) -> pd.DataFrame:
        """Return each authority's need split over two rows, as Nomis would."""
        self.asked.append((dataset, query))
        rows = [
            {"geography_code": code, "geography_name": name, "obs_value": need / 2}
            for code, name, need in NEED
            for _ in range(2)
        ]
        return pd.DataFrame(rows)


@pytest.fixture
def nomis():
    """Replace the need figures with the invented ones."""
    fake = _Nomis()
    with mock.patch("uk_open_data.analyses._need.load_ons", side_effect=fake.load):
        yield fake


def _volumes(**sessions: float) -> list[dict]:
    """Rows of volume by local authority name, with the user's column names."""
    return [
        {"Area": name.replace("_", " "), "Sessions": amount}
        for name, amount in sessions.items()
    ]


# Sessions for each 1,000 people: Lewisham 10, Greenwich 5, Adur 10, Manchester 1.
SPREAD = _volumes(Lewisham=90, Greenwich=40, Adur=10, Manchester=20)


def _run(rows, options=None, columns=COLUMNS):
    return run_analysis(ANALYSIS_ID, rows, columns=columns, options=options)


def _names(table) -> list[str]:
    return [row["geography_name"] for row in table.rows]


def _by_name(table) -> dict[str, dict]:
    return {row["geography_name"]: row for row in table.rows}


# --- the analysis is listed ----------------------------------------------------


def test_analysis_is_described():
    info = describe_analysis(ANALYSIS_ID)
    assert info.question == "Where is provision thin against need across a region?"
    modes = {mode.name: mode for mode in info.input_modes}
    assert list(modes) == ["sites", "area_volumes", "site_list"]
    assert modes["sites"].roles == ("postcode", "volume")
    assert modes["area_volumes"].aggregated
    assert not modes["sites"].aggregated
    assert not modes["site_list"].aggregated
    # The analysis hides nothing, so it has no threshold to set.
    assert [option.name for option in info.options] == [
        "postcode_lookup",
        "need",
        "catchment",
        "top",
    ]
    assert info.coverage == "England and Wales"
    # Local authorities are public places the result names. Nothing else may
    # come back from the input as text.
    reported = {role.name: role.reported for role in info.roles}
    assert reported == {"postcode": False, "local_authority": True, "volume": False}


def test_needs_can_be_picked_from_a_list():
    need = next(o for o in describe_analysis(ANALYSIS_ID).options if o.name == "need")
    assert need.default == "residents"
    assert [choice.value for choice in need.choices] == [
        "unemployed",
        "unemployed_women",
        "unemployed_men",
        "residents",
    ]


# --- figures ---------------------------------------------------------------


def test_figures_from_area_volumes(nomis):
    result = _run(SPREAD)
    assert result.input_mode == "area_volumes"
    values = {figure.id: figure.value for figure in result.figures}
    assert values == {
        "volume_supplied": 160,
        "volume_located": 160,
        "volume_in_catchment": 160,
        "areas_compared": 16,
        "areas_without_provision": 12,
        "people_in_need": 94620,
        "volume_per_1000_in_need": 1.69,
        "high_need_areas": 4,
        "high_need_areas_without_provision": 2,
        "share_of_provision_in_high_need_areas": 68.8,
        "share_of_need_in_high_need_areas": 83.5,
    }


def test_the_default_need_is_everyone_who_lives_there(nomis):
    result = _run(SPREAD)
    dataset, query = nomis.asked[0]
    assert dataset == "NM_2028_1"
    assert query["c_sex"] == 0
    assert query["measures"] == 20100
    assert result.figure("people_in_need").label.endswith("(Residents of every age)")
    assert any("Not all of them need" in caveat for caveat in result.caveats)


def test_need_can_be_another_built_in_measure(nomis):
    result = _run(SPREAD, options={"need": "unemployed_women"})
    dataset, query = nomis.asked[0]
    assert dataset == "NM_2124_1"
    assert query["c_sex"] == [1]
    assert "women" in result.figure("people_in_need").label


def test_kept_need_figures_are_used_and_nothing_is_fetched(nomis):
    doubled = [(code, name, need * 2) for code, name, need in NEED]
    keep_need_figures("residents", doubled, "invented for a test.")
    result = _run(SPREAD)
    assert nomis.asked == []
    assert result.figure("people_in_need").value == 189240
    assert result.sources[0].edition.endswith("invented for a test.")


@pytest.mark.parametrize("need", ["everyone", 7, None, {"dataset": "NM_1_1"}])
def test_bad_need_is_rejected(nomis, need):
    with pytest.raises(
        AnalysisInputError, match="People you are trying to reach"
    ) as caught:
        _run(SPREAD, options={"need": need})
    assert caught.value.option == "need"


# --- the answer ------------------------------------------------------------


def test_answer_says_where_need_is_high_and_provision_is_thin(nomis):
    result = _run(SPREAD)
    # The default sets provision against every resident, which is not a
    # need, so the sentence does not call it one.
    assert result.answer == (
        "83.5% of residents live in the 4 local authorities with the most "
        "residents, and 68.8% of your provision is there. The places to look "
        "at first, with the most residents and the thinnest provision, are "
        "Birmingham, Cardiff and Manchester."
    )
    assert result.key_figures == (
        "share_of_provision_in_high_need_areas",
        "share_of_need_in_high_need_areas",
        "high_need_areas_without_provision",
    )
    assert {figure.id for figure in result.figures} >= set(result.key_figures)
    assert result.to_dict()["answer"] == result.answer


def test_labels_follow_the_measure(nomis):
    # The default sets provision against every resident, so no label, heading,
    # title or chart calls it a need.
    result = _run(SPREAD)
    labels = {figure.id: figure.label for figure in result.figures}
    assert labels["share_of_need_in_high_need_areas"] == (
        "Share of residents who live in those local authorities"
    )
    assert labels["high_need_areas_without_provision"] == (
        "The local authorities with the most residents where you provide nothing"
    )
    assert labels["people_in_need"] == (
        "People in the area you serve (Residents of every age)"
    )
    # One word for what is provided, and the rate's label says its own unit.
    assert labels["volume_supplied"] == "Provision in the data you gave"
    assert labels["volume_in_catchment"] == "Provision in the area you serve"
    assert labels["volume_per_1000_in_need"] == (
        "Provision per 1,000 residents, across the area"
    )
    table = result.table("priority_areas")
    assert table.title == "Places with the most residents, thinnest provision first"
    assert table.headings["volume_per_1000_in_need"] == (
        "Provision per 1,000 residents"
    )
    charts = [chart.title for chart in result.charts]
    assert charts == [
        "Residents in the places listed",
        "Provision per 1,000 residents in the places listed",
    ]
    layers = [layer.label for layer in result.map.layers]
    assert layers == ["Residents", "Provision per 1,000 residents"]
    assert result.map.title == "Residents and provision, by local authority"
    read = [*labels.values(), table.title, *table.headings.values(), *charts]
    read += [*layers, result.map.title, result.map.layers[0].note]
    assert not [text for text in read if "need" in text.lower()]
    assert not any("high need" in caveat for caveat in result.caveats)
    # The working, the check and the source follow the measure too.
    said = [step.detail for step in result.working]
    said += [source.used_for for source in result.sources]
    assert not [text for text in said if "in need" in text or "high need" in text]
    option = {o.name: o for o in describe_analysis(ANALYSIS_ID).options}["need"]
    choice = next(c for c in result.choices if c.id == "need")
    assert choice.label == option.label == "People you are trying to reach"
    check = next(c for c in result.checks if c.id == "need_fits")
    assert "Change 'People you are trying to reach'" in check.why
    chosen = _run(SPREAD, options={"need": "unemployed"})
    labels = {figure.id: figure.label for figure in chosen.figures}
    assert labels["high_need_areas_without_provision"] == (
        "High-need local authorities where you provide nothing"
    )
    assert chosen.table("priority_areas").title == (
        "Places with high need, thinnest provision first"
    )
    assert chosen.charts[0].title == "People in need in the places listed"


def test_answer_says_need_when_a_need_is_chosen(nomis):
    result = _run(SPREAD, options={"need": "unemployed"})
    assert result.answer.startswith(
        "83.5% of the people in need live in the 4 local authorities with high "
        "need, and 68.8% of your provision is there. The places to look at "
        "first, with high need and the thinnest provision, are "
    )


def test_answer_does_not_name_a_place_with_more_provision_than_the_area(nomis):
    # Lewisham is the one high-need place of the three, and it has more
    # provision for its people than the area as a whole, so it is no gap.
    result = _run(
        _volumes(Lewisham=90, Greenwich=40, Adur=1),
        options={"catchment": ["Lewisham", "Greenwich", "Adur"]},
    )
    assert _names(result.table("priority_areas")) == ["Lewisham"]
    assert "look at first" not in result.answer
    assert result.answer.endswith("of your provision is there.")


# --- reading the volumes ---------------------------------------------------


def test_volumes_for_the_same_place_are_added_up(nomis):
    rows = [
        {"Area": "lewisham", "Sessions": "1,200"},
        {"Area": "E09000023", "Sessions": 300.5},
        {"Area": " Greenwich ", "Sessions": "40"},
    ]
    table = _by_name(_run(rows).table("by_local_authority"))
    assert table["Lewisham"]["volume"] == 1500.5
    assert table["Lewisham"]["volume_per_1000_in_need"] == 166.72
    assert table["Greenwich"]["volume"] == 40


def test_provision_that_cannot_be_placed_says_how_to_name_a_place(nomis):
    with pytest.raises(AnalysisInputError) as raised:
        _run(_volumes(Lewishm=40, Narnia_Borough=25))
    message = str(raised.value)
    assert message.startswith("None of the provision could be placed")
    assert "for example Lewisham, or give its code, for example E09000023" in message
    assert "Lewishm" not in message
    assert "Narnia" not in message


def test_rows_that_cannot_be_placed_are_counted_not_named(nomis):
    rows = [
        *SPREAD,
        {"Area": "Narnia Borough", "Sessions": 25},
        {"Area": "", "Sessions": 5},
    ]
    result = _run(rows)
    assert result.figure("volume_supplied").value == 190
    assert result.figure("volume_located").value == 160
    assert any(w.startswith("1 row had no local authority") for w in result.warnings)
    assert any(w.startswith("1 row named a local authority") for w in result.warnings)
    assert "Narnia" not in json.dumps(result.to_dict())


@pytest.mark.parametrize("volume", ["lots", "", None, -3, "nan", "inf", True])
def test_a_volume_that_is_not_a_number_is_an_input_error(nomis, volume):
    rows = [*SPREAD, {"Area": "Cardiff", "Sessions": volume}]
    with pytest.raises(
        AnalysisInputError,
        match="1 row had provision that is not a number of zero or more: row 5,",
    ):
        _run(rows)


def test_a_bad_volume_is_not_repeated_in_the_error(nomis):
    rows = [*SPREAD, {"Area": "Cardiff", "Sessions": "about forty"}]
    with pytest.raises(AnalysisInputError) as raised:
        _run(rows)
    assert "forty" not in str(raised.value)


def test_no_provision_anywhere_is_an_input_error(nomis):
    with pytest.raises(AnalysisInputError, match="None of the provision"):
        _run(_volumes(Lewisham=0, Narnia=4))


# --- the list of places ----------------------------------------------------


def test_priority_areas_are_high_need_with_the_least_provision(nomis):
    table = _run(SPREAD).table("priority_areas")
    # Nothing in Birmingham or Cardiff, so the larger need comes first.
    assert _names(table) == ["Birmingham", "Cardiff", "Manchester", "Lewisham"]
    assert [row["rank"] for row in table.rows] == [1, 2, 3, 4]
    assert [row["volume_per_1000_in_need"] for row in table.rows] == [0, 0, 1.0, 10.0]
    assert table.rows[2]["people_in_need"] == 20000
    assert table.rows[2]["volume"] == 20


def test_top_sets_the_length_of_the_list(nomis):
    table = _run(SPREAD, options={"top": 2}).table("priority_areas")
    assert _names(table) == ["Birmingham", "Cardiff"]


@pytest.mark.parametrize("top", [0, 51, 2.5, "ten", True])
def test_bad_top_is_rejected(nomis, top):
    with pytest.raises(AnalysisInputError, match="Places listed") as caught:
        _run(SPREAD, options={"top": top})
    assert caught.value.option == "top"


def test_volumes_are_shown_however_small(nomis):
    result = _run(_volumes(Lewisham=1, Greenwich=2, Cardiff=0.5))
    table = _by_name(result.table("by_local_authority"))
    assert table["Lewisham"]["volume"] == 1
    assert table["Cardiff"]["volume"] == 0.5
    assert result.privacy.cells_suppressed == 0
    # No threshold was used, so a page must not say that counts are hidden.
    assert result.privacy.suppress_below is None
    assert result.to_dict()["privacy"]["suppress_below"] is None
    assert all("suppressed" not in row for row in table.values())
    assert any("hides no count" in note for note in result.privacy.notes)
    assert any("one site" in note for note in result.privacy.notes)


# --- the catchment ---------------------------------------------------------


def test_catchment_can_name_local_authorities(nomis):
    result = _run(SPREAD, options={"catchment": ["Lewisham", "Greenwich", "Cardiff"]})
    assert result.figure("areas_compared").value == 3
    assert result.figure("volume_in_catchment").value == 130
    # The top quarter of three places is one place, the one with most need.
    assert _names(result.table("priority_areas")) == ["Cardiff"]
    assert any(w.startswith("Provision of 30 is outside") for w in result.warnings)
    assert any(w.startswith("Only 3 local authorities") for w in result.warnings)
    choice = next(c for c in result.choices if c.id == "catchment")
    assert choice.reason == "You gave the area."


def test_catchment_can_be_a_country(nomis):
    result = _run(SPREAD, options={"catchment": "England"})
    assert result.figure("areas_compared").value == 15
    assert "Cardiff" not in _names(result.table("by_local_authority"))


def test_a_catchment_with_no_provision_is_an_input_error(nomis):
    with pytest.raises(AnalysisInputError, match="None of the provision is in"):
        _run(SPREAD, options={"catchment": "Wales"})


@pytest.mark.parametrize("catchment", [["Lewisham", "Narnia"], 7, [], [""]])
def test_bad_catchment_is_rejected(nomis, catchment):
    with pytest.raises(AnalysisInputError, match="Area you serve") as caught:
        _run(SPREAD, options={"catchment": catchment})
    assert caught.value.option == "catchment"


def test_a_wide_comparison_is_flagged_when_provision_is_in_few_places():
    many = [(f"E060000{n:02d}", f"Place {n}", 1000 + n) for n in range(60)]
    keep_need_figures("residents", many, "invented for a test.")
    flag = (
        "No area was given, so all 60 local authorities in England and Wales "
        "are looked at, and you provide in 2 of them."
    )
    wide = _run(_volumes(Place_1=10, Place_2=20))
    named = _run(
        _volumes(Place_1=10, Place_2=20),
        options={"catchment": [f"Place {n}" for n in range(1, 6)]},
    )
    assert any(w.startswith(flag) for w in wide.warnings)
    assert not any(w.startswith("No area was given") for w in named.warnings)


# --- sites -----------------------------------------------------------------

# Real postcodes never end in C, I, K, M, O or V, so none of these can exist.
PLACES = {
    "SE13 7VC": "E09000023",
    "SE13 6CM": "E09000023",
    "SE10 9OK": "E09000011",
    "CF10 1VC": "W06000015",
    "EH1 1VC": "S12000036",
}
SITES = [
    {"Site postcode": "SE13 7VC", "Places": 1200},
    {"Site postcode": "se136cm", "Places": 300},
    {"Site postcode": "SE10 9OK", "Places": 4321},
    {"Site postcode": "CF10 1VC", "Places": 80},
    {"Site postcode": "EH1 1VC", "Places": 50},
    {"Site postcode": "SE13 7VO", "Places": 7},
    {"Site postcode": "not a postcode", "Places": 2},
    {"Site postcode": "", "Places": 1},
]
SITE_COLUMNS = {"postcode": "Site postcode", "volume": "Places"}


def _fake_lookup(sent: list):
    def lookup(postcodes: list[str], level: str) -> pd.DataFrame:
        sent.append((level, list(postcodes)))
        return pd.DataFrame(
            {
                "postcode": postcodes,
                "geography_code": [PLACES.get(postcode) for postcode in postcodes],
                "geography_name": [None] * len(postcodes),
            }
        )

    return lookup


def _run_sites(rows=SITES, columns=SITE_COLUMNS, options=None, sent=None):
    with mock.patch(
        "uk_open_data.analyses._steps.postcodes_to_geography",
        side_effect=_fake_lookup([] if sent is None else sent),
    ):
        return _run(rows, options=options, columns=columns)


def test_sites_are_placed_in_local_authorities_online(nomis):
    sent: list = []
    result = _run_sites(sent=sent)
    assert result.input_mode == "sites"
    level, postcodes = sent[0]
    assert level == "LAD"
    assert postcodes == sorted(set(postcodes))
    assert result.figure("volume_supplied").value == 5961
    assert result.figure("volume_located").value == 5901
    table = _by_name(result.table("by_local_authority"))
    assert table["Lewisham"]["volume"] == 1500
    assert table["Greenwich"]["volume"] == 4321
    assert table["Cardiff"]["volume"] == 80
    assert any(w.startswith("Provision of 10 is at sites") for w in result.warnings)
    assert any(
        w.startswith("Provision of 50 was placed outside") for w in result.warnings
    )
    assert "local authorities" in result.privacy.sent_to_third_parties[0]
    source = next(s for s in result.sources if s.id == "postcodes-io")
    assert source.used_for == "Finding the local authority each postcode is in."
    assert result.checks[0].id == "volume_is_provision"


def test_sites_stay_on_this_machine_when_a_table_is_installed(nomis, tmp_path):
    header = "pcd7,lsoa21cd,ladcd"
    lines = [
        f"{postcode.replace(' ', '').ljust(7)[:4].strip().ljust(4)}"
        f"{postcode[-3:]},E0100000{n},{lad}"
        for n, (postcode, lad) in enumerate(PLACES.items())
    ]
    source = tmp_path / "lookup.csv"
    source.write_text("\n".join([header, *lines]) + "\n", encoding="utf-8")
    packed = tmp_path / "postcodes.ktpc.gz"
    build_postcode_table(source, packed, "May 2026")
    install_postcode_table(packed)
    with mock.patch("uk_open_data.analyses._steps.postcodes_to_geography") as online:
        result = _run(SITES, columns=SITE_COLUMNS)
    online.assert_not_called()
    assert result.privacy.sent_to_third_parties == ()
    assert result.figure("volume_located").value == 5901


def test_a_list_of_sites_counts_each_site_as_one(nomis):
    rows = [{"Site postcode": row["Site postcode"]} for row in SITES]
    result = _run_sites(rows, columns={"postcode": "Site postcode"})
    assert result.input_mode == "site_list"
    assert result.figure("volume_supplied").value == 8
    assert result.figure("volume_located").value == 4
    table = _by_name(result.table("by_local_authority"))
    assert table["Lewisham"]["volume"] == 2
    assert table["Lewisham"]["volume_per_1000_in_need"] == 0.22
    assert result.checks[0].id == "sites_alike"


def test_no_postcode_reaches_the_result(nomis):
    result = _run_sites()
    payload = result.to_dict()
    assert find_row_values(payload, [row["Site postcode"] for row in SITES]) == []
    text = json.dumps(payload).upper().replace(" ", "")
    for row in SITES:
        compact = row["Site postcode"].upper().replace(" ", "")
        assert not compact or compact not in text


# --- the map ---------------------------------------------------------------


def test_map_is_described_by_local_authority(nomis):
    result = _run(SPREAD)
    spec = result.map
    assert (spec.geography_type, spec.geography_year) == ("LAD", 2023)
    assert spec.table == "by_local_authority"
    assert [layer.id for layer in spec.layers] == ["need", "provision"]
    assert spec.layers[0].categories == NEED_BANDS
    assert spec.layers[1].categories == PROVISION_BANDS
    table = result.table(spec.table)
    assert table.detail is True
    rows = _by_name(table)
    assert rows["Birmingham"]["need_band"] == "Highest fifth"
    assert rows["Isles of Scilly"]["need_band"] == "Lowest fifth"
    assert rows["Birmingham"]["high_need"] is True
    assert rows["Greenwich"]["high_need"] is False
    for name in ("Birmingham", "Cardiff", "Hartlepool", "Isles of Scilly"):
        assert rows[name]["provision_band"] == NO_PROVISION
    # For each 1,000 people: Manchester 1, Greenwich 5, Adur 10, Lewisham 10.
    assert rows["Manchester"]["provision_band"] == "Lower provision"
    assert rows["Greenwich"]["provision_band"] == "Lower provision"
    assert rows["Adur"]["provision_band"] == "Middle provision"
    assert rows["Lewisham"]["provision_band"] == "Higher provision"
    # A place for every group on both layers: nothing is said of few places.
    assert not [layer.note for layer in spec.layers if "fewer places" in layer.note]


def test_map_says_so_when_few_places_have_provision(nomis):
    two = _run(_volumes(Lewisham=90, Greenwich=40)).map
    assert "fewer places" not in two.layers[0].note
    assert two.layers[1].note.endswith(FEW_PLACES)
    one = _run(_volumes(Lewisham=90)).map
    assert one.layers[1].note.endswith(ONE_PLACE)


def _square(number: int, code: str) -> dict:
    """An invented square boundary for one local authority."""
    west = -3.0 + 0.5 * (number % 4)
    south = 51.0 + 0.5 * (number // 4)
    ring = [
        [west, south],
        [west + 0.5, south],
        [west + 0.5, south + 0.5],
        [west, south + 0.5],
        [west, south],
    ]
    return {
        "type": "Feature",
        "properties": {"LAD23CD": code},
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def test_map_can_be_drawn(nomis):
    result = _run(SPREAD)
    boundaries = {
        "type": "FeatureCollection",
        "features": [_square(n, code) for n, (code, _, _) in enumerate(NEED)],
    }
    for layer in ("need", "provision"):
        svg = render_map(result, layer=layer, boundaries=boundaries)
        root = ET.fromstring(svg)
        titles = [
            title.text for title in root.iter("{http://www.w3.org/2000/svg}title")
        ]
        assert any(text.startswith("Lewisham: ") for text in titles[1:])


# --- the whole result ------------------------------------------------------


def test_charts_use_columns_of_the_list(nomis):
    result = _run(SPREAD)
    assert [chart.id for chart in result.charts] == [
        "need_in_priority_areas",
        "provision_in_priority_areas",
    ]
    columns = set(result.table("priority_areas").columns)
    for chart in result.charts:
        assert chart.table == "priority_areas"
        assert chart.category_column in columns
        assert {series.column for series in chart.series} <= columns


def test_result_explains_itself(nomis):
    result = _run(SPREAD)
    options = check_working(result)
    assert options["need"] == "residents"
    rate = result.figure("volume_per_1000_in_need")
    assert round(rate.exact, 2) == rate.value
    # Every column has a plain heading to show in place of its id.
    assert not [
        column
        for table in result.tables
        for column in table.columns
        if table.headings[column] == column
    ]
    assert result.analysis_id == ANALYSIS_ID
    assert [step.title for step in result.working] == [
        "Loaded the need figures",
        "Read the provision by local authority",
        "Joined provision to the need figures",
        "Set the area you serve",
        "Set provision against residents",
        "Listed the places with the most residents and thin provision",
    ]
    assert [check.id for check in result.checks] == [
        "volume_is_provision",
        "everything_listed",
        "period",
        "need_fits",
        "catchment",
    ]
    assert [choice.id for choice in result.choices] == [
        "need",
        "high_need",
        "catchment",
        "top",
    ]
    option_names = {option.name for option in describe_analysis(ANALYSIS_ID).options}
    for choice in result.choices:
        assert choice.option is None or choice.option in option_names
    assert any("not the same as unmet need" in caveat for caveat in result.caveats)
    summary = result.to_dict(include_detail=False)
    json.dumps(summary)
    detail = next(t for t in summary["tables"] if t["id"] == "by_local_authority")
    assert detail["rows"] == []


def test_command_line_runs_the_analysis(nomis, tmp_path, capsys):
    path = tmp_path / "volumes.csv"
    path.write_text("Area,Sessions\nLewisham,90\nGreenwich,40\n", encoding="utf-8")
    code = main(
        [
            "analysis",
            "run",
            ANALYSIS_ID,
            str(path),
            "--column",
            "local_authority=Area",
            "--column",
            "volume=Sessions",
            "--option",
            'catchment=["Lewisham", "Greenwich", "Adur"]',
            "--json",
        ]
    )
    assert code == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["analysis_id"] == ANALYSIS_ID
    assert nomis.asked[0][0] == "NM_2028_1"


def test_command_line_report_does_not_say_counts_are_hidden(nomis, tmp_path, capsys):
    path = tmp_path / "volumes.csv"
    path.write_text("Area,Sessions\nLewisham,90\nGreenwich,40\n", encoding="utf-8")
    columns = ["--column", "local_authority=Area", "--column", "volume=Sessions"]
    assert main(["analysis", "run", ANALYSIS_ID, str(path), *columns]) == EXIT_OK
    report = capsys.readouterr().out
    assert "are hidden" not in report
    assert "hides no count" in report
