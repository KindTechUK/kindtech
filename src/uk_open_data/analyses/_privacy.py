"""Hiding small counts so a table of totals cannot point at a person."""

from __future__ import annotations

DEFAULT_SUPPRESS_BELOW = 5
# Every analysis says this in its privacy notes, so a reader does not take every
# hidden count for a small one.
SECOND_COUNT_NOTE = (
    "A hidden count is not always small. When only one count in a table is "
    "small, a second is hidden with it, so the first cannot be worked out "
    "from the total."
)


def is_small(count: int, threshold: int) -> bool:
    """Return True when a count is above zero but below the threshold."""
    return 0 < count < threshold


def cells_to_hide(
    counts: list[int],
    threshold: int,
    groups: tuple[tuple[int, ...], ...] = (),
) -> list[bool]:
    """Decide which cells of a table to hide when its total is published.

    A cell from 1 to ``threshold - 1`` is hidden. If exactly one cell is hidden
    it could be worked out by taking the others from the total, so the smallest
    remaining cell above zero is hidden with it.

    Args:
        counts: The counts in the table, one per cell.
        threshold: Counts below this (and above zero) are hidden.
        groups: Sets of cell positions that are also published as a sum. The
            second cell is taken from the same group as the first when it can
            be, so the group's sum gives neither away and can still be shown.

    Returns:
        One boolean per cell, True where the cell must be hidden.
    """
    hide = [is_small(count, threshold) for count in counts]
    if sum(hide) != 1:
        return hide
    first = hide.index(True)
    candidates = [
        (count, index)
        for index, count in enumerate(counts)
        if count > 0 and not hide[index]
    ]
    same_group = [
        (count, index)
        for count, index in candidates
        if any(first in group and index in group for group in groups)
    ]
    if candidates:
        _, partner = min(same_group or candidates)
        hide[partner] = True
    return hide


def group_hidden(
    counts: list[int], hide: list[bool], positions: tuple[int, ...], threshold: int
) -> bool:
    """Decide whether a figure for a group of cells must be hidden.

    The total is published, so a figure for a group also gives the figure for
    every cell outside it. Each side is checked: a side gives a cell away
    when its own count is small, or when exactly one of its cells is hidden in
    the table.
    """
    outside = tuple(i for i in range(len(counts)) if i not in positions)
    for side in (positions, outside):
        total = sum(counts[position] for position in side)
        hidden_cells = sum(hide[position] for position in side)
        if is_small(total, threshold) or hidden_cells == 1:
            return True
    return False


def count_band(count: int, threshold: int) -> str:
    """Put a count in a band so a map never shows an exact small number.

    The lowest band covers zero up to ``threshold - 1``, so an area with nobody
    in it looks the same as an area with a few people.
    """
    edges = [threshold, threshold * 2, threshold * 4, threshold * 10]
    if count < edges[0]:
        return f"fewer than {edges[0]}"
    for lower, upper in zip(edges, edges[1:], strict=False):
        if count < upper:
            return f"{lower} to {upper - 1}"
    return f"{edges[-1]} or more"


def band_labels(threshold: int) -> list[str]:
    """Return every band label, lowest first, for a map legend."""
    edges = [0, threshold, threshold * 2, threshold * 4, threshold * 10]
    return [count_band(edge, threshold) for edge in edges]
