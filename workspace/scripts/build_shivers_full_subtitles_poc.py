#!/usr/bin/env python3
"""Build the Shivers 1 full Korean subtitle and manual-picture runtime tree."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import shutil
import struct
import sys
from collections import defaultdict
from pathlib import Path


DEFAULT_BUILD_ID = "scummvm_ko_poc_017_full_subtitles_pic_20260903"
DEFAULT_BASE_BUILD = "build/scummvm_ko_poc_016_pic_all_manual_20260903"
DEFAULT_MOVIE_CSV = "workspace/translation/shivers_1_movie_subtitles_ko.csv"
DEFAULT_AUDIO_CSV = "workspace/translation/shivers_1_audio_narration_ko_translated.csv"
DEFAULT_AUDIO_BASE_CSV = "workspace/translation/shivers_1_audio_narration_ko.csv"
DEFAULT_TTF = Path(r"C:\Windows\Fonts\malgun.ttf")
DEFAULT_RUNTIME_PATCH = "workspace/scummvm_audio_subtitles/scummvm_v2026.3.0_shivers_full_subtitles.patch"
EXPECTED_FONT_SHA256 = "5BA2D547AB9A63A6997BE5280821610C0C4FE9AE0B9B0C7CF40F03AF6D7034EB"
EXCLUDED_AUDIO_IDS = {"32401"}
TIMING_OVERRIDES = {"V39260_018": 360}
SKIP_FROM_BASE = {
    "930.hep",
    "930.scr",
    "intro_korean_font_preview.png",
    "poc_manifest.json",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def hardlink_runtime_tree(source: Path, destination: Path) -> tuple[int, int, list[str]]:
    count = 0
    total = 0
    skipped: list[str] = []
    for source_path in sorted(source.rglob("*")):
        relative = source_path.relative_to(source)
        relative_posix = relative.as_posix()
        if relative.parts and relative.parts[0] == "graphics_previews":
            if source_path.is_file():
                skipped.append(relative_posix)
            continue
        if relative_posix in SKIP_FROM_BASE:
            skipped.append(relative_posix)
            continue
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
    return count, total, skipped


def load_movie_module(project: Path):
    path = project / "workspace/scripts/export_movie_subtitles_csv.py"
    spec = importlib.util.spec_from_file_location("shivers_movie_csv", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load movie CSV verifier")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def srt_time(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def read_vmd_timing(path: Path) -> dict[str, object]:
    header = path.read_bytes()[:820]
    header_length, _handle, _version, frame_count = struct.unpack_from("<HHHH", header, 0)
    sound_offset = 28 + (768 if header_length == 814 else 0) + 8
    sound_freq, sound_slice_size, _slice_count, sound_flags = struct.unpack_from("<HhhH", header, sound_offset)
    stereo = 1 if sound_flags & 0x8000 else (2 if sound_flags & 0x200 else 0)
    divisor = abs(sound_slice_size) // (2 if stereo == 1 else 1)
    if sound_freq == 0 or divisor == 0 or sound_freq % divisor != 0:
        raise ValueError(f"Non-integral or missing VMD frame rate: {path}")
    fps = sound_freq // divisor
    return {
        "frame_count": frame_count,
        "fps": fps,
        "sound_frequency": sound_freq,
        "sound_slice_size": sound_slice_size,
        "sha256": sha256(path),
    }


def build_movie_srts(project: Path, output_root: Path, movie_csv: Path) -> tuple[list[dict], int]:
    module = load_movie_module(project)
    expected = module.build_rows(project)
    rows = module.read_csv(movie_csv)
    module.validate_rows(rows, expected)
    caption_rows = [row for row in rows if row["row_type"] == "caption"]
    if len(rows) != 118 or len(caption_rows) != 117:
        raise ValueError("Movie subtitle population mismatch")
    if any(not row["translation_ko"].strip() for row in caption_rows):
        missing = [row["record_id"] for row in caption_rows if not row["translation_ko"].strip()]
        raise ValueError(f"Missing movie translations: {missing}")

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in caption_rows:
        grouped[row["movie_id"]].append(row)

    reports: list[dict] = []
    for movie_id in sorted(grouped, key=int):
        movie_path = output_root / "MOVIES" / f"{movie_id}.VMD"
        timing = read_vmd_timing(movie_path)
        if timing["fps"] != 10:
            raise ValueError(f"Unexpected frame rate for movie {movie_id}: {timing['fps']}")
        entries: list[str] = []
        normalized: list[dict] = []
        blank_line_normalizations: list[dict] = []
        movie_rows = grouped[movie_id]
        normalized_starts = [
            TIMING_OVERRIDES.get(row["record_id"], int(row["start_frame"]))
            for row in movie_rows
        ]
        for index, row in enumerate(movie_rows, start=1):
            source_start = int(row["start_frame"])
            start_frame = normalized_starts[index - 1]
            source_end = int(row["end_frame"])
            end_frame = normalized_starts[index] if index < len(movie_rows) else source_end
            end_frame = min(end_frame, int(timing["frame_count"]))
            if not (0 <= start_frame < end_frame <= int(timing["frame_count"])):
                raise ValueError(
                    f"Invalid normalized timing for {row['record_id']}: {start_frame}..{end_frame}"
                )
            start_ms = start_frame * 100
            end_ms = end_frame * 100
            source_text = row["translation_ko"].replace("\r\n", "\n").replace("\r", "\n").strip()
            source_lines = source_text.split("\n")
            text_lines = [line for line in source_lines if line.strip()]
            text = "\n".join(text_lines)
            removed_blank_lines = len(source_lines) - len(text_lines)
            if removed_blank_lines:
                blank_line_normalizations.append(
                    {"record_id": row["record_id"], "removed_blank_lines": removed_blank_lines}
                )
            entries.append(
                f"{index}\n{srt_time(start_ms)} --> {srt_time(end_ms)}\n{text}\n"
            )
            normalized.append(
                {
                    "record_id": row["record_id"],
                    "source_start_frame": source_start,
                    "start_frame": start_frame,
                    "source_end_frame": source_end,
                    "end_frame": end_frame,
                }
            )
        srt_path = output_root / "MOVIES" / f"{movie_id}.VMD.srt"
        srt_path.write_text("\ufeff" + "\n".join(entries), encoding="utf-8")
        reports.append(
            {
                "movie_id": int(movie_id),
                "movie_path": movie_path.relative_to(output_root).as_posix(),
                "movie_sha256": timing["sha256"],
                "frame_count": timing["frame_count"],
                "fps": timing["fps"],
                "subtitle_entries": len(entries),
                "srt_path": srt_path.relative_to(output_root).as_posix(),
                "srt_sha256": sha256(srt_path),
                "timing_overrides": [
                    item
                    for item in normalized
                    if item["source_start_frame"] != item["start_frame"]
                    or item["source_end_frame"] != item["end_frame"]
                ],
                "blank_line_normalizations": blank_line_normalizations,
            }
        )
    if len(reports) != 6:
        raise ValueError("Expected six movie SRT files")
    return reports, len(caption_rows)


def read_dict_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), list(reader)


def build_audio_table(output_root: Path, translated_csv: Path, baseline_csv: Path) -> tuple[list[dict], list[str]]:
    fields, rows = read_dict_csv(translated_csv)
    baseline_fields, baseline_rows = read_dict_csv(baseline_csv)
    if fields != baseline_fields or len(rows) != 87 or len(baseline_rows) != 87:
        raise ValueError("Audio CSV header or population mismatch")
    editable = {"korean_translation", "korean_wav", "status", "notes"}
    protected = [field for field in fields if field not in editable]
    for row, baseline in zip(rows, baseline_rows):
        if any(row[field] != baseline[field] for field in protected):
            raise ValueError(f"Protected audio field changed for {row['audio_id']}")

    excluded: list[str] = []
    runtime_rows: list[dict] = []
    output_lines = [b"# resource_id,duration_ms,text_cp949\r\n"]
    for row in rows:
        audio_id = row["audio_id"]
        text = row["korean_translation"].strip()
        if not text:
            excluded.append(audio_id)
            continue
        if audio_id in EXCLUDED_AUDIO_IDS:
            raise ValueError(f"Excluded effect unexpectedly has translation: {audio_id}")
        normalized_text = " ".join(text.replace("\r", "\n").splitlines())
        encoded = normalized_text.encode("cp949")
        if encoded.decode("cp949") != normalized_text:
            raise AssertionError(f"CP949 round-trip failed: {audio_id}")
        duration_ms = round(float(row["duration_seconds"]) * 1000)
        output_lines.append(f"{int(audio_id)},{duration_ms},".encode("ascii") + encoded + b"\r\n")
        runtime_rows.append(
            {
                "audio_id": int(audio_id),
                "duration_ms": duration_ms,
                "category": row["category"],
                "translation_scope": row["translation_scope"],
                "text_sha256": hashlib.sha256(encoded).hexdigest().upper(),
            }
        )
    if set(excluded) != EXCLUDED_AUDIO_IDS or len(runtime_rows) != 86:
        raise ValueError(f"Audio subtitle coverage mismatch: included={len(runtime_rows)}, excluded={excluded}")
    subtitle_path = output_root / "audio_subtitles_ko.csv"
    subtitle_bytes = b"".join(output_lines)
    subtitle_path.write_bytes(subtitle_bytes)
    if subtitle_path.read_bytes() != subtitle_bytes:
        raise AssertionError("Audio subtitle table readback failed")
    return runtime_rows, excluded


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-id", default=DEFAULT_BUILD_ID)
    parser.add_argument("--base-build", default=DEFAULT_BASE_BUILD)
    parser.add_argument("--movie-csv", default=DEFAULT_MOVIE_CSV)
    parser.add_argument("--audio-csv", default=DEFAULT_AUDIO_CSV)
    parser.add_argument("--audio-base-csv", default=DEFAULT_AUDIO_BASE_CSV)
    parser.add_argument("--korean-ttf", type=Path, default=DEFAULT_TTF)
    parser.add_argument("--runtime-patch", default=DEFAULT_RUNTIME_PATCH)
    parser.add_argument("--allow-poc", action="store_true")
    args = parser.parse_args()
    if not args.allow_poc:
        raise ValueError("This ScummVM-specific build requires --allow-poc")

    project = Path(__file__).resolve().parents[2]
    base_build = project / args.base_build
    output_root = project / "build" / args.build_id
    movie_csv = project / args.movie_csv
    audio_csv = project / args.audio_csv
    audio_base_csv = project / args.audio_base_csv
    runtime_patch = project / args.runtime_patch
    korean_ttf = args.korean_ttf.resolve()
    if output_root.exists():
        raise FileExistsError(f"Refusing to replace existing build: {output_root}")
    for path in (base_build, movie_csv, audio_csv, audio_base_csv, runtime_patch, korean_ttf):
        if not path.exists():
            raise FileNotFoundError(path)

    base_manifest_path = base_build / "poc_manifest.json"
    base_manifest = json.loads(base_manifest_path.read_text(encoding="utf-8"))
    if base_manifest.get("build_id") != base_build.name:
        raise ValueError("Base build manifest identity mismatch")
    if int(base_manifest.get("graphics_batch", {}).get("resource_count", 0)) != 142:
        raise ValueError("Base build does not declare 142 manual picture patches")
    if sha256(base_build / "korean.fnt") != EXPECTED_FONT_SHA256:
        raise ValueError("Korean bitmap font identity mismatch")

    output_root.mkdir(parents=True)
    linked_files, linked_bytes, skipped = hardlink_runtime_tree(base_build, output_root)
    shutil.copy2(korean_ttf, output_root / "ShiversKorean.ttf")
    movie_reports, movie_entry_count = build_movie_srts(project, output_root, movie_csv)
    audio_rows, excluded_audio = build_audio_table(output_root, audio_csv, audio_base_csv)

    if (output_root / "930.hep").exists() or (output_root / "930.scr").exists():
        raise AssertionError("Legacy forced intro patches must not be present")
    if (output_root / "audio_subtitles_poc_force_35036.flag").exists():
        raise AssertionError("Test-only forced audio marker must not be present")

    manifest = {
        "schema_version": 1,
        "build_id": args.build_id,
        "scope": "142 manual picture patches plus all translated movie and standalone-audio Korean subtitles",
        "base_build": {
            "path": base_build.relative_to(project).as_posix(),
            "manifest_sha256": sha256(base_manifest_path),
            "hardlinked_files": linked_files,
            "hardlinked_bytes": linked_bytes,
            "omitted_nonruntime_or_legacy_files": sorted(skipped),
            "manual_picture_count": 142,
        },
        "movie_subtitles": {
            "source_csv": movie_csv.relative_to(project).as_posix(),
            "source_csv_sha256": sha256(movie_csv),
            "encoding": "UTF-8 with BOM",
            "movies": movie_reports,
            "translated_entries": movie_entry_count,
            "legacy_native_intro_patches_removed": ["930.hep", "930.scr"],
        },
        "audio_subtitles": {
            "source_csv": audio_csv.relative_to(project).as_posix(),
            "source_csv_sha256": sha256(audio_csv),
            "baseline_csv": audio_base_csv.relative_to(project).as_posix(),
            "baseline_csv_sha256": sha256(audio_base_csv),
            "encoding": "CP949",
            "included_count": len(audio_rows),
            "excluded_audio_ids": excluded_audio,
            "entries": audio_rows,
            "force_marker_present": False,
            "pagination": "wrapped lines, two lines per time-proportional page",
        },
        "runtime": {
            "scummvm_source_tag": "v2026.3.0",
            "scummvm_source_commit": "fed42f2068dcafc6aafa1c28c77e4c88def74b66",
            "source_patch": args.runtime_patch,
            "source_patch_sha256": sha256(runtime_patch),
            "movie_font": "ShiversKorean.ttf",
            "movie_font_source": str(korean_ttf),
            "movie_font_sha256": sha256(output_root / "ShiversKorean.ttf"),
            "audio_font": "korean.fnt",
            "audio_font_sha256": sha256(output_root / "korean.fnt"),
        },
        "output": {
            "audio_table_sha256": sha256(output_root / "audio_subtitles_ko.csv"),
            "srt_count": len(movie_reports),
        },
        "static_validation": {
            "movie_csv_protected_fields": "PASS",
            "movie_translation_coverage": "117/117 PASS",
            "vmd_timing": "6/6 at 10 fps PASS",
            "audio_csv_protected_fields": "PASS",
            "audio_translation_coverage": "86/86 translated voice rows PASS; effect 32401 intentionally excluded",
            "audio_cp949_round_trip": "PASS",
            "legacy_intro_duplicate_prevention": "PASS",
            "forced_audio_test_gate_absent": "PASS",
        },
        "not_proved_by_build": [
            "all 117 movie subtitles were visually inspected in their six playback contexts",
            "all 86 standalone-audio subtitles were triggered and visually inspected",
            "full-game controls and save compatibility remain unaffected",
        ],
    }
    manifest_path = output_root / "poc_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"output={output_root}")
    print(f"manual_pictures=142")
    print(f"movie_subtitles={movie_entry_count}")
    print(f"movie_srt_files={len(movie_reports)}")
    print(f"audio_subtitles={len(audio_rows)}")
    print(f"excluded_audio={','.join(excluded_audio)}")
    print("static_validation=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
