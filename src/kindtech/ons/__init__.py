"""ONS data loading and processing package."""

from .api import load_ons
from ._ingestion import list_tables

__all__ = ["load_ons", "list_tables"]
