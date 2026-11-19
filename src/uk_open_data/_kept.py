"""Public figures kept on this machine, so they do not have to be fetched.

A kept file is JSON with a ``format`` that names what it holds and a ``note``
that says where the figures came from. Files live in the data folder, beside
the postcode table.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from uk_open_data.postcodes.offline import data_dir


def kept_file(folder: str, name: str) -> Path:
    """Return where a kept file goes, whether or not it is there."""
    return data_dir() / folder / f"{name}.json"


def write_kept(
    folder: str,
    name: str,
    file_format: str,
    note: str,
    content: dict[str, Any],
    *,
    compact: bool = False,
) -> Path:
    """Write a kept file and return its path.

    A small file is laid out for a person to read. Pass ``compact`` for a
    large table, which is written on one line to keep the file small.
    """
    path = kept_file(folder, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    kept = {"format": file_format, "note": note, **content}
    text = json.dumps(kept, indent=None if compact else 1)
    path.write_text(text + "\n", encoding="utf-8")
    return path


def read_kept(folder: str, name: str, file_format: str) -> dict[str, Any] | None:
    """Read a kept file.

    Returns:
        What the file holds, or None when there is no such file.

    Raises:
        ValueError: If the file is not JSON, or holds something else.
    """
    path = kept_file(folder, name)
    if not path.is_file():
        return None
    kept = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(kept, dict) or kept.get("format") != file_format:
        msg = f"{path.name} is not a {file_format} file."
        raise ValueError(msg)
    if not isinstance(kept.get("note"), str):
        msg = f"{path.name} has no note."
        raise ValueError(msg)
    return kept
