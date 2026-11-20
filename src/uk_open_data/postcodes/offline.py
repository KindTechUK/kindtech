"""Looking up postcodes on this machine, without sending them anywhere.

A postcode table is one file that maps every postcode in England and Wales to
its 2021 Lower layer Super Output Area and local authority. It is built from
the ONS best-fit postcode lookup and downloaded once; after that, lookups read
the file and nothing leaves the machine.

    >>> from uk_open_data.postcodes import download_postcode_table, postcode_to_lsoa
    >>> download_postcode_table()  # doctest: +SKIP
    >>> postcode_to_lsoa("SE13 7VC")  # doctest: +SKIP

Scotland and Northern Ireland are left out. Northern Ireland postcodes carry a
separate licence for commercial use, and neither nation has 2021 LSOAs.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import logging
import mmap
import os
import re
import struct
import zipfile
from collections.abc import Iterable, Iterator
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

DATA_DIR_VARIABLE = "UK_OPEN_DATA_DIR"
# The names used before the package was renamed. Both still work.
OLD_DATA_DIR_VARIABLE = "KINDTECH_DATA_DIR"
DATA_FOLDER = "uk-open-data"
OLD_DATA_FOLDER = "kindtech"
TABLE_FILE_NAME = "postcodes.ktpc"

# The table published for this version of the package, as a dict with "url",
# "sha256" (of the downloaded .gz file) and "edition". None until one is
# published; download_postcode_table() then needs a url and sha256 passing in.
PUBLISHED_TABLE: dict[str, str] | None = None

# The statements the ONS licence asks every user of its postcode data to show.
ATTRIBUTION = (
    "Source: Office for National Statistics licensed under the Open Government "
    "Licence v.3.0",
    "Contains OS data © Crown copyright and database right {year}",
    "Contains Royal Mail data © Royal Mail copyright and database right {year}",
)
SOURCE_NAME = "Postcode to OA (2021) to LSOA to MSOA to LAD Best Fit Lookup in the UK"
SOURCE_URL = "https://geoportal.statistics.gov.uk"

_MAGIC = b"KTPC1\n"
_HEADER_LENGTH = struct.Struct(">I")
_KEY_BYTES = 7
_RECORD = struct.Struct(">7sH")
_MAX_AREAS = 2**16
_NATIONS_KEPT = ("E01", "W01")
_SOURCE_FIELDS = ("pcd7", "lsoa21cd", "ladcd")
_SHAPE = re.compile(r"^([A-Z]{1,2}[0-9][A-Z0-9]?)([0-9][A-Z]{2})$")
_DISTRICT = re.compile(r"^[A-Z]{1,2}[0-9][A-Z0-9]?$")
_DOWNLOAD_TIMEOUT = 120


class PostcodeTableError(RuntimeError):
    """The postcode table is missing, damaged or could not be fetched."""


# --- where the table lives --------------------------------------------------


def data_dir() -> Path:
    """Return the folder that holds downloaded data.

    Set the ``UK_OPEN_DATA_DIR`` environment variable to choose it. Otherwise
    it is ``$XDG_CACHE_HOME/uk-open-data``, or ``~/.cache/uk-open-data``.

    The names from before the package was renamed still work: the
    ``KINDTECH_DATA_DIR`` variable is read when the new one is not set, and a
    ``kindtech`` folder is used when it exists and the new folder does not.
    """
    chosen = os.environ.get(DATA_DIR_VARIABLE) or os.environ.get(OLD_DATA_DIR_VARIABLE)
    if chosen:
        return Path(chosen)
    cache = os.environ.get("XDG_CACHE_HOME")
    base = Path(cache) if cache else Path.home() / ".cache"
    new, old = base / DATA_FOLDER, base / OLD_DATA_FOLDER
    return old if old.is_dir() and not new.is_dir() else new


def postcode_table_path() -> Path | None:
    """Return the path of the installed postcode table, or None."""
    path = data_dir() / TABLE_FILE_NAME
    return path if path.is_file() else None


# --- looking up -------------------------------------------------------------


def postcode_to_lsoa(postcode: str) -> str | None:
    """Return the 2021 LSOA code for one postcode, read from this machine.

    Args:
        postcode: A postcode in any spacing or case.

    Returns:
        The LSOA code, or None when the postcode is not shaped like a postcode
        or is not in the table (for example a Scottish postcode).

    Raises:
        PostcodeTableError: If no postcode table is installed.
    """
    return postcodes_to_lsoa([postcode])[0]


def postcodes_to_lsoa(postcodes: Iterable[str]) -> list[str | None]:
    """Return the 2021 LSOA code for each postcode, in the order given.

    Raises:
        PostcodeTableError: If no postcode table is installed.
    """
    table = _open_table()
    return [table.lsoa(postcode) for postcode in postcodes]


def postcodes_to_local_authority(postcodes: Iterable[str]) -> list[str | None]:
    """Return the local authority code for each postcode, in the order given.

    A postcode that is not in the table (for example a Scottish postcode) gives
    None.

    Raises:
        PostcodeTableError: If no postcode table is installed.
    """
    table = _open_table()
    return [table.local_authority(postcode) for postcode in postcodes]


def district_to_local_authorities(district: str) -> list[str]:
    """Return the local authority codes a postcode district reaches into.

    Args:
        district: The first half of a postcode, such as ``SE13``.

    Returns:
        Local authority district codes, sorted. Empty when the district is not
        in the table.

    Raises:
        PostcodeTableError: If no postcode table is installed.
    """
    return _open_table().local_authorities(district)


def postcode_table_info() -> dict[str, Any]:
    """Describe the installed table: edition, source, credits and size.

    Raises:
        PostcodeTableError: If no postcode table is installed.
    """
    table = _open_table()
    return {key: value for key, value in table.header.items() if key != "areas"}


class _Table:
    """A postcode table opened for reading."""

    def __init__(self, path: Path) -> None:
        self._file = path.open("rb")
        self._data = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        if self._data[: len(_MAGIC)] != _MAGIC:
            msg = f"{path} is not a postcode table."
            raise PostcodeTableError(msg)
        start = len(_MAGIC)
        (length,) = _HEADER_LENGTH.unpack_from(self._data, start)
        start += _HEADER_LENGTH.size
        self.header: dict[str, Any] = json.loads(self._data[start : start + length])
        self._body = start + length
        self._count = (len(self._data) - self._body) // _RECORD.size
        self._areas: list[list[str]] = self.header["areas"]

    def _key_at(self, index: int) -> bytes:
        """Return the postcode held in a record."""
        offset = self._body + index * _RECORD.size
        return self._data[offset : offset + _KEY_BYTES]

    def _area_at(self, index: int) -> list[str]:
        """Return the [LSOA code, local authority code] of a record."""
        offset = self._body + index * _RECORD.size
        _, area = _RECORD.unpack_from(self._data, offset)
        return self._areas[area]

    def _first_at_or_after(self, key: bytes) -> int:
        """Find the first record whose postcode is not before ``key``."""
        low, high = 0, self._count
        while low < high:
            middle = (low + high) // 2
            if self._key_at(middle) < key:
                low = middle + 1
            else:
                high = middle
        return low

    def _area(self, postcode: str) -> list[str] | None:
        """Return the [LSOA code, local authority code] of a postcode, or None."""
        key = _key(postcode)
        if key is None:
            return None
        index = self._first_at_or_after(key)
        if index < self._count and self._key_at(index) == key:
            return self._area_at(index)
        return None

    def lsoa(self, postcode: str) -> str | None:
        """Return the LSOA code for a postcode, or None."""
        area = self._area(postcode)
        return area[0] if area else None

    def local_authority(self, postcode: str) -> str | None:
        """Return the local authority code for a postcode, or None."""
        area = self._area(postcode)
        return area[1] if area else None

    def local_authorities(self, district: str) -> list[str]:
        """Return the local authority codes of every postcode in a district."""
        compact = re.sub(r"\s+", "", str(district)).upper()
        if not _DISTRICT.match(compact):
            return []
        prefix = compact.ljust(4).encode("ascii")
        index = self._first_at_or_after(prefix + b"\x00" * 3)
        found: set[str] = set()
        while index < self._count and self._key_at(index).startswith(prefix):
            found.add(self._area_at(index)[1])
            index += 1
        return sorted(found)


def _key(postcode: Any) -> bytes | None:
    """Return a postcode as the seven characters the table is sorted by."""
    compact = re.sub(r"\s+", "", str(postcode)).upper()
    match = _SHAPE.match(compact)
    if not match:
        return None
    return (match.group(1).ljust(4) + match.group(2)).encode("ascii")


def _open_table() -> _Table:
    """Open the installed table, or say how to get one."""
    path = postcode_table_path()
    if path is None:
        raise PostcodeTableError(missing_table_message())
    return _cached_table(str(path), path.stat().st_mtime_ns)


NO_TABLE = "No postcode table is installed on this machine."


def how_to_get_a_table() -> str:
    """Say how to get a postcode table for this version."""
    if PUBLISHED_TABLE is None:
        return (
            "None has been published for this version yet. To make one, build "
            "it from the ONS lookup with `uk-open-data postcodes build` and "
            "install it with uk_open_data.postcodes.install_postcode_table()."
        )
    return (
        "Fetch one with `uk-open-data postcodes download`, or call "
        "uk_open_data.postcodes.download_postcode_table()."
    )


def missing_table_message() -> str:
    """Say that no table is installed, and how to get one for this version."""
    return f"{NO_TABLE} {how_to_get_a_table()}"


@lru_cache(maxsize=2)
def _cached_table(path: str, modified: int) -> _Table:
    """Open a table once per file version."""
    logger.info("Opening postcode table %s (modified %d)", path, modified)
    return _Table(Path(path))


# --- fetching ---------------------------------------------------------------


def download_postcode_table(
    url: str | None = None, sha256: str | None = None, force: bool = False
) -> Path:
    """Fetch the postcode table and install it in the data folder.

    The file is public and the same for everyone, so fetching it says nothing
    about your data. It is checked against a SHA-256 before it is installed.

    Args:
        url: Where to fetch the gzipped table from. Left out, the table
            published for this version of the package is used.
        sha256: The SHA-256 of the gzipped file, as hex. Needed with ``url``.
        force: Fetch again even when a table is already installed.

    Returns:
        The path of the installed table.

    Raises:
        PostcodeTableError: If no table is published and no ``url`` is given,
            the download fails, or the file does not match its SHA-256.
    """
    installed = postcode_table_path()
    if installed is not None and not force:
        return installed
    url, sha256 = _resolve_download(url, sha256)
    logger.info("GET %s", url)
    try:
        response = requests.get(url, timeout=_DOWNLOAD_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        msg = f"The postcode table could not be fetched from {url}."
        raise PostcodeTableError(msg) from exc
    packed = response.content
    if hashlib.sha256(packed).hexdigest() != sha256.lower():
        msg = (
            "The downloaded postcode table does not match its SHA-256, so it "
            "was not installed."
        )
        raise PostcodeTableError(msg)
    return install_postcode_table(io.BytesIO(packed))


def _resolve_download(url: str | None, sha256: str | None) -> tuple[str, str]:
    """Work out what to fetch and the SHA-256 it must have."""
    if url is None and PUBLISHED_TABLE is not None:
        return PUBLISHED_TABLE["url"], PUBLISHED_TABLE["sha256"]
    if url is None:
        msg = (
            "No postcode table has been published for this version yet. Build "
            "one from the ONS lookup with `uk-open-data postcodes build`, or "
            "give a url and sha256."
        )
        raise PostcodeTableError(msg)
    if not url.startswith("https://"):
        raise PostcodeTableError("The postcode table must be fetched over https.")
    if not sha256:
        raise PostcodeTableError("A sha256 is needed with a url.")
    return url, sha256


def install_postcode_table(packed: Path | io.BufferedIOBase) -> Path:
    """Install a gzipped table file into the data folder.

    Args:
        packed: The path of a ``.gz`` table, or an open binary file of one.

    Returns:
        The path of the installed table.

    Raises:
        PostcodeTableError: If the file is not a postcode table.
    """
    try:
        with gzip.open(packed, "rb") as handle:
            content = handle.read()
    except (OSError, EOFError) as exc:
        raise PostcodeTableError("The file is not a gzipped postcode table.") from exc
    if not content.startswith(_MAGIC):
        raise PostcodeTableError("The file is not a postcode table.")
    folder = data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / TABLE_FILE_NAME
    partial = target.with_suffix(".partial")
    partial.write_bytes(content)
    partial.replace(target)
    return target


# --- building ---------------------------------------------------------------


def build_postcode_table(source: Path, output: Path, edition: str) -> dict[str, Any]:
    """Build a gzipped postcode table from the ONS best-fit postcode lookup.

    Args:
        source: The ONS lookup as a ``.csv`` file, or the ``.zip`` it comes in.
            It must have the columns ``pcd7``, ``lsoa21cd`` and ``ladcd``.
        output: Where to write the gzipped table.
        edition: The edition of the lookup, such as ``"May 2026"``.

    Returns:
        A summary: ``edition``, ``records``, ``areas``, ``bytes`` and the
        ``sha256`` of the file written.

    Raises:
        PostcodeTableError: If the source lacks a column or holds no postcodes
            in England or Wales.
    """
    areas: dict[tuple[str, str], int] = {}
    records: list[tuple[bytes, int]] = []
    for row in _source_rows(source):
        lsoa = row["lsoa21cd"].strip()
        if not lsoa.startswith(_NATIONS_KEPT):
            continue
        key = _key(row["pcd7"])
        if key is None:
            continue
        area = areas.setdefault((lsoa, row["ladcd"].strip()), len(areas))
        records.append((key, area))
    if not records:
        msg = "The source holds no postcodes in England or Wales."
        raise PostcodeTableError(msg)
    if len(areas) > _MAX_AREAS:
        msg = (
            f"The source has more than {_MAX_AREAS} areas, which the table cannot hold."
        )
        raise PostcodeTableError(msg)
    records.sort()
    year = date.today().year
    header = {
        "edition": edition,
        "source": SOURCE_NAME,
        "source_url": SOURCE_URL,
        "publisher": "Office for National Statistics",
        "licence": "Open Government Licence v3.0",
        "attribution": [line.format(year=year) for line in ATTRIBUTION],
        "coverage": "England and Wales",
        "built": date.today().isoformat(),
        "records": len(records),
        "areas": [list(area) for area in areas],
    }
    encoded = json.dumps(header, ensure_ascii=False).encode("utf-8")
    body = b"".join(_RECORD.pack(key, area) for key, area in records)
    content = _MAGIC + _HEADER_LENGTH.pack(len(encoded)) + encoded + body
    # mtime=0 keeps the file identical each time it is built from one source.
    packed = gzip.compress(content, mtime=0)
    output.write_bytes(packed)
    return {
        "edition": edition,
        "records": len(records),
        "areas": len(areas),
        "bytes": len(packed),
        "sha256": hashlib.sha256(packed).hexdigest(),
    }


def _source_rows(source: Path) -> Iterator[dict[str, str]]:
    """Yield the rows of the ONS lookup with lower-case column names."""
    with _open_source(source) as handle:
        reader = csv.reader(handle)
        names = [name.strip().lower() for name in next(reader, [])]
        missing = [name for name in _SOURCE_FIELDS if name not in names]
        if missing:
            msg = (
                f"The source has no column called {', '.join(missing)}. It "
                "should be the ONS postcode to OA (2021) to LSOA to MSOA to LAD "
                "best-fit lookup."
            )
            raise PostcodeTableError(msg)
        positions = {name: names.index(name) for name in _SOURCE_FIELDS}
        for row in reader:
            if len(row) == len(names):
                yield {name: row[position] for name, position in positions.items()}


def _open_source(source: Path) -> io.TextIOWrapper:
    """Open the lookup as text, from a CSV file or from the zip it comes in."""
    if source.suffix.lower() != ".zip":
        return source.open(newline="", encoding="utf-8-sig", errors="replace")
    archive = zipfile.ZipFile(source)
    members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
    if len(members) != 1:
        msg = "The zip file should hold exactly one .csv file."
        raise PostcodeTableError(msg)
    return io.TextIOWrapper(
        archive.open(members[0]), newline="", encoding="utf-8-sig", errors="replace"
    )
