#!/usr/bin/env python3
"""Build the first reversible Shivers Korean visibility PoC for ScummVM."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
from pathlib import Path

from PIL import Image


BUILD_ID = "scummvm_ko_poc_001"
SOURCE_ISO_SHA256 = "62E7E35D288D7C4ACB3A04CDE1CC9865D3B24E8EB40F8CB32D86DC00B28A80C9"
SOURCE_HEAP_SHA256 = "9A45F316D43ED635D2C48F15D5C614D39E5EDB5925249671765A39C0668BA39E"
SOURCE_HEAP_SIZE = 1728
TARGET_HEAP_OFFSET = 91
EXPECTED_SOURCE = bytes.fromhex("5468")  # "Th" after the leading space
EXPECTED_OUTPUT = bytes.fromhex("B0A1")  # EUC-KR/CP949 "가"
NAME_HEAP_SHA256 = "CDE580C62F5A9B00797B0E7193154B2DD98B2445A176A97D78AA7AB08FE6D3D8"
NAME_HEAP_SIZE = 5782
NAME_HEAP_OFFSET = 5479
NAME_EXPECTED_SOURCE = bytes.fromhex("41004200")  # "A\0B\0"
NAME_EXPECTED_OUTPUT = bytes.fromhex("B0A10000")  # "가\0\0" for the A button value
PATCH_HEADER = bytes((0x91, 0x00))  # heap resource type | 0x80, zero extra header
KOREAN_FONT_MAGIC = b"SCVMSJIS"
KOREAN_FONT_VERSION = 3
KOREAN_GLYPH_COUNT = 11184
ASCII_GLYPH_COUNT = 256
SOURCE_INTRO_SCRIPT_SHA256 = "2F5EE82BF8DE9D1D54930AD57EF2F4AD1A1B213E460652B2866643FED39994CA"
SOURCE_INTRO_SCRIPT_SIZE = 1292
INTRO_BRANCH_OFFSET = 0x2A
INTRO_BRANCH_SOURCE = bytes.fromhex("306304")
INTRO_BRANCH_OUTPUT = bytes.fromhex("300000")
SCRIPT_PATCH_HEADER = bytes((0x82, 0x00))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def read_glyph_pattern(path: Path) -> tuple[list[str], bytes]:
    rows = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != 16 or any(len(row) != 16 for row in rows):
        raise ValueError("PoC glyph source must contain exactly sixteen 16-character rows")
    if any(character not in ".#" for row in rows for character in row):
        raise ValueError("PoC glyph source accepts only '.' and '#'")
    if not any("#" in row for row in rows):
        raise ValueError("PoC glyph is empty")

    encoded = bytearray()
    for row in rows:
        bits = int("".join("1" if pixel == "#" else "0" for pixel in row), 2)
        encoded.extend(bits.to_bytes(2, "big"))
    return rows, bytes(encoded)


def write_preview(rows: list[str], output: Path) -> None:
    image = Image.new("RGB", (16, 16), "white")
    pixels = image.load()
    for y, row in enumerate(rows):
        for x, pixel in enumerate(row):
            if pixel == "#":
                pixels[x, y] = (0, 0, 0)
    image.resize((256, 256), Image.Resampling.NEAREST).save(output)


def build_korean_font(glyph: bytes) -> bytes:
    if len(glyph) != 32:
        raise ValueError("A 16x16 1bpp glyph must be exactly 32 bytes")
    header = KOREAN_FONT_MAGIC + struct.pack(">IHHH", KOREAN_FONT_VERSION, KOREAN_GLYPH_COUNT, ASCII_GLYPH_COUNT, 0)
    korean_table = glyph + bytes((KOREAN_GLYPH_COUNT - 1) * 32)
    # ScummVM stores each 8x16 row byte in the first byte of a two-byte cell.
    ascii_table = bytes(ASCII_GLYPH_COUNT * 32)
    font = header + korean_table + ascii_table
    expected_size = 18 + KOREAN_GLYPH_COUNT * 32 + ASCII_GLYPH_COUNT * 32
    if len(font) != expected_size:
        raise AssertionError(f"Unexpected korean.fnt size: {len(font)} != {expected_size}")
    return font


def hardlink_game_tree(source: Path, destination: Path, omit_sfx: bool = False) -> tuple[int, int]:
    file_count = 0
    total_bytes = 0
    for source_path in sorted(source.rglob("*")):
        relative = source_path.relative_to(source)
        destination_path = destination / relative
        if source_path.is_dir():
            destination_path.mkdir(parents=True, exist_ok=True)
            continue
        if omit_sfx and relative.as_posix().lower() == "resource.sfx":
            continue
        if not source_path.is_file():
            raise ValueError(f"Unsupported source entry: {source_path}")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        os.link(source_path, destination_path)
        file_count += 1
        total_bytes += source_path.stat().st_size
    return file_count, total_bytes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Shivers1 project root",
    )
    parser.add_argument("--build-id", default=BUILD_ID)
    parser.add_argument(
        "--poc-target",
        choices=("intro-dialogue", "earliest-name"),
        default="intro-dialogue",
    )
    parser.add_argument(
        "--omit-sfx",
        action="store_true",
        help="Omit RESOURCE.SFX so text fallback paths can be tested without speech data",
    )
    parser.add_argument(
        "--force-intro-subtitles",
        action="store_true",
        help="Add a script 930 patch that always enters the timed intro subtitle branch",
    )
    args = parser.parse_args()

    project = args.project.resolve()
    source_root = project / "extracted" / "installer"
    source_iso = project / "original" / "installer" / "SHIVCD.iso"
    source_intro_script = project / "extracted" / "sci" / "script" / "00930.scr"
    if args.poc_target == "earliest-name":
        source_heap = project / "extracted" / "sci" / "heap" / "00922.hep"
        source_heap_hash_expected = NAME_HEAP_SHA256
        source_heap_size_expected = NAME_HEAP_SIZE
        target_heap_offset = NAME_HEAP_OFFSET
        expected_source = NAME_EXPECTED_SOURCE
        expected_output = NAME_EXPECTED_OUTPUT
        patch_name = "922.hep"
        expected_write_meaning = "Make the first name-entry A button append EUC-KR ga"
    else:
        source_heap = project / "extracted" / "sci" / "heap" / "00930.hep"
        source_heap_hash_expected = SOURCE_HEAP_SHA256
        source_heap_size_expected = SOURCE_HEAP_SIZE
        target_heap_offset = TARGET_HEAP_OFFSET
        expected_source = EXPECTED_SOURCE
        expected_output = EXPECTED_OUTPUT
        patch_name = "930.hep"
        expected_write_meaning = "Replace the first visible letters of heap 930 string 1 with EUC-KR ga"
    glyph_source = project / "workspace" / "fonts" / "poc_ga_16x16.txt"
    output_root = project / "build" / args.build_id

    if output_root.exists():
        raise FileExistsError(f"Refusing to replace existing build: {output_root}")
    if sha256_file(source_iso) != SOURCE_ISO_SHA256:
        raise ValueError("Source ISO SHA-256 does not match the supported revision")
    if source_heap.stat().st_size != source_heap_size_expected:
        raise ValueError("Target heap size does not match the supported revision")
    source_heap_hash = sha256_file(source_heap)
    if source_heap_hash != source_heap_hash_expected:
        raise ValueError("Target heap SHA-256 does not match the supported revision")
    if args.force_intro_subtitles:
        if (
            source_intro_script.stat().st_size != SOURCE_INTRO_SCRIPT_SIZE
            or sha256_file(source_intro_script) != SOURCE_INTRO_SCRIPT_SHA256
        ):
            raise ValueError("Source intro script identity mismatch")
        source_intro_script_data = source_intro_script.read_bytes()
        actual_intro_branch = source_intro_script_data[
            INTRO_BRANCH_OFFSET : INTRO_BRANCH_OFFSET + len(INTRO_BRANCH_SOURCE)
        ]
        if actual_intro_branch != INTRO_BRANCH_SOURCE:
            raise ValueError("Intro subtitle branch Expected Write mismatch")

    source_data = source_heap.read_bytes()
    actual_source = source_data[target_heap_offset : target_heap_offset + len(expected_source)]
    if actual_source != expected_source:
        raise ValueError(
            f"Expected Write mismatch at {source_heap.name} offset {target_heap_offset}: "
            f"{actual_source.hex().upper()} != {expected_source.hex().upper()}"
        )

    output_root.mkdir(parents=True)
    hardlinked_files, hardlinked_bytes = hardlink_game_tree(source_root, output_root, args.omit_sfx)

    rows, glyph = read_glyph_pattern(glyph_source)
    preview_path = output_root / "poc_ga_16x16_preview.png"
    write_preview(rows, preview_path)

    korean_font = build_korean_font(glyph)
    font_path = output_root / "korean.fnt"
    font_path.write_bytes(korean_font)

    patched_heap = bytearray(source_data)
    patched_heap[target_heap_offset : target_heap_offset + len(expected_output)] = expected_output
    changed_offsets = [index for index, (before, after) in enumerate(zip(source_data, patched_heap)) if before != after]
    expected_offsets = [
        target_heap_offset + index
        for index, pair in enumerate(zip(expected_source, expected_output))
        if pair[0] != pair[1]
    ]
    if changed_offsets != expected_offsets:
        raise AssertionError(f"Unexpected heap diff offsets: {changed_offsets}")
    patch_path = output_root / patch_name
    patch_path.write_bytes(PATCH_HEADER + patched_heap)

    if patch_path.read_bytes()[:2] != PATCH_HEADER:
        raise AssertionError("SCI patch header verification failed")
    if patch_path.read_bytes()[2:] != patched_heap:
        raise AssertionError("SCI patch payload verification failed")
    if patched_heap[target_heap_offset : target_heap_offset + len(expected_output)] != expected_output:
        raise AssertionError("Korean code verification failed")
    if len(patched_heap) != len(source_data):
        raise AssertionError("Heap length changed")

    intro_script_patch = None
    intro_script_changed_offsets: list[int] = []
    if args.force_intro_subtitles:
        patched_intro_script = bytearray(source_intro_script_data)
        patched_intro_script[
            INTRO_BRANCH_OFFSET : INTRO_BRANCH_OFFSET + len(INTRO_BRANCH_OUTPUT)
        ] = INTRO_BRANCH_OUTPUT
        intro_script_changed_offsets = [
            index
            for index, pair in enumerate(zip(source_intro_script_data, patched_intro_script))
            if pair[0] != pair[1]
        ]
        if intro_script_changed_offsets != [INTRO_BRANCH_OFFSET + 1, INTRO_BRANCH_OFFSET + 2]:
            raise AssertionError(f"Unexpected intro script diff offsets: {intro_script_changed_offsets}")
        intro_script_patch = output_root / "930.scr"
        intro_script_patch.write_bytes(SCRIPT_PATCH_HEADER + patched_intro_script)
        if intro_script_patch.read_bytes()[2:] != patched_intro_script:
            raise AssertionError("Intro script patch round-trip failed")

    manifest = {
        "schema_version": 1,
        "build_id": args.build_id,
        "scope": "ScummVM-only Korean visibility PoC",
        "runtime_variant": "text fallback without RESOURCE.SFX" if args.omit_sfx else "complete installed data",
        "source": {
            "iso_sha256": SOURCE_ISO_SHA256,
            "target_heap_path": str(source_heap.relative_to(project)).replace("\\", "/"),
            "target_heap_size": len(source_data),
            "target_heap_sha256": source_heap_hash,
        },
        "expected_write": {
            "owner": "POC-VIS-001",
            "meaning": expected_write_meaning,
            "heap_offset": target_heap_offset,
            "expected_source_hex": expected_source.hex().upper(),
            "output_hex": expected_output.hex().upper(),
            "changed_offsets": changed_offsets,
        },
        "intro_subtitle_branch": {
            "enabled": args.force_intro_subtitles,
            "script_number": 930 if args.force_intro_subtitles else None,
            "script_offset": INTRO_BRANCH_OFFSET if args.force_intro_subtitles else None,
            "expected_source_hex": INTRO_BRANCH_SOURCE.hex().upper() if args.force_intro_subtitles else None,
            "output_hex": INTRO_BRANCH_OUTPUT.hex().upper() if args.force_intro_subtitles else None,
            "changed_offsets": intro_script_changed_offsets,
        },
        "font": {
            "format": "ScummVM Korean FNT v3",
            "encoding": "EUC-KR/CP949",
            "test_character": "가",
            "test_code_hex": EXPECTED_OUTPUT.hex().upper(),
            "glyph_source": str(glyph_source.relative_to(project)).replace("\\", "/"),
            "glyph_source_sha256": sha256_file(glyph_source),
            "glyph_bitmap_sha256": sha256_bytes(glyph),
            "korean_glyph_count": KOREAN_GLYPH_COUNT,
            "ascii_glyph_count": ASCII_GLYPH_COUNT,
            "ascii_policy": "blank in visibility PoC",
        },
        "output": {
            "hardlinked_source_files": hardlinked_files,
            "hardlinked_source_bytes": hardlinked_bytes,
            "resource_sfx_included": not args.omit_sfx,
            "patch_path": patch_path.name,
            "patch_size": patch_path.stat().st_size,
            "patch_sha256": sha256_file(patch_path),
            "font_path": font_path.name,
            "font_size": font_path.stat().st_size,
            "font_sha256": sha256_file(font_path),
            "preview_path": preview_path.name,
            "preview_sha256": sha256_file(preview_path),
            "script_patch_path": intro_script_patch.name if intro_script_patch else None,
            "script_patch_sha256": sha256_file(intro_script_patch) if intro_script_patch else None,
        },
        "proved_by_build": [
            "supported source identity",
            "two-byte Expected Write only",
            "unchanged heap length and NUL layout",
            "valid ScummVM Korean FNT v3 container size",
            "forced intro subtitle script branch" if args.force_intro_subtitles else "original intro branch preserved",
        ],
        "not_proved_by_build": [
            "ScummVM selects Korean language and font 1001",
            "patch resource 930 is consumed at runtime",
            "the Korean glyph is visible or readable in game",
            "original SIERRAW.EXE compatibility",
        ],
    }
    manifest_path = output_root / "poc_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"build_id={args.build_id}")
    print(f"output={output_root}")
    print(f"hardlinked_files={hardlinked_files}")
    print(f"heap_diff_offsets={changed_offsets}")
    print(f"patch_sha256={manifest['output']['patch_sha256']}")
    print(f"font_sha256={manifest['output']['font_sha256']}")
    print("static_validation=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
