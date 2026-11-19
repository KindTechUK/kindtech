"""Lenses: questions a charity can ask of its own data.

A lens takes a charity's data, joins it to UK open data, and returns figures
with their sources, a map description, the working, the choices it made and
the checks a person should do. Results hold totals only, never rows.

    >>> from uk_open_data.lenses import list_lenses, run_lens
    >>> [lens.id for lens in list_lenses()]
    ['reach-deprivation', 'need-reach', 'who-we-miss', 'provision-gap',
     'access-distance']
    >>> result = run_lens(
    ...     "reach-deprivation",
    ...     clients,
    ...     columns={"postcode": "Client postcode"},
    ... )  # doctest: +SKIP
    >>> result.figure("share_most_deprived_20").value  # doctest: +SKIP
    41.3
"""

from uk_open_data.lenses import access_distance as _access_distance
from uk_open_data.lenses import need_reach as _need_reach
from uk_open_data.lenses import provision_gap as _provision_gap
from uk_open_data.lenses import reach_deprivation as _reach_deprivation
from uk_open_data.lenses import who_we_miss as _who_we_miss
from uk_open_data.lenses._model import (
    Chart,
    ChartSeries,
    Check,
    Choice,
    Figure,
    InputMode,
    Lens,
    LensInfo,
    LensInput,
    LensInputError,
    LensResult,
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
from uk_open_data.lenses._registry import (
    describe_lens,
    list_lenses,
    register_lens,
    run_lens,
)
from uk_open_data.lenses.maps import load_map_boundaries, render_map

# Lenses are listed in this order.
for _lens in (
    _reach_deprivation.LENS,
    _need_reach.LENS,
    _who_we_miss.LENS,
    _provision_gap.LENS,
    _access_distance.LENS,
):
    register_lens(_lens)

__all__ = [
    "Chart",
    "ChartSeries",
    "Check",
    "Choice",
    "Figure",
    "InputMode",
    "Lens",
    "LensInfo",
    "LensInput",
    "LensInputError",
    "LensResult",
    "MapLayer",
    "MapSpec",
    "Option",
    "OptionChoice",
    "Privacy",
    "Role",
    "Source",
    "Step",
    "Table",
    "describe_lens",
    "list_lenses",
    "load_map_boundaries",
    "register_lens",
    "render_map",
    "run_lens",
]
