#!/usr/bin/env python3
"""Build a reversible full-intro Korean draft PoC for ScummVM Shivers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BUILD_ID = "scummvm_ko_poc_007_intro_draft"
SOURCE_ISO_SHA256 = "62E7E35D288D7C4ACB3A04CDE1CC9865D3B24E8EB40F8CB32D86DC00B28A80C9"
SOURCE_HEAP_SHA256 = "9A45F316D43ED635D2C48F15D5C614D39E5EDB5925249671765A39C0668BA39E"
SOURCE_HEAP_SIZE = 1728
SOURCE_SCRIPT_SHA256 = "2F5EE82BF8DE9D1D54930AD57EF2F4AD1A1B213E460652B2866643FED39994CA"
SOURCE_SCRIPT_SIZE = 1292
HANGUL_FONT_SHA256 = "48A28E97B34FC8E5B157657633670CD1B7DE126CFC414DA65CE9C3D5BC8BE733"
HANGUL_ATLAS_SHA256 = "ED69582591AD99E0C351AB0BB0118657E775A6AE1B927C8D82D3D82891FF284C"
ASCII_FONT_SHA256 = "C6E6CE8119FDD47EC6A5449A08E2D2AD7F41EA03143AAE193068ED9FA58EAEBC"
INTRO_BRANCH_OFFSET = 0x2A
INTRO_BRANCH_SOURCE = bytes.fromhex("306304")
INTRO_BRANCH_OUTPUT = bytes.fromhex("300000")
HEAP_PATCH_HEADER = bytes.fromhex("9100")
SCRIPT_PATCH_HEADER = bytes.fromhex("8200")
KOREAN_FONT_MAGIC = b"SCVMSJIS"
KOREAN_FONT_VERSION = 3
KOREAN_GLYPH_COUNT = 11184
ASCII_GLYPH_COUNT = 256
FONT_THRESHOLD = 112
ATLAS_CELL_SIZE = 16
ATLAS_COLUMNS = 64
ATLAS_ROWS = 175
ATLAS_HANGUL_COUNT = 11172


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


def rasterize(font: ImageFont.FreeTypeFont, character: str, width: int, height: int, baseline: int) -> Image.Image:
    image = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(image)
    draw.text((width // 2, baseline), character, font=font, fill=255, anchor="ms")
    return image.point(lambda value: 255 if value >= FONT_THRESHOLD else 0)


def pack_1bpp(image: Image.Image) -> bytes:
    width, height = image.size
    stride = (width + 7) // 8
    packed = bytearray()
    pixels = image.load()
    for y in range(height):
        row = 0
        for x in range(stride * 8):
            row = (row << 1) | (1 if x < width and pixels[x, y] else 0)
        packed.extend(row.to_bytes(stride, "big"))
    return bytes(packed)


def build_font(hangul_font_path: Path, ascii_font_path: Path, characters: set[str]) -> tuple[bytes, dict[str, Image.Image]]:
    hangul_font = ImageFont.truetype(hangul_font_path, 14)
    ascii_font = ImageFont.truetype(ascii_font_path, 13)
    glyph_images: dict[str, Image.Image] = {}
    hangul_table = bytearray(KOREAN_GLYPH_COUNT * 32)
    ascii_table = bytearray(ASCII_GLYPH_COUNT * 32)

    for code in range(0x20, 0x7F):
        character = chr(code)
        image = rasterize(ascii_font, character, 8, 16, 13)
        glyph_images[character] = image
        packed = pack_1bpp(image)
        output = bytearray()
        for value in packed:
            output.extend((value, 0))
        ascii_table[code * 32 : (code + 1) * 32] = output

    used_hangul = sorted(character for character in characters if 0xAC00 <= ord(character) <= 0xD7A3)
    for character in used_hangul:
        encoded = character.encode("cp949")
        if len(encoded) != 2 or not (0xB0 <= encoded[0] <= 0xC8 and 0xA1 <= encoded[1] <= 0xFE):
            raise ValueError(f"Character is outside ScummVM's supported KS X 1001 range: {character}")
        image = rasterize(hangul_font, character, 16, 16, 15)
        packed = pack_1bpp(image)
        if len(packed) != 32 or not any(packed):
            raise ValueError(f"Empty or invalid Hangul glyph: {character}")
        glyph_images[character] = image
        index = ord(character) - 0xAC00
        hangul_table[index * 32 : (index + 1) * 32] = packed

    header = KOREAN_FONT_MAGIC + struct.pack(">IHHH", KOREAN_FONT_VERSION, KOREAN_GLYPH_COUNT, ASCII_GLYPH_COUNT, 0)
    output = header + hangul_table + ascii_table
    expected_size = 18 + KOREAN_GLYPH_COUNT * 32 + ASCII_GLYPH_COUNT * 32
    if len(output) != expected_size:
        raise AssertionError("Unexpected korean.fnt size")
    return output, glyph_images


def build_font_from_atlas(
    hangul_atlas_path: Path, ascii_font_path: Path, characters: set[str]
) -> tuple[bytes, dict[str, Image.Image]]:
    ascii_font = ImageFont.truetype(ascii_font_path, 13)
    glyph_images: dict[str, Image.Image] = {}
    hangul_table = bytearray(KOREAN_GLYPH_COUNT * 32)
    ascii_table = bytearray(ASCII_GLYPH_COUNT * 32)

    for code in range(0x20, 0x7F):
        character = chr(code)
        image = rasterize(ascii_font, character, 8, 16, 13)
        glyph_images[character] = image
        packed = pack_1bpp(image)
        output = bytearray()
        for value in packed:
            output.extend((value, 0))
        ascii_table[code * 32 : (code + 1) * 32] = output

    with Image.open(hangul_atlas_path) as source:
        atlas = source.convert("RGBA")
    expected_size = (ATLAS_COLUMNS * ATLAS_CELL_SIZE, ATLAS_ROWS * ATLAS_CELL_SIZE)
    if atlas.size != expected_size:
        raise ValueError(f"Unexpected Hangul atlas dimensions: {atlas.size}, expected {expected_size}")

    atlas_pixels = atlas.load()
    used_hangul = sorted(character for character in characters if 0xAC00 <= ord(character) <= 0xD7A3)
    used_hangul_set = set(used_hangul)
    nonempty_cells = 0
    max_ink_right = 0
    max_ink_bottom = 0
    for index in range(ATLAS_COLUMNS * ATLAS_ROWS):
        cell_x = (index % ATLAS_COLUMNS) * ATLAS_CELL_SIZE
        cell_y = (index // ATLAS_COLUMNS) * ATLAS_CELL_SIZE
        image = Image.new("L", (ATLAS_CELL_SIZE, ATLAS_CELL_SIZE), 0)
        image_pixels = image.load()
        ink_coordinates: list[tuple[int, int]] = []
        for y in range(ATLAS_CELL_SIZE):
            for x in range(ATLAS_CELL_SIZE):
                red, green, blue, alpha = atlas_pixels[cell_x + x, cell_y + y]
                if alpha and (red or green or blue):
                    image_pixels[x, y] = 255
                    ink_coordinates.append((x, y))

        if index < ATLAS_HANGUL_COUNT:
            if not ink_coordinates:
                raise ValueError(f"Empty Hangul atlas cell at index {index}")
            nonempty_cells += 1
            max_ink_right = max(max_ink_right, max(x for x, _ in ink_coordinates) + 1)
            max_ink_bottom = max(max_ink_bottom, max(y for _, y in ink_coordinates) + 1)
            packed = pack_1bpp(image)
            hangul_table[index * 32 : (index + 1) * 32] = packed
            character = chr(0xAC00 + index)
            if character in used_hangul_set:
                encoded = character.encode("cp949")
                if len(encoded) != 2 or not (0xB0 <= encoded[0] <= 0xC8 and 0xA1 <= encoded[1] <= 0xFE):
                    raise ValueError(f"Character is outside ScummVM's supported KS X 1001 range: {character}")
                glyph_images[character] = image
        elif ink_coordinates:
            raise ValueError(f"Expected empty atlas padding cell at index {index}")

    if nonempty_cells != ATLAS_HANGUL_COUNT:
        raise AssertionError("Unexpected number of populated Hangul atlas cells")
    if max_ink_right > 11 or max_ink_bottom > 11:
        raise ValueError(f"Atlas ink exceeds its expected 11x11 bounds: {max_ink_right}x{max_ink_bottom}")

    header = KOREAN_FONT_MAGIC + struct.pack(">IHHH", KOREAN_FONT_VERSION, KOREAN_GLYPH_COUNT, ASCII_GLYPH_COUNT, 0)
    output = header + hangul_table + ascii_table
    expected_output_size = 18 + KOREAN_GLYPH_COUNT * 32 + ASCII_GLYPH_COUNT * 32
    if len(output) != expected_output_size:
        raise AssertionError("Unexpected korean.fnt size")
    return output, glyph_images


def wrap_text(text: str, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        current_width = 0
        for character in paragraph:
            width = 8 if ord(character) < 0x80 else 16
            if current and current_width + width > max_width:
                lines.append(current.rstrip())
                current = ""
                current_width = 0
            current += character
            current_width += width
        lines.append(current.rstrip())
    return lines


def create_preview(entries: list[dict[str, object]], glyph_images: dict[str, Image.Image], output: Path) -> None:
    width = 272
    rendered = [(entry, wrap_text(str(entry["ko"]), 263)) for entry in entries]
    height = 8 + sum(8 + max(1, len(lines)) * 16 + 8 for _, lines in rendered)
    preview = Image.new("RGB", (width, height), "black")
    y = 8
    orange = Image.new("RGB", (16, 16), (205, 82, 20))
    for entry, lines in rendered:
        for line in lines:
            x = 4
            for character in line:
                if character == " ":
                    x += 8
                    continue
                glyph = glyph_images.get(character)
                if glyph is None:
                    raise ValueError(f"Preview glyph is missing: U+{ord(character):04X}")
                preview.paste(orange.crop((0, 0, glyph.width, glyph.height)), (x, y), glyph)
                x += glyph.width
            y += 16
        y += 8
        ImageDraw.Draw(preview).line((0, y - 4, width - 1, y - 4), fill=(48, 48, 48))
    preview.resize((width * 2, height * 2), Image.Resampling.NEAREST).save(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-id", default=BUILD_ID)
    parser.add_argument("--allow-draft", action="store_true")
    parser.add_argument("--hangul-atlas", type=Path)
    args = parser.parse_args()
    if not args.allow_draft:
        raise ValueError("This is a draft-only PoC; pass --allow-draft explicitly")

    project = Path(__file__).resolve().parents[2]
    source_root = project / "extracted" / "installer"
    source_iso = project / "original" / "installer" / "SHIVCD.iso"
    heap_path = project / "extracted" / "sci" / "heap" / "00930.hep"
    script_path = project / "extracted" / "sci" / "script" / "00930.scr"
    translation_path = project / "workspace" / "translation" / "intro_movie_1002.json"
    hangul_font_path = Path("C:/Windows/Fonts/NanumGothic.ttf")
    hangul_atlas_path = args.hangul_atlas.resolve() if args.hangul_atlas else None
    ascii_font_path = Path("C:/Windows/Fonts/consola.ttf")
    output_root = project / "build" / args.build_id

    if output_root.exists():
        raise FileExistsError(f"Refusing to replace existing build: {output_root}")
    if sha256(source_iso) != SOURCE_ISO_SHA256:
        raise ValueError("Source ISO identity mismatch")
    if heap_path.stat().st_size != SOURCE_HEAP_SIZE or sha256(heap_path) != SOURCE_HEAP_SHA256:
        raise ValueError("Heap 930 identity mismatch")
    if script_path.stat().st_size != SOURCE_SCRIPT_SIZE or sha256(script_path) != SOURCE_SCRIPT_SHA256:
        raise ValueError("Script 930 identity mismatch")
    if sha256(ascii_font_path) != ASCII_FONT_SHA256:
        raise ValueError("ASCII font source identity mismatch")
    if hangul_atlas_path:
        if sha256(hangul_atlas_path) != HANGUL_ATLAS_SHA256:
            raise ValueError("Hangul atlas source identity mismatch")
    elif sha256(hangul_font_path) != HANGUL_FONT_SHA256:
        raise ValueError("Hangul font source identity mismatch")

    translation = json.loads(translation_path.read_text(encoding="utf-8"))
    if translation["source"]["heap_sha256"] != SOURCE_HEAP_SHA256:
        raise ValueError("Translation SSOT source identity mismatch")
    entries = translation["entries"]
    if len(entries) != 15:
        raise ValueError("Expected exactly 15 intro subtitle entries")

    source_heap = heap_path.read_bytes()
    patched_heap = bytearray(source_heap)
    allowed_heap_offsets: set[int] = set()
    all_characters: set[str] = set()
    for entry in entries:
        offset = int(entry["heap_offset"])
        source_raw = bytes.fromhex(str(entry["raw_hex"]))
        if source_heap[offset : offset + len(source_raw)] != source_raw:
            raise ValueError(f"Entry {entry['entry_id']} Expected Write mismatch")
        ko = str(entry["ko"])
        encoded = ko.encode("cp949")
        if len(encoded) > len(source_raw):
            raise ValueError(f"Entry {entry['entry_id']} exceeds its original slot")
        patched_heap[offset : offset + len(source_raw)] = encoded + bytes(len(source_raw) - len(encoded))
        allowed_heap_offsets.update(range(offset, offset + len(source_raw)))
        all_characters.update(ko.replace("\n", ""))

    changed_heap_offsets = [index for index, pair in enumerate(zip(source_heap, patched_heap)) if pair[0] != pair[1]]
    if not changed_heap_offsets or any(index not in allowed_heap_offsets for index in changed_heap_offsets):
        raise AssertionError("Heap diff escaped declared subtitle slots")

    source_script = script_path.read_bytes()
    if source_script[INTRO_BRANCH_OFFSET : INTRO_BRANCH_OFFSET + 3] != INTRO_BRANCH_SOURCE:
        raise ValueError("Intro branch Expected Write mismatch")
    patched_script = bytearray(source_script)
    patched_script[INTRO_BRANCH_OFFSET : INTRO_BRANCH_OFFSET + 3] = INTRO_BRANCH_OUTPUT
    changed_script_offsets = [index for index, pair in enumerate(zip(source_script, patched_script)) if pair[0] != pair[1]]
    if changed_script_offsets != [INTRO_BRANCH_OFFSET + 1, INTRO_BRANCH_OFFSET + 2]:
        raise AssertionError("Unexpected script diff")

    if hangul_atlas_path:
        korean_font, glyph_images = build_font_from_atlas(hangul_atlas_path, ascii_font_path, all_characters)
    else:
        korean_font, glyph_images = build_font(hangul_font_path, ascii_font_path, all_characters)
    used_hangul = sorted(character for character in all_characters if 0xAC00 <= ord(character) <= 0xD7A3)
    unsupported = sorted(character for character in all_characters if ord(character) >= 0x80 and character not in used_hangul)
    if unsupported:
        raise ValueError(f"Unsupported non-ASCII characters: {unsupported}")

    output_root.mkdir(parents=True)
    linked_files, linked_bytes = hardlink_tree(source_root, output_root)
    heap_patch = output_root / "930.hep"
    script_patch = output_root / "930.scr"
    font_output = output_root / "korean.fnt"
    preview_output = output_root / "intro_korean_font_preview.png"
    heap_patch.write_bytes(HEAP_PATCH_HEADER + patched_heap)
    script_patch.write_bytes(SCRIPT_PATCH_HEADER + patched_script)
    font_output.write_bytes(korean_font)
    create_preview(entries, glyph_images, preview_output)

    if heap_patch.read_bytes()[2:] != patched_heap or script_patch.read_bytes()[2:] != patched_script:
        raise AssertionError("Patch round-trip failed")
    if font_output.stat().st_size != 366098:
        raise AssertionError("korean.fnt size validation failed")

    manifest = {
        "schema_version": 1,
        "build_id": args.build_id,
        "scope": "ScummVM-only full intro Korean draft PoC",
        "translation": {
            "path": "workspace/translation/intro_movie_1002.json",
            "entry_count": len(entries),
            "status": "needs_human_review",
            "encoding": "cp949",
        },
        "source": {
            "iso_sha256": SOURCE_ISO_SHA256,
            "heap_sha256": SOURCE_HEAP_SHA256,
            "script_sha256": SOURCE_SCRIPT_SHA256,
        },
        "font": {
            "format": "ScummVM Korean FNT v3",
            "hangul_source_type": "bitmap_atlas" if hangul_atlas_path else "truetype",
            "hangul_source": str(hangul_atlas_path or hangul_font_path),
            "hangul_source_sha256": HANGUL_ATLAS_SHA256 if hangul_atlas_path else HANGUL_FONT_SHA256,
            "ascii_source": str(ascii_font_path),
            "ascii_source_sha256": ASCII_FONT_SHA256,
            "used_hangul_glyphs": len(used_hangul),
            "missing_required_glyphs": 0,
            "atlas_mapping": "U+AC00..U+D7A3 sequential" if hangul_atlas_path else None,
            "atlas_cell_size": [ATLAS_CELL_SIZE, ATLAS_CELL_SIZE] if hangul_atlas_path else None,
            "atlas_populated_glyphs": ATLAS_HANGUL_COUNT if hangul_atlas_path else None,
            "atlas_max_ink_bounds": [11, 11] if hangul_atlas_path else None,
            "raster_transform": "none; exact 1bpp mask" if hangul_atlas_path else f"threshold {FONT_THRESHOLD}",
        },
        "expected_writes": {
            "heap_owner": args.build_id,
            "heap_changed_offsets": changed_heap_offsets,
            "script_changed_offsets": changed_script_offsets,
        },
        "output": {
            "hardlinked_source_files": linked_files,
            "hardlinked_source_bytes": linked_bytes,
            "heap_patch_sha256": sha256(heap_patch),
            "script_patch_sha256": sha256(script_patch),
            "font_sha256": sha256(font_output),
            "preview_sha256": sha256(preview_output),
        },
        "not_proved_by_build": [
            "all 15 Korean subtitles render without clipping",
            "translation timing and naturalness",
            "full-game Korean glyph coverage",
            "original SIERRAW.EXE compatibility",
        ],
    }
    manifest_path = output_root / "poc_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"output={output_root}")
    print(f"entries={len(entries)}")
    print(f"used_hangul_glyphs={len(used_hangul)}")
    print(f"heap_changed_offsets={len(changed_heap_offsets)}")
    print("static_validation=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
