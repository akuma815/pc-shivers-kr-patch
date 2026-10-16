#!/usr/bin/env python3
"""Create reproducible file and SCI 2.1 resource inventories for Shivers 1.

This script is read-only with respect to original/ and extracted/. Generated
CSV files are written below workspace/analysis/.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import struct
from collections import Counter
from pathlib import Path


RESOURCE_TYPES = {
    0x00: "view",
    0x01: "pic",
    0x02: "script",
    0x03: "animation",
    0x04: "sound",
    0x05: "etc",
    0x06: "vocab",
    0x07: "font",
    0x08: "cursor",
    0x09: "patch",
    0x0A: "bitmap",
    0x0B: "palette",
    0x0C: "audio",
    0x0D: "audio",
    0x0E: "sync",
    0x0F: "message",
    0x10: "map",
    0x11: "heap",
    0x12: "chunk",
    0x13: "audio36",
    0x14: "sync36",
    0x15: "translation",
    0x16: "robot",
    0x17: "vmd",
    0x18: "duck",
    0x19: "clut",
    0x1A: "tga",
    0x1B: "zzz",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def write_file_inventory(project: Path, output: Path) -> int:
    roots = (
        ("installer", project / "extracted" / "installer"),
        ("installed", project / "extracted" / "installed"),
    )
    rows = []
    for source, root in roots:
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            rows.append(
                {
                    "source": source,
                    "path": path.relative_to(root).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("source", "path", "size", "sha256"))
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def parse_sci21_map(map_path: Path, volume_path: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    map_data = map_path.read_bytes()
    directories: list[tuple[int, int]] = []
    cursor = 0
    while True:
        if cursor + 3 > len(map_data):
            raise ValueError("resource directory ended before 0xFF terminator")
        raw_type, offset = struct.unpack_from("<BH", map_data, cursor)
        cursor += 3
        resource_type = raw_type & 0x1F
        directories.append((resource_type, offset))
        if resource_type == 0x1F:
            if offset != len(map_data):
                raise ValueError(f"terminal directory offset {offset} != map size {len(map_data)}")
            break

    previous_offset = cursor
    for resource_type, offset in directories:
        if offset < previous_offset:
            raise ValueError(f"directory offsets are not ascending at type 0x{resource_type:02X}")
        previous_offset = offset

    volume_size = volume_path.stat().st_size
    rows: list[dict[str, object]] = []
    with volume_path.open("rb") as volume:
        for index in range(len(directories) - 1):
            resource_type, start = directories[index]
            end = directories[index + 1][1]
            byte_count = end - start
            if byte_count % 6:
                raise ValueError(
                    f"type 0x{resource_type:02X} map span {byte_count} is not divisible by 6"
                )
            for offset in range(start, end, 6):
                number, file_offset = struct.unpack_from("<HI", map_data, offset)
                if file_offset + 13 > volume_size:
                    raise ValueError(
                        f"resource 0x{resource_type:02X}:{number} header exceeds volume"
                    )
                volume.seek(file_offset)
                header = volume.read(13)
                header_type, header_number, packed_size, unpacked_size, compression = struct.unpack(
                    "<BHIIH", header
                )
                stored_end = file_offset + 13 + packed_size
                rows.append(
                    {
                        "type_code": f"0x{resource_type:02X}",
                        "type_name": RESOURCE_TYPES.get(resource_type, "unknown"),
                        "number": number,
                        "volume_offset": file_offset,
                        "header_type_code": f"0x{header_type:02X}",
                        "header_number": header_number,
                        "packed_size": packed_size,
                        "unpacked_size": unpacked_size,
                        "compression": compression,
                        "header_matches_map": header_type == resource_type and header_number == number,
                        "payload_in_bounds": stored_end <= volume_size,
                    }
                )

    summary_counter = Counter(
        (row["type_code"], row["type_name"], row["compression"]) for row in rows
    )
    summaries = [
        {
            "type_code": type_code,
            "type_name": type_name,
            "compression": compression,
            "count": count,
        }
        for (type_code, type_name, compression), count in sorted(summary_counter.items())
    ]
    return rows, summaries


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write an empty inventory: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


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
    analysis = project / "workspace" / "analysis"
    analysis.mkdir(parents=True, exist_ok=True)

    file_count = write_file_inventory(project, analysis / "file_inventory.csv")
    resource_rows, summary_rows = parse_sci21_map(
        project / "extracted" / "installer" / "RESMAP.000",
        project / "extracted" / "installer" / "RESSCI.000",
    )
    write_csv(analysis / "resource_map.csv", resource_rows)
    write_csv(analysis / "resource_type_summary.csv", summary_rows)

    header_failures = sum(not bool(row["header_matches_map"]) for row in resource_rows)
    bounds_failures = sum(not bool(row["payload_in_bounds"]) for row in resource_rows)
    print(f"file_inventory_rows={file_count}")
    print(f"resource_rows={len(resource_rows)}")
    print(f"header_failures={header_failures}")
    print(f"bounds_failures={bounds_failures}")
    return 0 if not header_failures and not bounds_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
