"""ONS data loading and processing package."""

from ._ingestion import list_tables
from .api import load_ons

__all__ = ["load_ons", "list_tables"]
