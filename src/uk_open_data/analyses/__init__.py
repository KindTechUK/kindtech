"""Analyses: questions a charity can ask of its own data.

An analysis takes a charity's data, joins it to UK open data, and returns figures
with their sources, a map description, the working, the choices it made and
the checks a person should do. Results hold totals only, never rows.

    >>> from uk_open_data.analyses import list_analyses, run_analysis
    >>> [analysis.id for analysis in list_analyses()]
    ['reach-deprivation', 'need-reach', 'who-we-miss', 'provision-gap',
     'access-distance']
    >>> result = run_analysis(
    ...     "reach-deprivation",
    ...     clients,
    ...     columns={"postcode": "Client postcode"},
    ... )  # doctest: +SKIP
    >>> result.figure("share_most_deprived_20").value  # doctest: +SKIP
    41.3
"""

from uk_open_data.analyses import access_distance as _access_distance
from uk_open_data.analyses import need_reach as _need_reach
from uk_open_data.analyses import provision_gap as _provision_gap
from uk_open_data.analyses import reach_deprivation as _reach_deprivation
from uk_open_data.analyses import who_we_miss as _who_we_miss
from uk_open_data.analyses._model import (
    Analysis,
    AnalysisInfo,
    AnalysisInput,
    AnalysisInputError,
    AnalysisResult,
    Chart,
    ChartSeries,
    Check,
    Choice,
    Figure,
    InputMode,
    MapLayer,
    MapSpec,
    Option,
    OptionChoice,
    Privacy,
    Role,
    Source,
    Step,
    Table,
)
from uk_open_data.analyses._registry import (
    DOORS,
    RUNS_LOGGER,
    describe_analysis,
    list_analyses,
    record_run,
    register_analysis,
    run_analysis,
)
from uk_open_data.analyses.maps import load_map_boundaries, render_map

# Analyses are listed in this order.
for _analysis in (
    _reach_deprivation.ANALYSIS,
    _need_reach.ANALYSIS,
    _who_we_miss.ANALYSIS,
    _provision_gap.ANALYSIS,
    _access_distance.ANALYSIS,
):
    register_analysis(_analysis)

__all__ = [
    "DOORS",
    "RUNS_LOGGER",
    "Chart",
    "ChartSeries",
    "Check",
    "Choice",
    "Figure",
    "InputMode",
    "Analysis",
    "AnalysisInfo",
    "AnalysisInput",
    "AnalysisInputError",
    "AnalysisResult",
    "MapLayer",
    "MapSpec",
    "Option",
    "OptionChoice",
    "Privacy",
    "Role",
    "Source",
    "Step",
    "Table",
    "describe_analysis",
    "list_analyses",
    "load_map_boundaries",
    "record_run",
    "register_analysis",
    "render_map",
    "run_analysis",
]
