"""Lenses: questions a charity can ask of its own data.

A lens takes a charity's data, joins it to UK open data, and returns figures
with their sources, a map description, the working, the choices it made and
the checks a person should do. Results hold totals only, never rows.

    >>> from kindtech.lenses import list_lenses, run_lens
    >>> [lens.id for lens in list_lenses()]
    ['reach-deprivation', 'need-reach']
    >>> result = run_lens(
    ...     "reach-deprivation",
    ...     clients,
    ...     columns={"postcode": "Client postcode"},
    ... )  # doctest: +SKIP
    >>> result.figure("share_most_deprived_20").value  # doctest: +SKIP
    41.3
"""

from kindtech.lenses import need_reach as _need_reach
from kindtech.lenses import reach_deprivation as _reach_deprivation
from kindtech.lenses._model import (
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
    Privacy,
    Role,
    Source,
    Step,
    Table,
)
from kindtech.lenses._registry import (
    describe_lens,
    list_lenses,
    register_lens,
    run_lens,
)
from kindtech.lenses.maps import load_map_boundaries, render_map

# Lenses are listed in this order.
for _lens in (_reach_deprivation.LENS, _need_reach.LENS):
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
