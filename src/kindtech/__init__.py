"""The old name of the ``uk_open_data`` package.

The package was called ``kindtech`` up to version 0.1. Importing it by the old
name still works: ``kindtech`` and every module under it is the very same
module object as its ``uk_open_data`` counterpart, so nothing is loaded twice
and anything kept in a module, such as a cache, is shared.

New code should import ``uk_open_data``.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import sys
import warnings
from types import CodeType, ModuleType

OLD_NAME = "kindtech"
NEW_NAME = "uk_open_data"


def _new_name(old: str) -> str:
    """Turn ``kindtech.geo`` into ``uk_open_data.geo``."""
    return NEW_NAME + old[len(OLD_NAME) :]


class _OldNameFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Answer an import of ``kindtech.x`` with the module ``uk_open_data.x``."""

    def __init__(self) -> None:
        self._real_specs: dict[str, importlib.machinery.ModuleSpec] = {}

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: ModuleType | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        """Describe ``kindtech.x`` as its ``uk_open_data`` counterpart."""
        if not fullname.startswith(OLD_NAME + "."):
            return None
        real = importlib.util.find_spec(_new_name(fullname))
        if real is None:
            return None
        self._real_specs[fullname] = real
        spec = importlib.machinery.ModuleSpec(
            fullname,
            self,
            origin=real.origin,
            is_package=real.submodule_search_locations is not None,
        )
        if real.submodule_search_locations is not None:
            spec.submodule_search_locations = list(real.submodule_search_locations)
        return spec

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType:
        """Return the real module, importing it if it is not loaded yet."""
        return importlib.import_module(_new_name(spec.name))

    def exec_module(self, module: ModuleType) -> None:
        """Leave the real module as it is, under its own name."""
        # The import system has just described the module by its old name.
        module.__spec__ = self._real_specs.get(
            OLD_NAME + module.__name__[len(NEW_NAME) :], module.__spec__
        )

    def get_code(self, fullname: str) -> CodeType | None:
        """Return the code of the real module, so ``python -m`` can run it."""
        real = self._real_specs.get(fullname) or importlib.util.find_spec(
            _new_name(fullname)
        )
        loader = getattr(real, "loader", None)
        get_code = getattr(loader, "get_code", None)
        return get_code(_new_name(fullname)) if get_code else None


warnings.warn(
    "The 'kindtech' package is now 'uk_open_data'. Importing 'kindtech' still "
    "works, and will stop in a later release. Install 'uk-open-data' and "
    "import 'uk_open_data'.",
    DeprecationWarning,
    stacklevel=2,
)
sys.meta_path.insert(0, _OldNameFinder())
sys.modules[OLD_NAME] = importlib.import_module(NEW_NAME)
