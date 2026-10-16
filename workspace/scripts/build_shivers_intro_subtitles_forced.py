#!/usr/bin/env python3
"""Build an isolated ScummVM PoC that forces Shivers intro subtitles."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


BUILD_ID = "shivers_intro_subtitles_forced_001"
SOURCE_ISO_SHA256 = "62E7E35D288D7C4ACB3A04CDE1CC9865D3B24E8EB40F8CB32D86DC00B28A80C9"
SOURCE_SCRIPT_SHA256 = "2F5EE82BF8DE9D1D54930AD57EF2F4AD1A1B213E460652B2866643FED39994CA"
SOURCE_SCRIPT_SIZE = 1292
TARGET_OFFSET = 0x2A
EXPECTED_SOURCE = bytes.fromhex("306304")  # bnt +0x0463: jump to plain playVMD path
EXPECTED_OUTPUT = bytes.fromhex("300000")  # bnt +0: both outcomes continue to subtitles
PATCH_HEADER = bytes.fromhex("8200")       # SCI script resource, no extra header


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
    source_script = project / "extracted" / "sci" / "script" / "00930.scr"
    output_root = project / "build" / BUILD_ID

    if output_root.exists():
        raise FileExistsError(f"Refusing to replace existing build: {output_root}")
    if sha256(source_iso) != SOURCE_ISO_SHA256:
        raise ValueError("Source ISO SHA-256 does not match the supported revision")
    if (
        source_script.stat().st_size != SOURCE_SCRIPT_SIZE
        or sha256(source_script) != SOURCE_SCRIPT_SHA256
    ):
        raise ValueError("Source script 930 does not match the supported revision")

    source_data = source_script.read_bytes()
    if source_data[TARGET_OFFSET : TARGET_OFFSET + 3] != EXPECTED_SOURCE:
        raise ValueError("Expected intro branch bytes are not present")

    output_root.mkdir(parents=True)
    linked_files, linked_bytes = hardlink_tree(source_root, output_root)

    patched = bytearray(source_data)
    patched[TARGET_OFFSET : TARGET_OFFSET + 3] = EXPECTED_OUTPUT
    changed_offsets = [i for i, pair in enumerate(zip(source_data, patched)) if pair[0] != pair[1]]
    expected_changed_offsets = [TARGET_OFFSET + 1, TARGET_OFFSET + 2]
    if changed_offsets != expected_changed_offsets:
        raise AssertionError(f"Unexpected script diff offsets: {changed_offsets}")

    patch_path = output_root / "930.scr"
    patch_path.write_bytes(PATCH_HEADER + patched)
    readback = patch_path.read_bytes()[2 + TARGET_OFFSET : 2 + TARGET_OFFSET + 3]
    if readback != EXPECTED_OUTPUT:
        raise AssertionError("Patched intro branch readback failed")

    manifest = {
        "schema_version": 1,
        "build_id": BUILD_ID,
        "scope": "ScummVM-only forced intro subtitle branch PoC",
        "source": {
            "iso_sha256": SOURCE_ISO_SHA256,
            "script_path": "extracted/sci/script/00930.scr",
            "script_size": SOURCE_SCRIPT_SIZE,
            "script_sha256": SOURCE_SCRIPT_SHA256,
        },
        "expected_write": {
            "owner": "POC-INTRO-SUBS-001",
            "script_number": 930,
            "script_offset": TARGET_OFFSET,
            "meaning": "Keep introMovie:init on its timed subtitle branch regardless of IsFlag(39)",
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
    manifest_path = output_root / "intro_subtitles_forced_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
