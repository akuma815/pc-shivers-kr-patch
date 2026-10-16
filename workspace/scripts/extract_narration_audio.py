#!/usr/bin/env python3
"""Extract Shivers global voice candidates from RESOURCE.SFX as PCM WAV files.

The English Windows 1.02 installer stores the global audio map as a patch file:
the first two bytes are the patch resource header, followed by late-SCI 1.1
five-byte cumulative map entries.  Shivers uses 3xxxx IDs for its voice-like
global-audio namespace.  The extractor keeps all 3xxxx resources for review and
adds conservative script-derived categories instead of claiming that every
sample is spoken dialogue.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
import struct
import sys
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path


DPCM16_TABLE = (
    0x0000, 0x0008, 0x0010, 0x0020, 0x0030, 0x0040, 0x0050, 0x0060,
    0x0070, 0x0080, 0x0090, 0x00A0, 0x00B0, 0x00C0, 0x00D0, 0x00E0,
    0x00F0, 0x0100, 0x0110, 0x0120, 0x0130, 0x0140, 0x0150, 0x0160,
    0x0170, 0x0180, 0x0190, 0x01A0, 0x01B0, 0x01C0, 0x01D0, 0x01E0,
    0x01F0, 0x0200, 0x0208, 0x0210, 0x0218, 0x0220, 0x0228, 0x0230,
    0x0238, 0x0240, 0x0248, 0x0250, 0x0258, 0x0260, 0x0268, 0x0270,
    0x0278, 0x0280, 0x0288, 0x0290, 0x0298, 0x02A0, 0x02A8, 0x02B0,
    0x02B8, 0x02C0, 0x02C8, 0x02D0, 0x02D8, 0x02E0, 0x02E8, 0x02F0,
    0x02F8, 0x0300, 0x0308, 0x0310, 0x0318, 0x0320, 0x0328, 0x0330,
    0x0338, 0x0340, 0x0348, 0x0350, 0x0358, 0x0360, 0x0368, 0x0370,
    0x0378, 0x0380, 0x0388, 0x0390, 0x0398, 0x03A0, 0x03A8, 0x03B0,
    0x03B8, 0x03C0, 0x03C8, 0x03D0, 0x03D8, 0x03E0, 0x03E8, 0x03F0,
    0x03F8, 0x0400, 0x0440, 0x0480, 0x04C0, 0x0500, 0x0540, 0x0580,
    0x05C0, 0x0600, 0x0640, 0x0680, 0x06C0, 0x0700, 0x0740, 0x0780,
    0x07C0, 0x0800, 0x0900, 0x0A00, 0x0B00, 0x0C00, 0x0D00, 0x0E00,
    0x0F00, 0x1000, 0x1400, 0x1800, 0x1C00, 0x2000, 0x3000, 0x4000,
)

USER_COLUMNS = (
    "english_transcript",
    "korean_translation",
    "korean_wav",
    "status",
    "notes",
)


@dataclass(frozen=True)
class MapEntry:
    audio_id: int
    offset: int
    span: int


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def parse_global_audio_map(map_path: Path, volume_size: int) -> list[MapEntry]:
    raw = map_path.read_bytes()
    if len(raw) < 7:
        raise ValueError(f"Audio map is too short: {map_path}")

    # Extracted 65535.MAP is an SCI patch resource.  0x0090 is map type 0x10
    # with the patch high bit set; the actual cumulative map begins at byte 2.
    patch_header = int.from_bytes(raw[:2], "little")
    if patch_header != 0x0090:
        raise ValueError(
            f"Unexpected 65535.MAP patch header 0x{patch_header:04X}; expected 0x0090"
        )

    data = raw[2:]
    position = 0
    offset = 0
    partial: list[tuple[int, int]] = []
    while position + 2 <= len(data):
        audio_id = int.from_bytes(data[position : position + 2], "little")
        position += 2
        if audio_id == 0xFFFF:
            break
        if position + 3 > len(data):
            raise ValueError(f"Truncated cumulative offset at map byte {position + 2}")
        offset += int.from_bytes(data[position : position + 3], "little")
        position += 3
        if offset >= volume_size:
            raise ValueError(
                f"Audio {audio_id} offset {offset} is outside volume size {volume_size}"
            )
        partial.append((audio_id, offset))
    else:
        raise ValueError("65535.MAP has no 0xFFFF terminator")

    # Shivers has three 0xFF pad bytes after the two-byte terminator.
    if any(value != 0xFF for value in data[position:]):
        raise ValueError(f"Unexpected non-0xFF bytes after map terminator at {position + 2}")

    entries: list[MapEntry] = []
    for index, (audio_id, entry_offset) in enumerate(partial):
        next_offset = partial[index + 1][1] if index + 1 < len(partial) else volume_size
        if next_offset <= entry_offset:
            raise ValueError(f"Non-increasing map offset at audio {audio_id}")
        entries.append(MapEntry(audio_id, entry_offset, next_offset - entry_offset))
    return entries


def classify(audio_id: int) -> tuple[str, str, str, str]:
    """Return category, translation scope, subtitle evidence, script evidence."""
    if audio_id == 30110:
        return (
            "scene_narration",
            "translate",
            "no_transcript_draw_found",
            "rm1v550.sc gSounds play 30110",
        )
    if audio_id in {30601, 30602}:
        return (
            "cassette_voice_composite",
            "translate_with_split_set",
            "optional_split_english_subtitles_exist",
            "rm6v240.sc caption-off composite playback",
        )
    if audio_id in {30611, 30612, 30613, 30621, 30622, 30623}:
        return (
            "cassette_voice_split",
            "translate_with_composite_set",
            "optional_english_subtitle_drawText_exists",
            "rm6v240.sc caption-on split playback",
        )
    if audio_id in {
        31150, 31250, 31350, 31950, 32010, 32050, 32150, 32250,
        32350, 32401, 32450, 32950, 32951, 32952, 33050, 33150, 33250,
    }:
        return (
            "museum_exhibit_narration",
            "translate",
            "no_spoken_transcript_draw_found",
            "room sNarrative/sNarration gSounds playback",
        )
    if 33510 <= audio_id <= 33518:
        return (
            "selection_audio_likely_music",
            "review_exclude_by_default",
            "screen_only_says_playing_current_selection",
            "rm35v154.sc 3x3 selection player",
        )
    if audio_id in {35031, 35033, 35034, 35036, 35037, 35038, 35039, 35040}:
        return (
            "new_game_random_voice",
            "translate",
            "no_transcript_draw_found",
            "newGame.sc randomized playback",
        )
    if audio_id in {35054, 35055, 35056}:
        return (
            "load_game_random_voice",
            "translate",
            "no_transcript_draw_found",
            "oldGame.sc randomized playback",
        )
    if audio_id in {
        35071, 35073, 35074, 35075, 35076, 35077, 35078, 35079,
        35082, 35084, 35085, 35086, 35087, 35088, 35089, 35090,
        35092, 35093, 35094,
    }:
        return (
            "death_scene_random_voice",
            "translate",
            "no_transcript_draw_found",
            "deadRoom.sc outcome-selected playback",
        )
    if audio_id in {35101, 35102}:
        return (
            "ending_random_voice",
            "translate",
            "no_transcript_draw_found",
            "endGame.sc randomized playback",
        )
    if audio_id in {35001, 35003}:
        return (
            "unreferenced_voice_namespace",
            "review",
            "no_static_playback_reference_found",
            "no literal script reference found",
        )
    if audio_id in {35010, 35020}:
        return (
            "ui_or_recurring_voice_candidate",
            "review",
            "no_transcript_draw_found",
            "logo/recurring room playback",
        )
    return (
        "short_scene_voice_or_effect_candidate",
        "review",
        "no_transcript_draw_found",
        "literal or dynamic room playback",
    )


def decode_sol_to_wav(resource: bytes, output_path: Path) -> tuple[int, int, int, float]:
    if len(resource) < 14:
        raise ValueError("SOL resource is shorter than its fixed header")
    if (resource[0] & 0x7F) != 0x0D or resource[2:6] != b"SOL\0":
        raise ValueError("Resource does not have an SCI SOL audio header")

    header_size = resource[1] + 2
    sample_rate = int.from_bytes(resource[6:8], "little")
    flags = resource[8]
    data_size = int.from_bytes(resource[9:13], "little")
    if header_size + data_size != len(resource):
        raise ValueError(
            f"SOL span mismatch: header {header_size} + data {data_size} != {len(resource)}"
        )
    if flags != 0x0D:
        raise ValueError(f"Unsupported Shivers SOL flags 0x{flags:02X}; expected 0x0D")

    sample = 0
    pcm = array("h")
    for delta in resource[header_size:]:
        if delta & 0x80:
            sample -= DPCM16_TABLE[delta & 0x7F]
        else:
            sample += DPCM16_TABLE[delta]
        if sample > 32767:
            sample -= 65536
        elif sample < -32768:
            sample += 65536
        pcm.append(sample)

    if sys.byteorder != "little":
        pcm.byteswap()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())
    return sample_rate, 1, 16, len(pcm) / sample_rate


def validate_and_copy_wav(resource: bytes, output_path: Path) -> tuple[int, int, int, float]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(resource)
    with wave.open(str(output_path), "rb") as wav:
        sample_rate = wav.getframerate()
        channels = wav.getnchannels()
        bits = wav.getsampwidth() * 8
        duration = wav.getnframes() / sample_rate
    return sample_rate, channels, bits, duration


def load_user_fields(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "audio_id" not in reader.fieldnames:
            raise ValueError(f"Existing translation CSV has no audio_id column: {path}")
        return {
            row["audio_id"]: {column: row.get(column, "") for column in USER_COLUMNS}
            for row in reader
        }


def write_csv(path: Path, rows: list[dict[str, str]], fields: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--map",
        type=Path,
        default=root / "extracted" / "installer" / "65535.MAP",
    )
    parser.add_argument(
        "--volume",
        type=Path,
        default=root / "extracted" / "installer" / "RESOURCE.SFX",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=root / "workspace" / "audio" / "narration_source_en",
    )
    parser.add_argument(
        "--translation-csv",
        type=Path,
        default=root / "workspace" / "translation" / "shivers_1_audio_narration_ko.csv",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    map_path = args.map.resolve()
    volume_path = args.volume.resolve()
    output_dir = args.output_dir.resolve()
    translation_csv = args.translation_csv.resolve()
    wav_dir = output_dir / "wav"

    if not map_path.is_file() or not volume_path.is_file():
        raise FileNotFoundError(f"Missing input: {map_path} or {volume_path}")

    volume = volume_path.read_bytes()
    entries = parse_global_audio_map(map_path, len(volume))
    if len(entries) != 733:
        raise ValueError(f"Unexpected Shivers audio entry count {len(entries)}; expected 733")
    candidates = [entry for entry in entries if 30000 <= entry.audio_id < 40000]
    if len(candidates) != 87:
        raise ValueError(f"Unexpected 3xxxx candidate count {len(candidates)}; expected 87")
    if len({entry.audio_id for entry in candidates}) != len(candidates):
        raise ValueError("Duplicate audio ID found in 3xxxx candidate namespace")

    existing = load_user_fields(translation_csv)
    rows: list[dict[str, str]] = []
    expected_wavs: set[Path] = set()
    for entry in sorted(candidates, key=lambda item: item.audio_id):
        resource = volume[entry.offset : entry.offset + entry.span]
        output_path = wav_dir / f"audio_{entry.audio_id:05d}.wav"
        expected_wavs.add(output_path.resolve())
        if resource[2:6] == b"SOL\0":
            source_format = "SOL_DPCM16_MONO"
            sample_rate, channels, bits, duration = decode_sol_to_wav(resource, output_path)
        elif resource[:4] == b"RIFF":
            source_format = "WAV_PCM"
            sample_rate, channels, bits, duration = validate_and_copy_wav(resource, output_path)
        else:
            raise ValueError(
                f"Audio {entry.audio_id} has unsupported signature {resource[:8].hex()}"
            )

        category, scope, subtitle_evidence, script_evidence = classify(entry.audio_id)
        relative_wav = output_path.relative_to(output_dir.parent.parent).as_posix()
        row = {
            "audio_id": str(entry.audio_id),
            "category": category,
            "translation_scope": scope,
            "subtitle_evidence": subtitle_evidence,
            "script_evidence": script_evidence,
            "source_format": source_format,
            "source_offset": str(entry.offset),
            "source_size": str(entry.span),
            "source_sha256": sha256_bytes(resource),
            "sample_rate_hz": str(sample_rate),
            "channels": str(channels),
            "bits_per_sample": str(bits),
            "duration_seconds": f"{duration:.3f}",
            "wav_path": relative_wav,
            "wav_sha256": sha256_file(output_path),
            **existing.get(str(entry.audio_id), {column: "" for column in USER_COLUMNS}),
        }
        if not row["status"]:
            row["status"] = "pending_review"
        rows.append(row)

    # Only remove obsolete WAV files in this extractor-owned folder.
    if wav_dir.exists():
        for path in wav_dir.glob("audio_*.wav"):
            if path.resolve() not in expected_wavs:
                path.unlink()

    fields = (
        "audio_id", "category", "translation_scope", "subtitle_evidence",
        "script_evidence", "source_format", "source_offset", "source_size",
        "source_sha256", "sample_rate_hz", "channels", "bits_per_sample",
        "duration_seconds", "wav_path", "wav_sha256", *USER_COLUMNS,
    )
    manifest_fields = fields[:15]
    write_csv(output_dir / "manifest.csv", rows, manifest_fields)
    write_csv(translation_csv, rows, fields)

    total_duration = sum(float(row["duration_seconds"]) for row in rows)
    translate_count = sum(row["translation_scope"].startswith("translate") for row in rows)
    review_count = sum(row["translation_scope"] == "review" for row in rows)
    excluded_count = sum(row["translation_scope"] == "review_exclude_by_default" for row in rows)
    print(f"audio_map_entries={len(entries)}")
    print(f"voice_namespace_wavs={len(rows)}")
    print(f"translate_rows={translate_count}")
    print(f"review_rows={review_count}")
    print(f"likely_music_rows={excluded_count}")
    print(f"total_duration_seconds={total_duration:.3f}")
    print(f"manifest={output_dir / 'manifest.csv'}")
    print(f"translation_csv={translation_csv}")
    print("static_validation=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
