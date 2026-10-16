#!/usr/bin/env python3
"""Build an exact-version ScummVM runner that detects English Shivers as Korean."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


SOURCE_SHA256 = "28BEA3ACE3CB5D5EFA520824BD5EF48D4C1018079ABC928BA16A438CDB15B01E"
SOURCE_SIZE = 201266688
LANGUAGE_OFFSET = 0x53702D0
EXPECTED_LANGUAGE = 0x07  # Common::EN_ANY
OUTPUT_LANGUAGE = 0x16  # Common::KO_KOR
EXPECTED_RECORD_TAIL = bytes.fromhex("07140000000000087956334501000000")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> int:
    project = Path(__file__).resolve().parents[2]
    source = Path(r"H:\scummvm\scummvm.exe")
    output_root = project / "work" / "scummvm_poc_runner"
    output = output_root / "scummvm_shivers_ko_poc.exe"
    manifest_path = output_root / "runner_manifest.json"

    if output.exists() or manifest_path.exists():
        raise FileExistsError(f"Refusing to replace existing runner: {output_root}")
    if source.stat().st_size != SOURCE_SIZE:
        raise ValueError(f"Unexpected ScummVM size: {source.stat().st_size}")
    source_hash = sha256_file(source)
    if source_hash != SOURCE_SHA256:
        raise ValueError(f"Unexpected ScummVM SHA-256: {source_hash}")

    with source.open("rb") as stream:
        stream.seek(LANGUAGE_OFFSET)
        actual_tail = stream.read(len(EXPECTED_RECORD_TAIL))
    if actual_tail != EXPECTED_RECORD_TAIL:
        raise ValueError(
            f"Shivers detection record mismatch at 0x{LANGUAGE_OFFSET:X}: "
            f"{actual_tail.hex().upper()}"
        )

    output_root.mkdir(parents=True)
    shutil.copyfile(source, output)
    with output.open("r+b") as stream:
        stream.seek(LANGUAGE_OFFSET)
        actual = stream.read(1)
        if actual != bytes((EXPECTED_LANGUAGE,)):
            raise ValueError(f"Expected Write mismatch: {actual.hex().upper()}")
        stream.seek(LANGUAGE_OFFSET)
        stream.write(bytes((OUTPUT_LANGUAGE,)))

    changed = []
    with source.open("rb") as before, output.open("rb") as after:
        offset = 0
        while True:
            old = before.read(1024 * 1024)
            new = after.read(1024 * 1024)
            if not old and not new:
                break
            if len(old) != len(new):
                raise AssertionError("Runner size changed")
            changed.extend(offset + index for index, pair in enumerate(zip(old, new)) if pair[0] != pair[1])
            offset += len(old)
    if changed != [LANGUAGE_OFFSET]:
        raise AssertionError(f"Unexpected runner diff offsets: {changed}")

    manifest = {
        "schema_version": 1,
        "scope": "Exact ScummVM 2026.3.0 Shivers Korean-language detection PoC",
        "source": {
            "path": str(source),
            "size": SOURCE_SIZE,
            "sha256": SOURCE_SHA256,
        },
        "expected_write": {
            "owner": "POC-VIS-001",
            "file_offset": LANGUAGE_OFFSET,
            "file_offset_hex": f"0x{LANGUAGE_OFFSET:X}",
            "expected_source_hex": f"{EXPECTED_LANGUAGE:02X}",
            "output_hex": f"{OUTPUT_LANGUAGE:02X}",
            "meaning": "Shivers English detection language EN_ANY to KO_KOR",
            "changed_offsets": changed,
        },
        "output": {
            "path": str(output.relative_to(project)).replace("\\", "/"),
            "size": output.stat().st_size,
            "sha256": sha256_file(output),
        },
        "limitations": [
            "ScummVM 2026.3.0 exact binary only",
            "PE checksum is not recalculated",
            "PoC runner is not a release artifact",
            "Original H:/scummvm/scummvm.exe remains unchanged",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"output={output}")
    print(f"changed_offsets={changed}")
    print(f"sha256={manifest['output']['sha256']}")
    print("static_validation=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
