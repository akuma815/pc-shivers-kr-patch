#!/usr/bin/env python3
"""Validate and summarize decompressed SCI bitmap-font resources."""

from __future__ import annotations

import argparse
import csv
import struct
from pathlib import Path


def analyze_font(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    if len(data) < 6:
        raise ValueError(f"font is too short: {path}")
    first_word, character_count, line_height = struct.unpack_from("<HHH", data, 0)
    offset_table_end = 6 + character_count * 2
    if offset_table_end > len(data):
        raise ValueError(f"font offset table exceeds resource: {path}")

    widths = []
    heights = []
    unique_offsets = set()
    for character in range(character_count):
        offset = struct.unpack_from("<H", data, 6 + character * 2)[0]
        if offset + 2 > len(data):
            raise ValueError(f"glyph {character} header exceeds font: {path}")
        width, height = data[offset], data[offset + 1]
        bitmap_size = ((width + 7) // 8) * height
        if offset + 2 + bitmap_size > len(data):
            raise ValueError(f"glyph {character} bitmap exceeds font: {path}")
        widths.append(width)
        heights.append(height)
        unique_offsets.add(offset)

    return {
        "font_number": int(path.stem),
        "resource_size": len(data),
        "header_word_0": first_word,
        "character_count": character_count,
        "line_height": line_height,
        "unique_glyph_offsets": len(unique_offsets),
        "min_glyph_width": min(widths),
        "max_glyph_width": max(widths),
        "min_glyph_height": min(heights),
        "max_glyph_height": max(heights),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Shivers1 project root",
    )
    args = parser.parse_args()
    project = args.project.resolve()
    font_root = project / "extracted" / "sci" / "font"
    rows = [analyze_font(path) for path in sorted(font_root.glob("*.fon"))]
    output = project / "workspace" / "analysis" / "font_inventory.csv"
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"font_resources={len(rows)}")
    print(f"max_character_count={max(int(row['character_count']) for row in rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
