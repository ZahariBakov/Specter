"""Draws the Specter icon (no dependencies): src/specter/assets/icon.png and icon.ico.

Run:  python tools/make_icon.py
Four bars on a dark rounded square, coloured like the panel's bars (green, yellow, red).
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "src" / "specter" / "assets"

BG = (16, 18, 21)
BORDER = (47, 111, 236)
GREEN, YELLOW, RED = (61, 220, 132), (245, 197, 66), (255, 91, 91)
# Drawn on a 256 grid: (x, top, width, height, colour). They share one baseline at y=206.
BARS = [
    (35, 150, 36, 56, GREEN),
    (85, 110, 36, 96, GREEN),
    (135, 72, 36, 134, YELLOW),
    (185, 44, 36, 162, RED),
]
SUPERSAMPLE = 3


def _inside_round_rect(x: float, y: float, x0: float, y0: float, x1: float, y1: float, r: float) -> bool:
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def _colour_at(x: float, y: float) -> tuple[int, int, int, int]:
    """RGBA at a point of the 256x256 design."""
    if not _inside_round_rect(x, y, 6, 6, 250, 250, 52):
        return 0, 0, 0, 0
    for bx, top, width, height, colour in BARS:
        if _inside_round_rect(x, y, bx, top, bx + width, top + height, 7):
            return (*colour, 255)
    if not _inside_round_rect(x, y, 12, 12, 244, 244, 46):
        return (*BORDER, 255)
    return (*BG, 255)


def render(size: int) -> bytes:
    """RGBA pixels, size x size, anti-aliased by supersampling."""
    scale = 256 / size
    n = SUPERSAMPLE
    rows = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            total = [0, 0, 0, 0]
            for sy in range(n):
                for sx in range(n):
                    r, g, b, a = _colour_at((px + (sx + 0.5) / n) * scale, (py + (sy + 0.5) / n) * scale)
                    total[0] += r * a
                    total[1] += g * a
                    total[2] += b * a
                    total[3] += a
            alpha = total[3]
            if alpha:
                row += bytes((total[0] // alpha, total[1] // alpha, total[2] // alpha, alpha // (n * n)))
            else:
                row += bytes(4)
        rows.append(bytes(row))
    return b"".join(rows)


def png(size: int) -> bytes:
    pixels = render(size)
    raw = b"".join(b"\x00" + pixels[y * size * 4 : (y + 1) * size * 4] for y in range(size))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def ico(sizes: list[int]) -> bytes:
    """A Windows icon holding one PNG per size."""
    images = [png(s) for s in sizes]
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for size, data in zip(sizes, images):
        out += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return out + b"".join(images)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    (ASSETS / "icon.png").write_bytes(png(256))
    (ASSETS / "icon.ico").write_bytes(ico([256, 64, 48, 32, 16]))
    print("wrote", ASSETS / "icon.png", "and", ASSETS / "icon.ico")


if __name__ == "__main__":
    main()
