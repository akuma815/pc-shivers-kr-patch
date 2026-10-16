#!/usr/bin/env python3
"""Build labeled contact sheets for reviewing OCR-selected graphics."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-root", type=Path, required=True)
    parser.add_argument("--ocr-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--columns", type=int, default=5)
    parser.add_argument("--rows", type=int, default=4)
    parser.add_argument("--cell-width", type=int, default=240)
    parser.add_argument("--cell-height", type=int, default=190)
    parser.add_argument("--min-ascii-letters", type=int, default=1)
    parser.add_argument("--one-per-resource", action="store_true")
    parser.add_argument("--min-resource", type=int)
    parser.add_argument("--max-resource", type=int)
    args = parser.parse_args()

    root = args.image_root.resolve()
    with args.ocr_csv.open("r", encoding="utf-8-sig", newline="") as stream:
        source_rows = list(csv.DictReader(stream))
    selected = []
    for row in source_rows:
        letters = sum(character.isascii() and character.isalpha() for character in row["text"])
        path = root / Path(row["path"])
        path_parts = row["path"].split("/")
        path_resource_id = next(part for part in path_parts if part.isdigit())
        resource_id = row.get("label") or path_resource_id
        resource_number = int(path_resource_id)
        in_range = (
            (args.min_resource is None or resource_number >= args.min_resource)
            and (args.max_resource is None or resource_number <= args.max_resource)
        )
        if letters >= args.min_ascii_letters and in_range and path.is_file():
            selected.append((path, resource_id, letters))

    if args.one_per_resource:
        best: dict[str, tuple[Path, str, int]] = {}
        for item in selected:
            if item[1] not in best or item[2] > best[item[1]][2]:
                best[item[1]] = item
        selected = sorted(best.values(), key=lambda item: int(item[1]))

    args.output.mkdir(parents=True, exist_ok=True)
    font = ImageFont.load_default(size=16)
    page_size = args.columns * args.rows
    sheet_width = args.columns * args.cell_width
    sheet_height = args.rows * args.cell_height
    for page in range(math.ceil(len(selected) / page_size)):
        sheet = Image.new("RGB", (sheet_width, sheet_height), (38, 38, 38))
        draw = ImageDraw.Draw(sheet)
        for slot, (path, resource_id, letters) in enumerate(
            selected[page * page_size : (page + 1) * page_size]
        ):
            column = slot % args.columns
            row = slot // args.columns
            x = column * args.cell_width
            y = row * args.cell_height
            with Image.open(path) as source:
                source = source.convert("RGBA")
                backdrop = Image.new("RGBA", source.size, (0, 0, 0, 255))
                backdrop.alpha_composite(source)
                image = backdrop.convert("RGB")
                image.thumbnail((args.cell_width - 8, args.cell_height - 30), Image.Resampling.LANCZOS)
                px = x + (args.cell_width - image.width) // 2
                py = y + 24 + (args.cell_height - 28 - image.height) // 2
                sheet.paste(image, (px, py))
            score = "" if ":" in resource_id else f"  OCR:{letters}"
            draw.text((x + 5, y + 3), f"{resource_id}{score}", fill="white", font=font)
        path = args.output / f"sheet_{page + 1:03d}.png"
        sheet.save(path, optimize=True)

    print(f"selected={len(selected)}")
    print(f"sheets={math.ceil(len(selected) / page_size)}")
    print(f"output={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
