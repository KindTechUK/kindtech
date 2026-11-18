"""Lenses: questions a charity can ask of its own data.

A lens takes a charity's data, joins it to UK open data, and returns figures
with their sources, a map description, the working, the choices it made and
the checks a person should do. Results hold totals only, never rows.

    >>> from kindtech.lenses import list_lenses, run_lens
    >>> [lens.id for lens in list_lenses()]
    ['reach-deprivation']
    >>> result = run_lens(
    ...     "reach-deprivation",
    ...     clients,
    ...     columns={"postcode": "Client postcode"},
    ... )  # doctest: +SKIP
    >>> result.figure("share_most_deprived_20").value  # doctest: +SKIP
    41.3
"""

from kindtech.lenses import reach_deprivation as _reach_deprivation  # noqa: F401
from kindtech.lenses._model import (
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

__all__ = [
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
