#!/usr/bin/env python3
"""Build the reversible Shivers audio-only subtitle PoC game directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


DEFAULT_CONFIG = "workspace/scummvm_audio_subtitles/poc_015.json"
EXPECTED_FONT_SHA256 = "5BA2D547AB9A63A6997BE5280821610C0C4FE9AE0B9B0C7CF40F03AF6D7034EB"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def hardlink_tree(source: Path, destination: Path) -> tuple[int, int]:
    count = 0
    total = 0
    for source_path in sorted(source.rglob("*")):
        relative = source_path.relative_to(source)
        destination_path = destination / relative
        if source_path.is_dir():
            destination_path.mkdir(parents=True, exist_ok=True)
        elif source_path.is_file():
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            os.link(source_path, destination_path)
            count += 1
            total += source_path.stat().st_size
        else:
            raise ValueError(f"Unsupported source entry: {source_path}")
    return count, total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path)
    parser.add_argument("--build-id")
    parser.add_argument("--allow-poc", action="store_true")
    args = parser.parse_args()
    if not args.allow_poc:
        raise ValueError("This is a test-only PoC; pass --allow-poc explicitly")

    project = Path(__file__).resolve().parents[2]
    config_path = args.config.resolve() if args.config else project / DEFAULT_CONFIG
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("schema_version") != 1:
        raise ValueError("Unsupported audio subtitle config schema")

    build_id = str(args.build_id or config["build_id"])
    base_build = project / str(config["base_build"])
    output_root = project / "build" / build_id
    if output_root.exists():
        raise FileExistsError(f"Refusing to replace existing build: {output_root}")
    if not base_build.is_dir():
        raise FileNotFoundError(f"Base build not found: {base_build}")

    base_manifest_path = base_build / "poc_manifest.json"
    base_manifest = json.loads(base_manifest_path.read_text(encoding="utf-8"))
    if base_manifest.get("build_id") != base_build.name:
        raise ValueError("Base build manifest identity mismatch")
    font_path = base_build / "korean.fnt"
    if sha256(font_path) != EXPECTED_FONT_SHA256:
        raise ValueError("Korean font identity mismatch")

    entries = config.get("audio_subtitles")
    if not isinstance(entries, list) or len(entries) != 1:
        raise ValueError("PoC 015 must contain exactly one audio subtitle")
    entry = entries[0]
    if int(entry["resource_id"]) != 35036 or int(entry["duration_ms"]) != 3427:
        raise ValueError("PoC target identity mismatch")
    korean = str(entry["korean"])
    encoded_korean = korean.encode("cp949")

    output_root.mkdir(parents=True)
    linked_files, linked_bytes = hardlink_tree(base_build, output_root)

    # Break the manifest hardlink before writing build-specific metadata.
    output_manifest_path = output_root / "poc_manifest.json"
    output_manifest_path.unlink()

    subtitle_path = output_root / "audio_subtitles_ko.csv"
    subtitle_bytes = (
        b"# resource_id,duration_ms,text_cp949\r\n"
        + f"{int(entry['resource_id'])},{int(entry['duration_ms'])},".encode("ascii")
        + encoded_korean
        + b"\r\n"
    )
    subtitle_path.write_bytes(subtitle_bytes)
    if subtitle_path.read_bytes() != subtitle_bytes:
        raise AssertionError("Audio subtitle CP949 round-trip failed")
    if encoded_korean.decode("cp949") != korean:
        raise AssertionError("Audio subtitle text round-trip failed")

    marker_path = output_root / str(config["test_gate"]["marker"])
    marker_path.write_text(
        "TEST ONLY: force the random name-entry voice to resource 35036 for repeatable runtime QA.\n",
        encoding="ascii",
    )

    patch_path = project / "workspace/scummvm_audio_subtitles/scummvm_v2026.3.0_shivers_audio_subtitles.patch"
    manifest = {
        "schema_version": 1,
        "build_id": build_id,
        "scope": "ScummVM-only audio subtitle PoC for name-entry resource 35036",
        "base_build": {
            "path": base_build.relative_to(project).as_posix(),
            "manifest_sha256": sha256(base_manifest_path),
            "hardlinked_files": linked_files,
            "hardlinked_bytes": linked_bytes,
        },
        "runtime": {
            "scummvm_source_tag": config["scummvm_source_tag"],
            "scummvm_source_commit": config["scummvm_source_commit"],
            "source_patch": patch_path.relative_to(project).as_posix(),
            "source_patch_sha256": sha256(patch_path),
        },
        "audio_subtitles": [
            {
                "resource_id": int(entry["resource_id"]),
                "duration_ms": int(entry["duration_ms"]),
                "english": str(entry["english"]),
                "korean": korean,
                "encoding": "cp949",
            }
        ],
        "test_gate": config["test_gate"],
        "output": {
            "config_sha256": sha256(config_path),
            "font_sha256": sha256(output_root / "korean.fnt"),
            "audio_subtitles_sha256": sha256(subtitle_path),
            "force_marker_sha256": sha256(marker_path),
        },
        "static_validation": {
            "cp949_round_trip": "PASS",
            "font_identity": "PASS",
            "base_manifest_identity": "PASS",
        },
        "not_proved_by_build": [
            "subtitle is visible while resource 35036 plays",
            "subtitle clears after the voice ends",
            "name-entry controls remain usable",
            "full-game audio subtitle coverage",
        ],
    }
    output_manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"output={output_root}")
    print(f"subtitle_resource={entry['resource_id']}")
    print(f"subtitle_duration_ms={entry['duration_ms']}")
    print("static_validation=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
