"""Picks how to arrange the tiles for a given window size (no Tk here, so it is easy to test)."""

from __future__ import annotations

import math

NO_FIT = 0  # choose_columns(): no grid fits
GAP_X = 16  # space between columns
GAP_Y = 12  # space between rows


def grid_size(count: int, columns: int, cell_w: int, cell_h: int) -> tuple[int, int]:
    """Space needed for `count` tiles in `columns` columns."""
    rows = -(-count // columns)  # ceil
    return columns * cell_w + (columns - 1) * GAP_X, rows * cell_h + (rows - 1) * GAP_Y


def choose_columns(count: int, cell_w: int, cell_h: int, width: int, height: int) -> int:
    """Number of columns to fit `count` tiles in width x height, or NO_FIT.

    When several grids fit, take the one whose shape is closest to the window's:
    a short wide window gets one row, a narrow tall one gets one column.
    """
    if count <= 0 or width <= 0 or height <= 0:
        return NO_FIT
    target = math.log(width / height)
    best, best_score = NO_FIT, math.inf
    for columns in range(1, count + 1):
        need_w, need_h = grid_size(count, columns, cell_w, cell_h)
        if need_w > width or need_h > height:
            continue
        score = abs(math.log(need_w / need_h) - target)
        if score < best_score:
            best, best_score = columns, score
    return best


def choose_layout(
    count: int, cell_w: int, cell_h: int, width: int, height: int, arrows_w: int = 0
) -> tuple[int, int]:
    """Return (visible tiles, columns) for the space inside the panel.

    Shows all tiles if they fit. Otherwise as many as fit next to the ‹ › arrows
    (which take `arrows_w`), down to one tile.
    """
    for visible in range(count, 0, -1):
        avail_w = width if visible == count else width - arrows_w
        columns = choose_columns(visible, cell_w, cell_h, avail_w, height)
        if columns != NO_FIT:
            return visible, columns
    return min(1, count), 1


def fit_row(widths: list[int], width: int, arrows_w: int = 0, first: int = 0) -> int:
    """How many tiles of different widths fit in one row (the slim strip).

    All of them if they fit. Otherwise as many as fit next to the ‹ › arrows,
    starting at tile `first` and wrapping around, but at least one.
    """
    count = len(widths)
    if count == 0:
        return 0
    if sum(widths) + (count - 1) * GAP_X <= width:
        return count
    used = visible = 0
    for i in range(count):
        need = widths[(first + i) % count] + (GAP_X if visible else 0)
        if used + need > width - arrows_w:
            break
        used += need
        visible += 1
    return max(1, visible)
