#!/usr/bin/env python3
"""Export and verify the Shivers 1 full-movie subtitle translation CSV.

The protected columns are reconstructed from the exact English Windows 1.02
script/heap resources. Translators should edit only translation_ko, status, and
translator_notes in the generated CSV.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MovieConfig:
    movie_id: int
    role: str
    script_number: int
    heap_size: int
    heap_sha256: str
    script_size: int
    script_sha256: str
    start_frames: tuple[int, ...]
    final_end_frame: int


MOVIES = (
    MovieConfig(
        1002,
        "intro",
        930,
        1728,
        "9A45F316D43ED635D2C48F15D5C614D39E5EDB5925249671765A39C0668BA39E",
        1292,
        "2F5EE82BF8DE9D1D54930AD57EF2F4AD1A1B213E460652B2866643FED39994CA",
        (142, 200, 270, 320, 360, 445, 495, 530, 675, 750, 850, 890, 950, 990, 1030),
        1100,
    ),
    MovieConfig(
        3361,
        "professor_ghost",
        931,
        876,
        "C6CF1670EA4A46773565640E71F149BDFEA62A0AC29E89F386B4E72045460168",
        800,
        "EE3A0BF26BB8F976FD38D83EEE1E80BA5C5CF6CCA7AEC0013F31A8CA83B1A132",
        (25, 100, 225, 260, 325, 400, 465, 520),
        702,
    ),
    MovieConfig(
        35180,
        "girl_ghost",
        932,
        598,
        "30FBD2DB2CD3B3FFA5405C4292E071C966457A61472CF51AB1E1A6DCA2501598",
        1360,
        "D02814CB7100D03B9F47FEB150EFBD17B9C010FF57E9BB2BBC94A062A1A183DC",
        (60, 95, 135, 155, 195, 227, 300, 327, 350, 375, 390, 417, 452, 460, 482, 510),
        570,
    ),
    MovieConfig(
        28040,
        "boy_ghost",
        933,
        584,
        "70A9A113144C9DAD7CB5847BD4F768C707ED278DFE57BB39E647766BDC6B65EC",
        1168,
        "D49EF68088E5B708F496A350DBB5EBC60AD3F33AF05016ED67ACAEEB269C2AAC",
        (35, 57, 90, 125, 172, 190, 210, 236, 258, 263, 285, 305, 325),
        370,
    ),
    MovieConfig(
        16000,
        "museum_theatre",
        934,
        2480,
        "65F8F73CB8636F350D851588DB8F99013AD4E4E48F597B515F84403C8116A882",
        2148,
        "E9C813588BD274F467D39A4A932A04816B7FD13190CEDD8A7EAA6424F9F89366",
        (130, 145, 170, 180, 198, 245, 280, 305, 345, 385, 410, 465, 520, 675,
         760, 850, 900, 925, 970, 1030, 1050, 1180, 1314, 1340, 1400, 1530, 1580, 1620),
        2000,
    ),
    MovieConfig(
        39260,
        "ending",
        935,
        1306,
        "13B7509C2B68C057EB52AC3E8396679488EC879C809153B6843BC2DCE32701C3",
        3074,
        "A8CB7FDA7A7C3D1E219B4000D0B2E278ABFE352B81E76FBDD48E48E420FA73E9",
        (5, 100, 105, 110, 120, 130, 135, 140, 145, 150, 155, 190, 195, 220,
         285, 310, 345, 260, 370, 382, 395, 432, 470, 482, 505, 540, 550, 565,
         575, 585, 612, 632, 652, 660, 680, 710, 745, 775),
        840,
    ),
)

FIELDNAMES = (
    "record_id",
    "movie_id",
    "movie_file",
    "video_role",
    "script_number",
    "heap_path",
    "caption_index",
    "heap_string_id",
    "heap_offset",
    "start_frame",
    "end_frame",
    "row_type",
    "source_cp1252",
    "translation_ko",
    "status",
    "translator_notes",
    "source_byte_length",
    "raw_hex",
    "technical_notes",
)

EDITABLE_FIELDS = {"translation_ko", "status", "translator_notes"}
PROTECTED_FIELDS = tuple(field for field in FIELDNAMES if field not in EDITABLE_FIELDS)
ALLOWED_STATUSES = {
    "needs_translation",
    "in_translation",
    "translated",
    "needs_human_review",
    "approved",
    "locked_control",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def extract_heap_strings(heap: bytes) -> list[tuple[int, bytes]]:
    end_of_strings, object_words = struct.unpack_from("<HH", heap, 0)
    position = object_words * 2 + 4
    while True:
        object_position = position
        block_type = struct.unpack_from("<H", heap, position)[0]
        position += 2
        if block_type != 0x1234:
            break
        property_count = struct.unpack_from("<H", heap, position)[0]
        position = object_position + property_count * 2

    strings: list[tuple[int, bytes]] = []
    while position < end_of_strings:
        nul = heap.find(b"\0", position, end_of_strings)
        if nul < 0:
            raise ValueError("Unterminated heap string")
        strings.append((position, heap[position:nul]))
        position = nul + 1
    return strings


def load_intro_translations(project: Path) -> dict[str, dict[str, str]]:
    path = project / "workspace" / "translation" / "intro_movie_1002.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("table_id") != "shivers_intro_movie_1002":
        raise ValueError("Intro translation table identity mismatch")
    translations: dict[str, dict[str, str]] = {}
    for entry in document["entries"]:
        raw_hex = str(entry["raw_hex"]).upper()
        translations[raw_hex] = {
            "translation_ko": str(entry.get("ko", "")),
            "status": str(entry.get("status", "needs_human_review")),
            "translator_notes": " | ".join(str(note) for note in entry.get("notes", [])),
        }
    if len(translations) != 15:
        raise ValueError("Expected 15 intro translation entries")
    return translations


def build_rows(project: Path) -> list[dict[str, str]]:
    intro_translations = load_intro_translations(project)
    rows: list[dict[str, str]] = []
    for movie in MOVIES:
        resource_name = f"{movie.script_number:05d}"
        heap_path = project / "extracted" / "sci" / "heap" / f"{resource_name}.hep"
        script_path = project / "extracted" / "sci" / "script" / f"{resource_name}.scr"
        if heap_path.stat().st_size != movie.heap_size or sha256(heap_path) != movie.heap_sha256:
            raise ValueError(f"Heap {movie.script_number} identity mismatch")
        if script_path.stat().st_size != movie.script_size or sha256(script_path) != movie.script_sha256:
            raise ValueError(f"Script {movie.script_number} identity mismatch")

        strings = extract_heap_strings(heap_path.read_bytes())
        caption_count = len(movie.start_frames)
        if len(strings) < caption_count:
            raise ValueError(f"Heap {movie.script_number} has too few strings")
        end_frames = movie.start_frames[1:] + (movie.final_end_frame,)
        for index, ((offset, raw), start_frame, end_frame) in enumerate(
            zip(strings[:caption_count], movie.start_frames, end_frames), start=1
        ):
            raw_hex = raw.hex().upper()
            source = raw.decode("cp1252")
            row_type = "clear_control" if not raw.strip(b" \t\r\n") else "caption"
            translation = ""
            status = "locked_control" if row_type == "clear_control" else "needs_translation"
            translator_notes = ""
            if movie.movie_id == 1002:
                if raw_hex not in intro_translations:
                    raise ValueError(f"Intro source row {index} does not match its JSON SSOT")
                translation = intro_translations[raw_hex]["translation_ko"]
                status = intro_translations[raw_hex]["status"]
                translator_notes = intro_translations[raw_hex]["translator_notes"]

            technical_notes = ""
            if row_type == "clear_control":
                technical_notes = "자막 지우기용 빈 문자열; 번역 금지"
            elif movie.movie_id == 39260 and index == 17:
                technical_notes = "다음 script 이벤트가 frame 260으로 역행함; 원본 순서 보존 및 런타임 타이밍 확인 필요"
            elif movie.movie_id == 39260 and index == 18:
                technical_notes = "원본 script에서 frame 345 이벤트 뒤에 frame 260으로 기록됨"

            rows.append(
                {
                    "record_id": f"V{movie.movie_id:05d}_{index:03d}",
                    "movie_id": str(movie.movie_id),
                    "movie_file": f"MOVIES/{movie.movie_id}.VMD",
                    "video_role": movie.role,
                    "script_number": str(movie.script_number),
                    "heap_path": f"extracted/sci/heap/{resource_name}.hep",
                    "caption_index": str(index),
                    "heap_string_id": str(index),
                    "heap_offset": str(offset),
                    "start_frame": str(start_frame),
                    "end_frame": str(end_frame),
                    "row_type": row_type,
                    "source_cp1252": source,
                    "translation_ko": translation,
                    "status": status,
                    "translator_notes": translator_notes,
                    "source_byte_length": str(len(raw)),
                    "raw_hex": raw_hex,
                    "technical_notes": technical_notes,
                }
            )
    return rows


def validate_rows(actual: list[dict[str, str]], expected: list[dict[str, str]]) -> None:
    if len(actual) != len(expected):
        raise ValueError(f"CSV row count mismatch: expected {len(expected)}, got {len(actual)}")
    seen: set[str] = set()
    for row_number, (row, baseline) in enumerate(zip(actual, expected), start=2):
        if tuple(row.keys()) != FIELDNAMES:
            raise ValueError("CSV header/order mismatch")
        record_id = row["record_id"]
        if record_id in seen:
            raise ValueError(f"Duplicate record_id at CSV row {row_number}: {record_id}")
        seen.add(record_id)
        for field in PROTECTED_FIELDS:
            if row[field] != baseline[field]:
                raise ValueError(f"Protected field changed at {record_id}: {field}")
        if row["status"] not in ALLOWED_STATUSES:
            raise ValueError(f"Invalid status at {record_id}: {row['status']}")
        if row["row_type"] == "clear_control":
            if row["translation_ko"] or row["status"] != "locked_control":
                raise ValueError(f"Clear-control row must remain locked: {record_id}")
        elif row["translation_ko"]:
            try:
                row["translation_ko"].encode("cp949")
            except UnicodeEncodeError as error:
                raise ValueError(f"CP949-unencodable translation at {record_id}") from error


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != FIELDNAMES:
            raise ValueError("CSV header/order mismatch")
        return list(reader)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Shivers1 project root",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output CSV path (default: workspace/translation/movie_subtitles.csv)",
    )
    parser.add_argument("--verify", action="store_true", help="Verify an existing CSV without modifying it")
    args = parser.parse_args()

    project = args.project.resolve()
    output = args.output or project / "workspace" / "translation" / "movie_subtitles.csv"
    output = output.resolve()
    expected = build_rows(project)

    if args.verify:
        actual = read_csv(output)
        validate_rows(actual, expected)
        print(f"verified={output}")
        print(f"rows={len(actual)}")
        print(f"movies={len({row['movie_id'] for row in actual})}")
        print(f"translatable_rows={sum(row['row_type'] == 'caption' for row in actual)}")
        print(f"translated_rows={sum(bool(row['translation_ko']) for row in actual)}")
        return 0

    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing translation CSV: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDNAMES, quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writeheader()
        writer.writerows(expected)

    actual = read_csv(output)
    validate_rows(actual, expected)
    print(f"output={output}")
    print(f"rows={len(actual)}")
    print(f"movies={len({row['movie_id'] for row in actual})}")
    print(f"translatable_rows={sum(row['row_type'] == 'caption' for row in actual)}")
    print(f"translated_rows={sum(bool(row['translation_ko']) for row in actual)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
