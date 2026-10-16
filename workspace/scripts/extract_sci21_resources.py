#!/usr/bin/env python3
"""Extract selected Shivers SCI 2.1 resources with strict size validation."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path

from inventory_shivers import parse_sci21_map


EXTENSIONS = {
    "script": "scr",
    "vocab": "voc",
    "font": "fon",
    "message": "msg",
    "heap": "hep",
}


class MsbBitReader:
    def __init__(self, data: bytes):
        self.data = data
        self.bit_position = 0

    def bits(self, count: int) -> int:
        value = 0
        for _ in range(count):
            byte_index, bit_index = divmod(self.bit_position, 8)
            if byte_index >= len(self.data):
                raise ValueError("compressed stream ended before output was complete")
            value = (value << 1) | ((self.data[byte_index] >> (7 - bit_index)) & 1)
            self.bit_position += 1
        return value


def lzs_length(reader: MsbBitReader) -> int:
    first = reader.bits(2)
    if first < 3:
        return first + 2
    second = reader.bits(2)
    if second < 3:
        return second + 5
    length = 8
    while True:
        nibble = reader.bits(4)
        length += nibble
        if nibble != 0xF:
            return length


def decompress_lzs(data: bytes, expected_size: int) -> bytes:
    reader = MsbBitReader(data)
    output = bytearray()
    while len(output) < expected_size:
        if reader.bits(1):
            if reader.bits(1):
                offset = reader.bits(7)
                if offset == 0:
                    break
            else:
                offset = reader.bits(11)
            length = lzs_length(reader)
            if offset == 0 or offset > len(output):
                raise ValueError(f"invalid LZS offset {offset} at output byte {len(output)}")
            if len(output) + length > expected_size:
                raise ValueError("LZS copy exceeds declared unpacked size")
            for _ in range(length):
                output.append(output[-offset])
        else:
            if len(output) >= expected_size:
                raise ValueError("LZS literal exceeds declared unpacked size")
            output.append(reader.bits(8))
    if len(output) != expected_size:
        raise ValueError(f"LZS output size {len(output)} != expected {expected_size}")
    return bytes(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Shivers1 project root",
    )
    parser.add_argument(
        "--types",
        default="script,vocab,font,message,heap",
        help="comma-separated resource type names",
    )
    args = parser.parse_args()
    project = args.project.resolve()
    selected_types = {value.strip() for value in args.types.split(",") if value.strip()}
    unknown_types = selected_types - set(EXTENSIONS)
    if unknown_types:
        raise ValueError(f"unsupported extraction type(s): {', '.join(sorted(unknown_types))}")

    map_path = project / "extracted" / "installer" / "RESMAP.000"
    volume_path = project / "extracted" / "installer" / "RESSCI.000"
    rows, _ = parse_sci21_map(map_path, volume_path)
    selected = [row for row in rows if row["type_name"] in selected_types]
    output_root = project / "extracted" / "sci"
    output_root.mkdir(parents=True, exist_ok=True)

    manifest = []
    with volume_path.open("rb") as volume:
        for row in selected:
            resource_type = str(row["type_name"])
            number = int(row["number"])
            packed_size = int(row["packed_size"])
            unpacked_size = int(row["unpacked_size"])
            compression = int(row["compression"])
            volume.seek(int(row["volume_offset"]) + 13)
            packed = volume.read(packed_size)
            if len(packed) != packed_size:
                raise ValueError(f"short payload for {resource_type}:{number}")
            if compression == 0:
                if packed_size != unpacked_size:
                    raise ValueError(f"uncompressed size mismatch for {resource_type}:{number}")
                unpacked = packed
            elif compression == 32:
                unpacked = decompress_lzs(packed, unpacked_size)
            else:
                raise ValueError(f"unsupported compression {compression} for {resource_type}:{number}")

            extension = EXTENSIONS[resource_type]
            relative_path = Path(resource_type) / f"{number:05d}.{extension}"
            output_path = output_root / relative_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(unpacked)
            manifest.append(
                {
                    "type_name": resource_type,
                    "number": number,
                    "compression": compression,
                    "packed_size": packed_size,
                    "unpacked_size": unpacked_size,
                    "sha256": hashlib.sha256(unpacked).hexdigest().upper(),
                    "path": relative_path.as_posix(),
                }
            )

    manifest_path = project / "workspace" / "analysis" / "extracted_resource_manifest.csv"
    with manifest_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=manifest[0].keys())
        writer.writeheader()
        writer.writerows(manifest)

    print(f"selected_types={','.join(sorted(selected_types))}")
    print(f"extracted_resources={len(manifest)}")
    print(f"unpacked_bytes={sum(int(row['unpacked_size']) for row in manifest)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
