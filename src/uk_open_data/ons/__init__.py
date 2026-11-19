"""
KindTech ONS Package

Provides access to UK Office for National Statistics data via the NOMIS API.
"""

from .api import list_tables, load_ons

__all__ = [
    "list_tables",
    "load_ons",
]
