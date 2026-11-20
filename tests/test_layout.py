from __future__ import annotations

from specter.ui.layout import GAP_X, GAP_Y, NO_FIT, choose_columns, choose_layout, fit_row, grid_size

ARROWS = 40

CELL_W, CELL_H = 100, 60


def test_grid_size_counts_gaps_and_partial_rows():
    assert grid_size(3, 3, CELL_W, CELL_H) == (3 * CELL_W + 2 * GAP_X, CELL_H)
    assert grid_size(3, 2, CELL_W, CELL_H) == (2 * CELL_W + GAP_X, 2 * CELL_H + GAP_Y)
    assert grid_size(3, 1, CELL_W, CELL_H) == (CELL_W, 3 * CELL_H + 2 * GAP_Y)


def test_short_wide_window_puts_tiles_side_by_side():
    assert choose_columns(3, CELL_W, CELL_H, 400, 70) == 3


def test_narrow_tall_window_stacks_tiles():
    assert choose_columns(3, CELL_W, CELL_H, 110, 260) == 1


def test_squarish_window_uses_a_grid():
    assert choose_columns(3, CELL_W, CELL_H, 230, 140) == 2


def test_big_window_follows_its_shape():
    assert choose_columns(3, CELL_W, CELL_H, 1000, 150) == 3
    assert choose_columns(3, CELL_W, CELL_H, 150, 1000) == 1


def test_nothing_fits():
    assert choose_columns(3, CELL_W, CELL_H, 150, 100) == NO_FIT
    assert choose_columns(0, CELL_W, CELL_H, 500, 500) == NO_FIT
    assert choose_columns(3, CELL_W, CELL_H, 0, 0) == NO_FIT


def test_layout_shows_all_tiles_when_they_fit():
    assert choose_layout(3, CELL_W, CELL_H, 230, 140, ARROWS) == (3, 2)


def test_layout_shrinks_from_three_to_two_stacked():
    # Too short for three stacked, too narrow for side by side: two stacked + arrows.
    assert choose_layout(3, CELL_W, CELL_H, 150, 140, ARROWS) == (2, 1)


def test_layout_shrinks_to_two_side_by_side_when_short():
    assert choose_layout(3, CELL_W, CELL_H, 300, 70, ARROWS) == (2, 2)


def test_layout_shrinks_to_one():
    assert choose_layout(3, CELL_W, CELL_H, 150, 70, ARROWS) == (1, 1)
    assert choose_layout(3, CELL_W, CELL_H, 10, 10, ARROWS) == (1, 1)


def test_layout_with_no_tiles():
    assert choose_layout(0, CELL_W, CELL_H, 500, 500, ARROWS) == (0, 1)


def test_fit_row_all_when_they_fit():
    assert fit_row([100, 50, 80], 230 + 2 * GAP_X, ARROWS) == 3
    assert fit_row([], 500, ARROWS) == 0


def test_fit_row_fills_space_next_to_arrows_from_first():
    widths = [100, 50, 80, 120]
    width = ARROWS + 130 + GAP_X  # room for 50 + 80, but not 100 + 50
    assert fit_row(widths, width, ARROWS, first=0) == 1
    assert fit_row(widths, width, ARROWS, first=1) == 2
    assert fit_row(widths, width, ARROWS, first=3) == 1  # wraps: 120, then 100 is too much


def test_fit_row_shows_at_least_one():
    assert fit_row([300, 50], 100, ARROWS) == 1
