#!/usr/bin/env python3
"""Build a first-screen Shivers PoC by aliasing font 37 glyph A to Hangul ga."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
from pathlib import Path

from PIL import Image


SOURCE_ISO_SHA256 = "62E7E35D288D7C4ACB3A04CDE1CC9865D3B24E8EB40F8CB32D86DC00B28A80C9"
GLYPH_INDEX = 65
PATCH_HEADER = bytes((0x87, 0x00))
FONT_TARGETS = {
    37: {
        "build_id": "scummvm_ko_poc_004_name_font_alias",
        "source_name": "00037.fon",
        "source_sha256": "7F0520621FD461475064041DD41E9B5E5B9903DA04808F50CE5ABE7463647A0D",
        "source_size": 1921,
        "glyph_offset": 1023,
        "width": 9,
        "height": 12,
        "expected_bitmap": bytes.fromhex("000000000E000F001B001B003F00330073006300E3000100"),
        "glyph_source": "poc_ga_9x12_font37.txt",
    },
    7: {
        "build_id": "scummvm_ko_poc_005_name_font7_alias",
        "source_name": "00007.fon",
        "source_sha256": "A4707A1B29CFDCAC25A916C653AEA6329EB601FA73C3BB2B98E84CDF515CE0F6",
        "source_size": 3466,
        "glyph_offset": 1312,
        "width": 15,
        "height": 17,
        "expected_bitmap": bytes.fromhex("0000000001C001C003E003E003E0077007700F780E380FF81FFC1C1C3C1E380E380E"),
        "glyph_source": "poc_ga_15x17_font7.txt",
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def read_pattern(path: Path, width: int, height: int) -> tuple[list[str], bytes]:
    rows = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != height or any(len(row) != width for row in rows):
        raise ValueError(f"Glyph source must be exactly {width}x{height}")
    if any(pixel not in ".#" for row in rows for pixel in row):
        raise ValueError("Glyph source accepts only '.' and '#'")
    stride = (width + 7) // 8
    bitmap = bytearray()
    for row in rows:
        bits = int("".join("1" if pixel == "#" else "0" for pixel in row).ljust(stride * 8, "0"), 2)
        bitmap.extend(bits.to_bytes(stride, "big"))
    return rows, bytes(bitmap)


def hardlink_tree(source: Path, destination: Path) -> tuple[int, int]:
    count = 0
    size = 0
    for source_path in sorted(source.rglob("*")):
        relative = source_path.relative_to(source)
        destination_path = destination / relative
        if source_path.is_dir():
            destination_path.mkdir(parents=True, exist_ok=True)
        elif source_path.is_file():
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            os.link(source_path, destination_path)
            count += 1
            size += source_path.stat().st_size
        else:
            raise ValueError(f"Unsupported source entry: {source_path}")
    return count, size


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-id", default="")
    parser.add_argument("--font-id", type=int, choices=sorted(FONT_TARGETS), default=37)
    args = parser.parse_args()
    target = FONT_TARGETS[args.font_id]
    build_id = args.build_id or target["build_id"]

    project = Path(__file__).resolve().parents[2]
    source_root = project / "extracted" / "installer"
    source_iso = project / "original" / "installer" / "SHIVCD.iso"
    source_font = project / "extracted" / "sci" / "font" / target["source_name"]
    glyph_source = project / "workspace" / "fonts" / target["glyph_source"]
    output_root = project / "build" / build_id
    if output_root.exists():
        raise FileExistsError(f"Refusing to replace existing build: {output_root}")
    if sha256_file(source_iso) != SOURCE_ISO_SHA256:
        raise ValueError("Source ISO SHA-256 mismatch")
    if source_font.stat().st_size != target["source_size"] or sha256_file(source_font) != target["source_sha256"]:
        raise ValueError(f"Source font {args.font_id} identity mismatch")

    source_data = source_font.read_bytes()
    table_offset = struct.unpack_from("<H", source_data, 6 + GLYPH_INDEX * 2)[0]
    width, height = source_data[table_offset : table_offset + 2]
    if (table_offset, width, height) != (target["glyph_offset"], target["width"], target["height"]):
        raise ValueError(f"Font {args.font_id} glyph A metadata mismatch")
    bitmap_offset = table_offset + 2
    expected_bitmap = target["expected_bitmap"]
    if source_data[bitmap_offset : bitmap_offset + len(expected_bitmap)] != expected_bitmap:
        raise ValueError(f"Font {args.font_id} glyph A Expected Write mismatch")

    rows, bitmap = read_pattern(glyph_source, width, height)
    output_root.mkdir(parents=True)
    hardlinked_files, hardlinked_bytes = hardlink_tree(source_root, output_root)
    patched = bytearray(source_data)
    patched[bitmap_offset : bitmap_offset + len(bitmap)] = bitmap
    changed_offsets = [index for index, pair in enumerate(zip(source_data, patched)) if pair[0] != pair[1]]
    if not changed_offsets or any(index < bitmap_offset or index >= bitmap_offset + len(bitmap) for index in changed_offsets):
        raise AssertionError(f"Unexpected font diff offsets: {changed_offsets}")

    patch_path = output_root / f"{args.font_id}.fon"
    patch_path.write_bytes(PATCH_HEADER + patched)
    if patch_path.read_bytes()[2:] != patched:
        raise AssertionError("Font patch round-trip failed")

    preview = Image.new("RGB", (width, height), "white")
    pixels = preview.load()
    for y, row in enumerate(rows):
        for x, pixel in enumerate(row):
            if pixel == "#":
                pixels[x, y] = (0, 0, 0)
    preview_path = output_root / f"poc_ga_font{args.font_id}_preview.png"
    preview.resize((width * 16, height * 16), Image.Resampling.NEAREST).save(preview_path)

    manifest = {
        "schema_version": 1,
        "build_id": build_id,
        "scope": "Earliest-screen single-byte visual alias PoC",
        "source": {
            "iso_sha256": SOURCE_ISO_SHA256,
            "font_path": str(source_font.relative_to(project)).replace("\\", "/"),
            "font_size": target["source_size"],
            "font_sha256": target["source_sha256"],
        },
        "expected_write": {
            "owner": "POC-VIS-002",
            "meaning": f"Alias font {args.font_id} ASCII A glyph to a Hangul ga bitmap",
            "glyph_index": GLYPH_INDEX,
            "glyph_bitmap_offset": bitmap_offset,
            "expected_source_hex": expected_bitmap.hex().upper(),
            "output_hex": bitmap.hex().upper(),
            "changed_offsets": changed_offsets,
        },
        "output": {
            "hardlinked_source_files": hardlinked_files,
            "hardlinked_source_bytes": hardlinked_bytes,
            "patch_path": patch_path.name,
            "patch_size": patch_path.stat().st_size,
            "patch_sha256": sha256_file(patch_path),
            "preview_path": preview_path.name,
            "preview_sha256": sha256_file(preview_path),
        },
        "proved_by_build": [
            "supported source identity",
            f"font {args.font_id} glyph A-only bitmap replacement",
            "unchanged font resource length and glyph table",
        ],
        "not_proved_by_build": [
            "runtime patch consumption",
            "runtime visibility/readability",
            "EUC-KR two-byte rendering",
            "original SIERRAW.EXE compatibility",
        ],
    }
    manifest_path = output_root / "poc_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"build_id={build_id}")
    print(f"output={output_root}")
    print(f"changed_offsets={changed_offsets}")
    print(f"patch_sha256={manifest['output']['patch_sha256']}")
    print("static_validation=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
