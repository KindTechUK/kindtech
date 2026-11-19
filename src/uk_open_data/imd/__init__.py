"""
KindTech IMD Package

Loads the composite UK Index of Multiple Deprivation — the four nations'
official deprivation indices harmonised onto one UK-wide ranking — keyed on ONS
geography codes so it joins to KindTech boundaries and statistics.
"""

from .api import download_imd, imd_path, keep_imd, kept_imd_note, load_imd

__all__ = [
    "download_imd",
    "imd_path",
    "keep_imd",
    "kept_imd_note",
    "load_imd",
]
