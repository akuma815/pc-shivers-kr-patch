#!/usr/bin/env python3
"""Freeze the reviewed manual pic working set and emit a deterministic build config."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path

from PIL import Image

from extract_sci21_graphics import decode_cel, iter_pic_cels


DEFAULT_QUEUE = "workspace/graphics/graphics_translation_queue_20260901.csv"
NORMALIZATION = (
    "Lanczos resize to the original cel dimensions, then nearest-color mapping "
    "to palette indices used by the original picture"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def append_note(current: str, addition: str) -> str:
    current = current.strip()
    return f"{current}; {addition}" if current else addition


def inspect_source(path: Path) -> tuple[tuple[int, int], dict[str, object]]:
    source = path.read_bytes()
    cels = list(iter_pic_cels(source))
    if len(cels) != 1 or cels[0][0] != 0:
        raise ValueError(f"Expected one loop-0 picture cel: {path}")
    cel_header = cels[0][1]
    source_pixels, info = decode_cel(source, cel_header)
    pixels_offset = struct.unpack_from("<I", source, cel_header + 24)[0]
    batch_supported = (
        int(info["compression"]) == 0
        and not bool(info["transparent"])
        and pixels_offset + len(source_pixels) == len(source)
    )
    return (int(info["width"]), int(info["height"])), {
        "compression": int(info["compression"]),
        "transparent": bool(info["transparent"]),
        "pixels_offset": pixels_offset,
        "resource_size": len(source),
        "batch_builder_supported": batch_supported,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path)
    parser.add_argument("--config-output", type=Path, required=True)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--completion-date", default="2026-09-03")
    args = parser.parse_args()

    project = Path(__file__).resolve().parents[2]
    queue_path = (args.queue or project / DEFAULT_QUEUE).resolve()
    config_output = args.config_output.resolve()
    backup_root = args.backup_root.resolve()
    if config_output.exists():
        raise FileExistsError(f"Refusing to replace config: {config_output}")
    if backup_root.exists():
        raise FileExistsError(f"Refusing to replace backup: {backup_root}")
    if project not in config_output.parents or project not in backup_root.parents:
        raise ValueError("Output paths must stay inside the project")

    with queue_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames
        rows = list(reader)
    if not fieldnames:
        raise ValueError("Queue has no header")
    pic_rows = [row for row in rows if row["type_name"] == "pic"]
    if len(pic_rows) != 178:
        raise ValueError(f"Expected 178 pic rows, got {len(pic_rows)}")
    numbers = [int(row["number"]) for row in pic_rows]
    if len(set(numbers)) != len(numbers):
        raise ValueError("Duplicate pic resource number")

    frozen: list[dict[str, object]] = []
    assets: list[dict[str, object]] = []
    aspect_mismatches: list[dict[str, object]] = []
    changed_numbers: list[int] = []
    unchanged_numbers: list[int] = []
    completion_note = (
        f"user reported manual pic review complete on {args.completion_date}; "
        "frozen for the all-pic build"
    )

    for row in pic_rows:
        number = int(row["number"])
        translation_path = project / "workspace/graphics/english_assets" / row["path"]
        source_path = project / f"workspace/graphics/english_assets/raw/pic/{number:05d}.p56"
        if not translation_path.is_file() or not source_path.is_file():
            raise FileNotFoundError(f"Missing pic input {number}: {translation_path} / {source_path}")
        translation_hash = sha256(translation_path)
        source_hash = sha256(source_path)
        source_dimensions, source_info = inspect_source(source_path)
        with Image.open(translation_path) as image:
            translation_dimensions = image.size
            image.verify()
        changed = translation_hash != row["original_sha256"].upper()
        if changed and not bool(source_info["batch_builder_supported"]):
            raise ValueError(f"Translated picture is unsupported by the batch builder: {source_path}")
        row["current_sha256"] = translation_hash
        if changed:
            changed_numbers.append(number)
            row["status"] = f"translated_working_manual_complete_{args.completion_date.replace('-', '')}"
            assets.append(
                {
                    "resource_number": number,
                    "source_path": source_path.relative_to(project).as_posix(),
                    "source_sha256": source_hash,
                    "source_dimensions": list(source_dimensions),
                    "translation_path": translation_path.relative_to(project).as_posix(),
                    "translation_sha256": translation_hash,
                    "translation_dimensions": list(translation_dimensions),
                }
            )
        else:
            unchanged_numbers.append(number)
            if row["status"] != "excluded_proper_name_logo":
                row["status"] = f"manual_review_complete_unchanged_{args.completion_date.replace('-', '')}"
        row["note"] = append_note(row.get("note", ""), completion_note)
        if abs(
            translation_dimensions[0] / translation_dimensions[1]
            - source_dimensions[0] / source_dimensions[1]
        ) > 0.001:
            aspect_mismatches.append(
                {
                    "resource_number": number,
                    "translation_dimensions": list(translation_dimensions),
                    "source_dimensions": list(source_dimensions),
                }
            )
        frozen.append(
            {
                "resource_number": number,
                "queue_path": row["path"],
                "translation_sha256": translation_hash,
                "original_png_sha256": row["original_sha256"].upper(),
                "changed_from_original_png": changed,
                "translation_dimensions": list(translation_dimensions),
                "source_path": source_path.relative_to(project).as_posix(),
                "source_sha256": source_hash,
                "source_dimensions": list(source_dimensions),
                **source_info,
            }
        )

    if len(assets) != 142:
        raise ValueError(f"Expected 142 changed manual pic inputs, got {len(assets)}")

    backup_png_root = backup_root / "png/pic"
    for row in pic_rows:
        source = project / "workspace/graphics/english_assets" / row["path"]
        destination = backup_root / row["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if sha256(destination) != sha256(source):
            raise AssertionError(f"Backup readback mismatch: {source}")

    shutil.copy2(queue_path, backup_root / queue_path.name)
    config_output.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "schema_version": 1,
        "scope": f"All {len(assets)} manually translated Shivers SCI picture assets frozen on {args.completion_date}",
        "status": "user_reported_manual_complete_build_input",
        "normalization": NORMALIZATION,
        "expected_resource_numbers": changed_numbers,
        "reviewed_unchanged_resource_numbers": unchanged_numbers,
        "assets": assets,
    }
    config_output.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    temporary_queue = queue_path.with_suffix(queue_path.suffix + ".tmp")
    with temporary_queue.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
    temporary_queue.replace(queue_path)

    report = {
        "schema_version": 1,
        "completion_date": args.completion_date,
        "queue_path": queue_path.relative_to(project).as_posix(),
        "queue_sha256_after_sync": sha256(queue_path),
        "queue_backup_path": (backup_root / queue_path.name).relative_to(project).as_posix(),
        "queue_backup_sha256": sha256(backup_root / queue_path.name),
        "config_path": config_output.relative_to(project).as_posix(),
        "config_sha256": sha256(config_output),
        "reviewed_pic_count": len(pic_rows),
        "translated_pic_count": len(assets),
        "reviewed_unchanged_pic_count": len(unchanged_numbers),
        "aspect_mismatch_count": len(aspect_mismatches),
        "aspect_mismatches": aspect_mismatches,
        "files": frozen,
    }
    report_path = backup_root / "manual_pic_snapshot_manifest.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"backup={backup_root}")
    print(f"config={config_output}")
    print(f"reviewed_pictures={len(pic_rows)}")
    print(f"translated_pictures={len(assets)}")
    print(f"reviewed_unchanged={len(unchanged_numbers)}")
    print(f"aspect_mismatches={len(aspect_mismatches)}")
    print(f"queue_sha256={sha256(queue_path)}")
    print(f"config_sha256={sha256(config_output)}")
    print(f"snapshot_manifest_sha256={sha256(report_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
