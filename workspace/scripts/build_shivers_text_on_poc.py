#!/usr/bin/env python3
"""Build a reversible Shivers PoC with CD Text enabled before the intro."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


BUILD_ID = "shivers_text_on_poc_001"
SOURCE_ISO_SHA256 = "62E7E35D288D7C4ACB3A04CDE1CC9865D3B24E8EB40F8CB32D86DC00B28A80C9"
SOURCE_HEAP_SHA256 = "5951C75C10A95E3E936D44A24570BC41651016071386AA31B7A5C98007B2A707"
SOURCE_HEAP_SIZE = 2668
GLOBAL_INDEX = 211
LOCALS_BASE = 4
TARGET_OFFSET = LOCALS_BASE + GLOBAL_INDEX * 2
EXPECTED_SOURCE = bytes.fromhex("0000")
EXPECTED_OUTPUT = bytes.fromhex("0001")  # little-endian 0x0100
PATCH_HEADER = bytes.fromhex("9100")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def hardlink_tree(source: Path, destination: Path) -> tuple[int, int]:
    file_count = 0
    total_bytes = 0
    for source_path in sorted(source.rglob("*")):
        relative = source_path.relative_to(source)
        destination_path = destination / relative
        if source_path.is_dir():
            destination_path.mkdir(parents=True, exist_ok=True)
            continue
        if not source_path.is_file():
            raise ValueError(f"Unsupported source entry: {source_path}")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        os.link(source_path, destination_path)
        file_count += 1
        total_bytes += source_path.stat().st_size
    return file_count, total_bytes


def main() -> int:
    project = Path(__file__).resolve().parents[2]
    source_root = project / "extracted" / "installer"
    source_iso = project / "original" / "installer" / "SHIVCD.iso"
    source_heap = project / "extracted" / "sci" / "heap" / "00000.hep"
    output_root = project / "build" / BUILD_ID

    if output_root.exists():
        raise FileExistsError(f"Refusing to replace existing build: {output_root}")
    if sha256(source_iso) != SOURCE_ISO_SHA256:
        raise ValueError("Source ISO SHA-256 does not match the supported revision")
    if source_heap.stat().st_size != SOURCE_HEAP_SIZE or sha256(source_heap) != SOURCE_HEAP_SHA256:
        raise ValueError("Source heap 0 does not match the supported revision")

    source_data = source_heap.read_bytes()
    if source_data[TARGET_OFFSET : TARGET_OFFSET + 2] != EXPECTED_SOURCE:
        raise ValueError("Expected Write mismatch for Shivers global 211")

    output_root.mkdir(parents=True)
    linked_files, linked_bytes = hardlink_tree(source_root, output_root)

    patched = bytearray(source_data)
    patched[TARGET_OFFSET : TARGET_OFFSET + 2] = EXPECTED_OUTPUT
    changed_offsets = [i for i, pair in enumerate(zip(source_data, patched)) if pair[0] != pair[1]]
    if changed_offsets != [TARGET_OFFSET + 1]:
        raise AssertionError(f"Unexpected heap diff offsets: {changed_offsets}")

    patch_path = output_root / "0.hep"
    patch_path.write_bytes(PATCH_HEADER + patched)
    if patch_path.read_bytes()[2 + TARGET_OFFSET : 2 + TARGET_OFFSET + 2] != EXPECTED_OUTPUT:
        raise AssertionError("Patched global 211 readback failed")

    manifest = {
        "schema_version": 1,
        "build_id": BUILD_ID,
        "scope": "ScummVM-only forced CD Text startup PoC",
        "source": {
            "iso_sha256": SOURCE_ISO_SHA256,
            "heap_path": "extracted/sci/heap/00000.hep",
            "heap_size": SOURCE_HEAP_SIZE,
            "heap_sha256": SOURCE_HEAP_SHA256,
        },
        "expected_write": {
            "owner": "POC-TEXT-ON-001",
            "global_index": GLOBAL_INDEX,
            "heap_offset": TARGET_OFFSET,
            "meaning": "Set Shivers CD Text flag 0x0100 before script 930 intro playback",
            "expected_source_hex": EXPECTED_SOURCE.hex().upper(),
            "output_hex": EXPECTED_OUTPUT.hex().upper(),
            "changed_offsets": changed_offsets,
        },
        "output": {
            "hardlinked_source_files": linked_files,
            "hardlinked_source_bytes": linked_bytes,
            "patch_path": patch_path.name,
            "patch_size": patch_path.stat().st_size,
            "patch_sha256": sha256(patch_path),
        },
        "not_proved_by_build": [
            "runtime subtitle rendering in intro movie 1002",
            "original SIERRAW.EXE compatibility",
        ],
    }
    manifest_path = output_root / "text_on_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
