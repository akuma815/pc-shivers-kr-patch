#!/usr/bin/env python3
"""Enumerate the SCI 1.1-2.1 NUL string area in every Shivers heap."""

from __future__ import annotations

import argparse
import csv
import struct
from pathlib import Path


OBJECT_MAGIC = 0x1234


def decode_cp1252(data: bytes) -> str:
    return data.decode("cp1252", errors="backslashreplace")


def parse_heap(heap: bytes, script_size: int, script_number: int) -> list[dict[str, object]]:
    if len(heap) < 4:
        raise ValueError(f"heap {script_number} is shorter than its four-byte header")
    end_of_strings, object_words = struct.unpack_from("<HH", heap, 0)
    object_start = object_words * 2 + 4
    if object_start > len(heap) or end_of_strings > len(heap):
        raise ValueError(f"heap {script_number} header points outside the resource")

    position = object_start
    object_count = 0
    while True:
        if position + 2 > end_of_strings:
            raise ValueError(f"heap {script_number} object list lacks its terminator")
        object_position = position
        block_type = struct.unpack_from("<H", heap, position)[0]
        position += 2
        if block_type != OBJECT_MAGIC:
            break
        if position + 2 > end_of_strings:
            raise ValueError(f"heap {script_number} object header is truncated")
        property_count = struct.unpack_from("<H", heap, position)[0]
        block_size = property_count * 2
        if block_size < 4 or object_position + block_size > end_of_strings:
            raise ValueError(f"heap {script_number} has an invalid object block")
        position = object_position + block_size
        object_count += 1

    string_start = position
    if string_start > end_of_strings:
        raise ValueError(f"heap {script_number} string block starts after its end")

    rows = []
    string_id = 0
    position = string_start
    while position < end_of_strings:
        nul = heap.find(b"\0", position, end_of_strings)
        if nul < 0:
            raise ValueError(f"heap {script_number} has a non-terminated string")
        raw = heap[position:nul]
        string_id += 1
        rows.append(
            {
                "script_number": script_number,
                "string_id": string_id,
                "heap_offset": position,
                "combined_offset": script_size + position,
                "byte_length": len(raw),
                "object_count": object_count,
                "ascii_printable": all(0x20 <= value <= 0x7E or value in (9, 10, 13) for value in raw),
                "text_cp1252": decode_cp1252(raw),
                "raw_hex": raw.hex().upper(),
            }
        )
        position = nul + 1
    return rows


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
    heap_root = project / "extracted" / "sci" / "heap"
    script_root = project / "extracted" / "sci" / "script"
    rows = []
    heap_count = 0
    for heap_path in sorted(heap_root.glob("*.hep")):
        script_number = int(heap_path.stem)
        script_path = script_root / f"{script_number:05d}.scr"
        if not script_path.is_file():
            raise ValueError(f"matching script is missing for heap {script_number}")
        rows.extend(parse_heap(heap_path.read_bytes(), script_path.stat().st_size, script_number))
        heap_count += 1

    output = project / "workspace" / "analysis" / "heap_strings.csv"
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    nonempty = [row for row in rows if int(row["byte_length"]) > 0]
    printable = [row for row in nonempty if bool(row["ascii_printable"])]
    print(f"heap_resources={heap_count}")
    print(f"heap_strings={len(rows)}")
    print(f"nonempty_strings={len(nonempty)}")
    print(f"printable_ascii_strings={len(printable)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
