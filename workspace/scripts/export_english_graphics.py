#!/usr/bin/env python3
"""Export the manually reviewed Shivers graphics that contain English text."""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path


def stepped(start: int, end: int, step: int = 1) -> list[int]:
    return list(range(start, end + 1, step))


PIC_GROUPS = {
    "title_logo_death_and_save_screens": [
        5, 899, 900, 902, 910, 911, 914, 918, 920, 921, 922, 923, 927, 991, 993, 994
    ],
    "letters_books_newspapers_and_personal_documents": [
        1003, 1004,
        *stepped(3111, 3117),
        6111, 6162, 6163, *stepped(6200, 6202), *stepped(6221, 6228), 7162,
        *stepped(8342, 8347), *stepped(8413, 8416), 8530, 8630, 8650, 8660, 8680, 8690,
        9800, 9810, 9901, 9902,
        10122, 10132, 10133, 10142,
        10204, *stepped(10205, 10209), 10211, 10212, 10481,
        *stepped(12182, 12186),
        16431, 23311,
        *stepped(24502, 24507), 24509,
        29042, 29043, 35154, 37252, 39311, 51234,
    ],
    "museum_exhibit_placards_and_puzzle_instructions": [
        *stepped(11400, 11440, 10), *stepped(11900, 11930, 10),
        *stepped(12550, 12590, 10), 12800, 12820, 13891, 14200,
        *stepped(20900, 20930, 10), 21141, 21181, 21204, 21321, 21411,
        *stepped(21800, 21840, 10), *stepped(22800, 22820, 10),
        *stepped(23900, 23960, 10), *stepped(24800, 24840, 10),
        *stepped(29800, 29830, 10), 31800, 32800, 32810,
    ],
    "environmental_signs_and_labels": [
        1020, 1030, 10290, 11510, 20441, 28050,
        30080, 30090, 30110, 30140, 30170, 30180, 30280, 30290,
        30310, 30330, 30350, 30390, 30440, 30460, 30470, 30600,
        39060, 39070, 39090, 39120, 39121, 39150, 39170, 39210, 39240,
    ],
}


VIEW_GROUPS = {
    "menu_buttons_dialogs_and_input_glyphs": [
        899, 910, 920, 921, 922, 923, 927, 928, 990, 991, 993, 994, 50400, 55555
    ],
    "books_scrapbook_diary_blueprints_and_notes": [
        *stepped(6221, 6225), *stepped(8342, 8348), *stepped(8413, 8416),
        *stepped(8631, 8635), *stepped(8691, 8693),
        *stepped(10205, 10209), 10211, 10212,
        10290, *stepped(12182, 12186), 12221, 16374, 16434, 16905,
        *stepped(21111, 21119), *stepped(24502, 24504),
        28051, 29042, 29260, 35154,
        *stepped(37252, 37265),
    ],
}


def flatten(groups: dict[str, list[int]]) -> tuple[list[int], dict[int, str]]:
    categories: dict[int, str] = {}
    for category, numbers in groups.items():
        for number in numbers:
            if number in categories:
                raise ValueError(f"duplicate resource {number}: {categories[number]} and {category}")
            categories[number] = category
    return sorted(categories), categories


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        help="output root; defaults to workspace/graphics/english_assets",
    )
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[2]
    output = args.output or project / "workspace" / "graphics" / "english_assets"
    if not output.is_absolute():
        output = project / output
    pic_numbers, pic_categories = flatten(PIC_GROUPS)
    view_numbers, view_categories = flatten(VIEW_GROUPS)
    selection = ["palette:999"]
    selection.extend(f"pic:{number}" for number in pic_numbers)
    selection.extend(f"view:{number}" for number in view_numbers)
    subprocess.run(
        [
            sys.executable,
            "-B",
            str(Path(__file__).with_name("extract_sci21_graphics.py")),
            "--project",
            str(project),
            "--select",
            ",".join(selection),
            "--output",
            str(output),
        ],
        check=True,
    )

    manifest_rows = list(
        csv.DictReader((output / "manifest.csv").open("r", encoding="utf-8-sig", newline=""))
    )
    raw_by_resource = {
        (row["type_name"], int(row["number"])): row
        for row in manifest_rows
        if row["note"] == "decompressed original resource"
    }
    catalog = []
    for kind, numbers, categories in (
        ("pic", pic_numbers, pic_categories),
        ("view", view_numbers, view_categories),
    ):
        for number in numbers:
            raw = raw_by_resource[(kind, number)]
            png_count = sum(
                1
                for row in manifest_rows
                if row["type_name"] == kind
                and int(row["number"]) == number
                and row["path"].endswith(".png")
            )
            catalog.append(
                {
                    "type_name": kind,
                    "number": number,
                    "category": categories[number],
                    "review_status": "english_visible_manual_review_2026-08-30",
                    "raw_sha256": raw["sha256"],
                    "raw_path": raw["path"],
                    "png_root": f"png/{kind}/{number:05d}",
                    "png_count": png_count,
                }
            )
    catalog_path = output / "english_graphics_catalog.csv"
    with catalog_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=catalog[0].keys())
        writer.writeheader()
        writer.writerows(catalog)

    overview_rows = []
    for catalog_row in catalog:
        kind = catalog_row["type_name"]
        number = int(catalog_row["number"])
        png_rows = [
            row
            for row in manifest_rows
            if row["type_name"] == kind
            and int(row["number"]) == number
            and row["path"].endswith(".png")
        ]
        representative = max(
            png_rows,
            key=lambda row: int(row["width"]) * int(row["height"]),
        )
        overview_rows.append(
            {
                "path": representative["path"],
                "text": catalog_row["category"],
                "label": f"{kind[0].upper()}:{number:05d}",
            }
        )
    overview_index = output / "overview_index.csv"
    with overview_index.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=overview_rows[0].keys())
        writer.writeheader()
        writer.writerows(overview_rows)
    subprocess.run(
        [
            sys.executable,
            "-B",
            str(Path(__file__).with_name("make_graphics_contact_sheets.py")),
            "--image-root",
            str(output),
            "--ocr-csv",
            str(overview_index),
            "--output",
            str(output / "overview"),
            "--columns",
            "5",
            "--rows",
            "4",
            "--cell-width",
            "240",
            "--cell-height",
            "190",
            "--min-ascii-letters",
            "0",
        ],
        check=True,
    )
    print(f"pic_resources={len(pic_numbers)}")
    print(f"view_resources={len(view_numbers)}")
    print(f"catalog={catalog_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
