#!/usr/bin/env python3
"""Build a ScummVM PoC containing a declared batch of translated SCI pictures."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from extract_sci21_graphics import (
    decode_cel,
    iter_pic_cels,
    make_png,
    merge_palette,
    parse_hunk_palette,
    u32,
)


BUILD_ID = "scummvm_ko_poc_011_pic_batch_01030"
BATCH_CONFIG = "workspace/graphics/translated_pic_batch_01030.json"
EXPECTED_RESOURCE_NUMBERS = [5, 910, 911, 914, 918, 920, 921, 922, 923, 927, 991, 1003, 1004, 1020, 1030]
SCI2_PIC_PATCH_HEADER = bytes.fromhex("81000000")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def quantize_to_source_palette(
    image: Image.Image,
    source_pixels: bytes,
    palette: list[tuple[bool, int, int, int]],
) -> bytes:
    candidates = sorted(set(source_pixels))
    if not candidates or len(candidates) > 256:
        raise ValueError("Invalid source palette candidate set")
    index_map = candidates + [candidates[0]] * (256 - len(candidates))
    flat_palette: list[int] = []
    for source_index in index_map:
        _, red, green, blue = palette[source_index]
        flat_palette.extend((red, green, blue))
    palette_image = Image.new("P", (1, 1))
    palette_image.putpalette(flat_palette)
    quantized = image.convert("RGB").quantize(palette=palette_image, dither=Image.Dither.NONE)
    return bytes(index_map[index] for index in quantized.tobytes())


def build_picture(
    source: bytes,
    translated_path: Path,
    declared_source_dimensions: tuple[int, int],
    declared_translation_dimensions: tuple[int, int],
) -> tuple[bytes, Image.Image, dict[str, object]]:
    cels = list(iter_pic_cels(source))
    if len(cels) != 1 or cels[0][0] != 0:
        raise ValueError("Expected exactly one picture cel")
    cel_header = cels[0][1]
    source_pixels, info = decode_cel(source, cel_header)
    dimensions = (int(info["width"]), int(info["height"]))
    if dimensions != declared_source_dimensions:
        raise ValueError(f"Source dimension mismatch: declared {declared_source_dimensions}, got {dimensions}")
    if int(info["compression"]) != 0 or bool(info["transparent"]):
        raise ValueError("Batch currently supports only uncompressed, opaque pictures")
    pixels_offset = struct.unpack_from("<I", source, cel_header + 24)[0]
    if pixels_offset + len(source_pixels) != len(source):
        raise ValueError("Picture pixel plane is not the exact resource tail")

    palette_offset = u32(source, 6)
    if palette_offset == 0:
        raise ValueError("Picture has no embedded palette")
    palette = merge_palette(
        [(True, index, index, index) for index in range(256)],
        parse_hunk_palette(source, palette_offset),
    )

    with Image.open(translated_path) as translated:
        if translated.size != declared_translation_dimensions:
            raise ValueError(
                f"Translation dimension mismatch: declared {declared_translation_dimensions}, got {translated.size}"
            )
        normalized = translated.convert("RGB").resize(dimensions, Image.Resampling.LANCZOS)
    output_pixels = quantize_to_source_palette(normalized, source_pixels, palette)
    if len(output_pixels) != len(source_pixels):
        raise AssertionError("Quantized pixel plane size mismatch")
    changed_offsets = [
        index for index, (before, after) in enumerate(zip(source_pixels, output_pixels)) if before != after
    ]
    if not changed_offsets:
        raise AssertionError("Translated picture changed no pixels")

    patched = bytearray(source)
    patched[pixels_offset : pixels_offset + len(output_pixels)] = output_pixels
    patched_bytes = bytes(patched)
    if len(patched_bytes) != len(source) or patched_bytes[:pixels_offset] != source[:pixels_offset]:
        raise AssertionError("Protected picture container bytes changed")
    readback_pixels, readback_info = decode_cel(patched_bytes, cel_header)
    if readback_pixels != output_pixels or readback_info != info:
        raise AssertionError("Picture readback mismatch")

    width, _ = dimensions
    xs = [index % width for index in changed_offsets]
    ys = [index // width for index in changed_offsets]
    changed_bbox = [min(xs), min(ys), max(xs) + 1, max(ys) + 1]
    preview = make_png(readback_pixels, readback_info, palette, False)
    metadata: dict[str, object] = {
        "source_dimensions": list(dimensions),
        "translation_dimensions": list(declared_translation_dimensions),
        "compression": int(info["compression"]),
        "transparent": bool(info["transparent"]),
        "pixels_offset": pixels_offset,
        "source_palette_indices": len(set(source_pixels)),
        "changed_pixel_count": len(changed_offsets),
        "changed_pixel_bbox": changed_bbox,
        "writable_region": [0, 0, dimensions[0], dimensions[1]],
        "protected_prefix_bytes": pixels_offset,
        "resource_size_preserved": True,
    }
    return patched_bytes, preview, metadata


def make_contact_sheet(previews: list[tuple[int, Image.Image]], output: Path) -> None:
    columns = 3
    cell_width = 336
    cell_height = 252
    rows = (len(previews) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    for index, (resource_number, preview) in enumerate(previews):
        column = index % columns
        row = index // columns
        left = column * cell_width
        top = row * cell_height
        thumb = ImageOps.contain(preview.convert("RGB"), (320, 216), Image.Resampling.LANCZOS)
        x = left + (cell_width - thumb.width) // 2
        y = top + 26 + (216 - thumb.height) // 2
        sheet.paste(thumb, (x, y))
        draw.text((left + 8, top + 6), f"pic {resource_number:05d}", fill=(255, 255, 255))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, optimize=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-id", default=BUILD_ID)
    parser.add_argument("--allow-draft", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--hangul-atlas", type=Path)
    args = parser.parse_args()
    if not args.allow_draft:
        raise ValueError("This is a PoC build; pass --allow-draft explicitly")

    project = Path(__file__).resolve().parents[2]
    config_path = args.config.resolve() if args.config else project / BATCH_CONFIG
    hangul_atlas = (
        args.hangul_atlas.resolve()
        if args.hangul_atlas
        else project.parent.parent / "Font" / "Galmuri11_16x16.png"
    )
    output_root = project / "build" / args.build_id
    base_builder = project / "workspace" / "scripts" / "build_intro_korean_draft_poc.py"
    if output_root.exists():
        raise FileExistsError(f"Refusing to replace existing build: {output_root}")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("schema_version") != 1:
        raise ValueError("Unsupported batch config schema")
    assets = config.get("assets")
    if not isinstance(assets, list):
        raise ValueError("Batch assets must be a list")
    numbers = [int(asset["resource_number"]) for asset in assets]
    expected_numbers = [
        int(number) for number in config.get("expected_resource_numbers", EXPECTED_RESOURCE_NUMBERS)
    ]
    if numbers != expected_numbers or len(set(numbers)) != len(numbers):
        raise ValueError(f"Unexpected resource population: {numbers}")

    prepared: list[tuple[dict[str, object], bytes, Image.Image, dict[str, object]]] = []
    for asset in assets:
        number = int(asset["resource_number"])
        source_path = project / str(asset["source_path"])
        translated_path = project / str(asset["translation_path"])
        if sha256(source_path) != str(asset["source_sha256"]):
            raise ValueError(f"Source identity mismatch for pic {number}")
        if sha256(translated_path) != str(asset["translation_sha256"]):
            raise ValueError(f"Translation identity mismatch for pic {number}")
        patched, preview, metadata = build_picture(
            source_path.read_bytes(),
            translated_path,
            tuple(int(value) for value in asset["source_dimensions"]),
            tuple(int(value) for value in asset["translation_dimensions"]),
        )
        prepared.append((asset, patched, preview, metadata))

    subprocess.run(
        [
            sys.executable,
            "-B",
            str(base_builder),
            "--build-id",
            args.build_id,
            "--allow-draft",
            "--hangul-atlas",
            str(hangul_atlas),
        ],
        cwd=project,
        check=True,
    )

    previews_root = output_root / "graphics_previews"
    previews_root.mkdir(parents=True)
    manifest_assets: list[dict[str, object]] = []
    contact_previews: list[tuple[int, Image.Image]] = []
    for asset, patched, preview, metadata in prepared:
        number = int(asset["resource_number"])
        patch_output = output_root / f"{number}.p56"
        preview_output = previews_root / f"pic_{number:05d}.png"
        patch_output.write_bytes(SCI2_PIC_PATCH_HEADER + patched)
        preview.save(preview_output, optimize=True)
        if patch_output.read_bytes()[:4] != SCI2_PIC_PATCH_HEADER:
            raise AssertionError(f"Patch header readback failed for pic {number}")
        if patch_output.read_bytes()[4:] != patched:
            raise AssertionError(f"Patch payload readback failed for pic {number}")
        manifest_assets.append(
            {
                "resource_number": number,
                "source_path": asset["source_path"],
                "source_sha256": asset["source_sha256"],
                "translation_path": asset["translation_path"],
                "translation_sha256": asset["translation_sha256"],
                **metadata,
                "patch_path": patch_output.relative_to(output_root).as_posix(),
                "patch_sha256": sha256(patch_output),
                "resource_sha256": sha256_bytes(patched),
                "preview_path": preview_output.relative_to(output_root).as_posix(),
                "preview_sha256": sha256(preview_output),
            }
        )
        contact_previews.append((number, preview))

    contact_sheet = previews_root / f"contact_sheet_pic_{min(numbers):05d}_{max(numbers):05d}.png"
    make_contact_sheet(contact_previews, contact_sheet)

    manifest_path = output_root / "poc_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["scope"] = (
        f"ScummVM-only intro Korean draft plus {len(manifest_assets)} declared translated pictures "
        f"through pic {max(numbers)}"
    )
    manifest["graphics_batch"] = {
        "config_path": config_path.relative_to(project).as_posix(),
        "config_sha256": sha256(config_path),
        "status": "poc_input",
        "normalization": config["normalization"],
        "resource_count": len(manifest_assets),
        "resource_numbers": numbers,
        "assets": manifest_assets,
        "contact_sheet": contact_sheet.relative_to(output_root).as_posix(),
        "contact_sheet_sha256": sha256(contact_sheet),
    }
    manifest["expected_writes"]["picture_batch_owner"] = args.build_id
    manifest["expected_writes"]["picture_batch_resources"] = numbers
    manifest["not_proved_by_build"].extend(
        [
            f"all {len(manifest_assets)} picture patches are selected by their live game screens",
            "all translated artwork is visually approved after palette conversion",
            "all screens preserve navigation, state changes, and adjacent UI",
        ]
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"output={output_root}")
    print(f"pictures={len(manifest_assets)}")
    print(f"resource_numbers={','.join(str(number) for number in numbers)}")
    print(f"changed_pixels={sum(int(asset['changed_pixel_count']) for asset in manifest_assets)}")
    print("static_validation=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
