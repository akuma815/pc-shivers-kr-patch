#!/usr/bin/env python3
"""Extract and render SCI 2.1 picture/view resources from Shivers.

The renderer follows ScummVM's SCI32 CelObj layout.  It deliberately keeps the
original decompressed resource beside lossless PNG previews so later editing
and reinsertion can be based on the exact source bytes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import struct
from pathlib import Path

from PIL import Image

from extract_sci21_resources import decompress_lzs
from inventory_shivers import parse_sci21_map


EXTENSIONS = {"view": "v56", "pic": "p56", "palette": "pal"}


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def i16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<h", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def check_range(data: bytes, offset: int, size: int, label: str) -> None:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ValueError(f"{label} exceeds resource: offset={offset}, size={size}, total={len(data)}")


def parse_hunk_palette(data: bytes, offset: int = 0) -> list[tuple[bool, int, int, int]]:
    """Return 256 (used, r, g, b) entries from an SCI32 HunkPalette."""
    check_range(data, offset, 13, "palette header")
    count = data[offset + 10]
    if count == 0:
        return [(False, 0, 0, 0)] * 256
    if count != 1:
        raise ValueError(f"unsupported SCI32 palette count {count}")
    entry = offset + 13 + 2 * count
    check_range(data, entry, 22, "palette entry")
    start = data[entry + 10]
    colors = u16(data, entry + 14)
    default_used = bool(data[entry + 16])
    shared_used = bool(data[entry + 17])
    if start + colors > 256:
        raise ValueError(f"palette range {start}+{colors} exceeds 256")
    cursor = entry + 22
    stride = 3 if shared_used else 4
    check_range(data, cursor, colors * stride, "palette colors")
    result = [(False, 0, 0, 0)] * 256
    for index in range(start, start + colors):
        used = default_used if shared_used else bool(data[cursor])
        if not shared_used:
            cursor += 1
        result[index] = (used, data[cursor], data[cursor + 1], data[cursor + 2])
        cursor += 3
    return result


def merge_palette(
    base: list[tuple[bool, int, int, int]],
    overlay: list[tuple[bool, int, int, int]],
) -> list[tuple[bool, int, int, int]]:
    return [new if new[0] else old for old, new in zip(base, overlay)]


def decode_cel(data: bytes, header: int) -> tuple[bytes, dict[str, int | bool]]:
    check_range(data, header, 42, "cel header")
    width = u16(data, header)
    height = u16(data, header + 2)
    skip = data[header + 8]
    compression = data[header + 9]
    flags = u16(data, header + 10)
    if width == 0 or height == 0 or width > 4096 or height > 4096:
        raise ValueError(f"invalid cel dimensions {width}x{height}")

    if compression == 0:
        pixels_offset = u32(data, header + 24)
        check_range(data, pixels_offset, 0, "uncompressed pixels")
        available = min(width * height, len(data) - pixels_offset)
        pixels = data[pixels_offset : pixels_offset + available]
        # A few shipped Shivers resources declare one more row than they
        # contain. ScummVM also treats these as truncated; use the cel's skip
        # color for the absent tail so previews stay in bounds and deterministic.
        if available < width * height:
            pixels += bytes([skip]) * (width * height - available)
    elif compression == 138:
        data_offset = u32(data, header + 24)
        literal_base = u32(data, header + 28)
        control_offset = u32(data, header + 32)
        check_range(data, control_offset, height * 8, "row offset tables")
        output = bytearray()
        for y in range(height):
            row_rel = u32(data, control_offset + y * 4)
            literal_rel = u32(data, control_offset + height * 4 + y * 4)
            row_cursor = data_offset + row_rel
            literal_cursor = literal_base + literal_rel
            row = bytearray()
            while len(row) < width:
                check_range(data, row_cursor, 1, "RLE control")
                control = data[row_cursor]
                row_cursor += 1
                length = control & 0x3F if control & 0x80 else control
                if length == 0 or len(row) + length > width:
                    raise ValueError(
                        f"invalid RLE run {length} at row {y}, x={len(row)}, width={width}"
                    )
                if control & 0x80:
                    if control & 0x40:
                        row.extend([skip] * length)
                    else:
                        check_range(data, literal_cursor, 1, "RLE fill literal")
                        row.extend([data[literal_cursor]] * length)
                        literal_cursor += 1
                else:
                    check_range(data, literal_cursor, length, "RLE literals")
                    row.extend(data[literal_cursor : literal_cursor + length])
                    literal_cursor += length
            output.extend(row)
        pixels = bytes(output)
    else:
        raise ValueError(f"unsupported cel compression {compression}")

    transparent = bool(flags & 1) if flags & 0x80 else compression != 0
    return pixels, {
        "width": width,
        "height": height,
        "skip_color": skip,
        "compression": compression,
        "flags": flags,
        "transparent": transparent,
        "origin_x": i16(data, header + 4),
        "origin_y": i16(data, header + 6),
    }


def make_png(
    pixels: bytes,
    info: dict[str, int | bool],
    palette: list[tuple[bool, int, int, int]],
    transparent: bool,
) -> Image.Image:
    skip = int(info["skip_color"])
    rgba = bytearray()
    for pixel in pixels:
        _, red, green, blue = palette[pixel]
        alpha = 0 if transparent and pixel == skip else 255
        rgba.extend((red, green, blue, alpha))
    return Image.frombytes("RGBA", (int(info["width"]), int(info["height"])), bytes(rgba))


def iter_view_cels(data: bytes):
    check_range(data, 0, 18, "view header")
    loop_count = data[2]
    header_size = u16(data, 0)
    loop_header_size = data[12]
    cel_header_size = data[13]
    for loop in range(loop_count):
        loop_header = 2 + header_size + loop_header_size * loop
        check_range(data, loop_header, max(loop_header_size, 16), "loop header")
        alias = struct.unpack_from("<b", data, loop_header)[0]
        resolved = loop if alias == -1 else alias
        resolved_header = 2 + header_size + loop_header_size * resolved
        check_range(data, resolved_header, max(loop_header_size, 16), "resolved loop header")
        cel_count = data[resolved_header + 2]
        base = u32(data, resolved_header + 12)
        for cel in range(cel_count):
            yield loop, cel, base + cel_header_size * cel, alias


def iter_pic_cels(data: bytes):
    check_range(data, 0, 14, "picture header")
    cel_count = data[2]
    base = u16(data, 0)
    cel_header_size = u16(data, 4)
    for cel in range(cel_count):
        header = base + cel_header_size * cel
        yield cel, header


def read_resource(volume, row: dict[str, object]) -> bytes:
    packed_size = int(row["packed_size"])
    unpacked_size = int(row["unpacked_size"])
    volume.seek(int(row["volume_offset"]) + 13)
    packed = volume.read(packed_size)
    if len(packed) != packed_size:
        raise ValueError(f"short payload for {row['type_name']}:{row['number']}")
    compression = int(row["compression"])
    if compression == 0:
        unpacked = packed
    elif compression == 32:
        unpacked = decompress_lzs(packed, unpacked_size)
    else:
        raise ValueError(f"unsupported resource compression {compression}")
    if len(unpacked) != unpacked_size:
        raise ValueError("resource unpacked size mismatch")
    return unpacked


def parse_selection(value: str) -> dict[str, set[int] | None]:
    result: dict[str, set[int] | None] = {"pic": set(), "view": set(), "palette": set()}
    for item in value.split(","):
        if not item.strip():
            continue
        resource_type, number = item.strip().split(":", 1)
        if resource_type not in result:
            raise ValueError(f"unsupported resource type {resource_type}")
        if number == "*":
            result[resource_type] = None
        elif result[resource_type] is not None:
            result[resource_type].add(int(number))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument(
        "--select",
        required=True,
        help="comma-separated resources, for example pic:902,view:922,palette:999",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    project = args.project.resolve()
    output = args.output if args.output.is_absolute() else project / args.output
    selection = parse_selection(args.select)
    map_path = project / "extracted" / "installer" / "RESMAP.000"
    volume_path = project / "extracted" / "installer" / "RESSCI.000"
    rows, _ = parse_sci21_map(map_path, volume_path)
    chosen = [
        row
        for row in rows
        if row["type_name"] in selection
        and (
            selection[str(row["type_name"])] is None
            or int(row["number"]) in selection[str(row["type_name"])]
        )
    ]
    requested = sum(len(numbers) for numbers in selection.values() if numbers is not None)
    if all(numbers is not None for numbers in selection.values()) and len(chosen) != requested:
        found = {(str(row["type_name"]), int(row["number"])) for row in chosen}
        missing = [
            f"{kind}:{number}"
            for kind, numbers in selection.items()
            if numbers is not None
            for number in sorted(numbers)
            if (kind, number) not in found
        ]
        raise ValueError(f"resource(s) not found: {', '.join(missing)}")

    output.mkdir(parents=True, exist_ok=True)
    resources: dict[tuple[str, int], bytes] = {}
    manifest: list[dict[str, object]] = []
    with volume_path.open("rb") as volume:
        for row in chosen:
            kind = str(row["type_name"])
            number = int(row["number"])
            raw_dir = output / "raw" / kind
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_path = raw_dir / f"{number:05d}.{EXTENSIONS[kind]}"
            if raw_path.is_file() and raw_path.stat().st_size == int(row["unpacked_size"]):
                data = raw_path.read_bytes()
            else:
                data = read_resource(volume, row)
                raw_path.write_bytes(data)
            resources[(kind, number)] = data
            manifest.append(
                {
                    "type_name": kind,
                    "number": number,
                    "loop": "",
                    "cel": "",
                    "width": "",
                    "height": "",
                    "compression": int(row["compression"]),
                    "sha256": hashlib.sha256(data).hexdigest().upper(),
                    "path": raw_path.relative_to(output).as_posix(),
                    "note": "decompressed original resource",
                }
            )

    base_palette = [(True, index, index, index) for index in range(256)]
    palette_999 = resources.get(("palette", 999))
    if palette_999 is not None:
        base_palette = merge_palette(base_palette, parse_hunk_palette(palette_999))

    for (kind, number), data in sorted(resources.items()):
        if kind == "palette":
            continue
        palette_offset = u32(data, 8 if kind == "view" else 6)
        palette = base_palette
        if palette_offset:
            palette = merge_palette(base_palette, parse_hunk_palette(data, palette_offset))
        png_dir = output / "png" / kind / f"{number:05d}"
        png_dir.mkdir(parents=True, exist_ok=True)
        if kind == "view":
            cels = ((loop, cel, header, alias) for loop, cel, header, alias in iter_view_cels(data))
            for loop, cel, header, alias in cels:
                pixels, info = decode_cel(data, header)
                image = make_png(pixels, info, palette, True)
                path = png_dir / f"loop_{loop:03d}_cel_{cel:03d}.png"
                if not path.is_file():
                    image.save(path, optimize=True)
                manifest.append(
                    {
                        "type_name": kind,
                        "number": number,
                        "loop": loop,
                        "cel": cel,
                        "width": info["width"],
                        "height": info["height"],
                        "compression": info["compression"],
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
                        "path": path.relative_to(output).as_posix(),
                        "note": f"rendered cel; loop_alias={alias}",
                    }
                )
        else:
            for cel, header in iter_pic_cels(data):
                pixels, info = decode_cel(data, header)
                image = make_png(pixels, info, palette, bool(info["transparent"]))
                path = png_dir / f"cel_{cel:03d}.png"
                if not path.is_file():
                    image.save(path, optimize=True)
                manifest.append(
                    {
                        "type_name": kind,
                        "number": number,
                        "loop": 0,
                        "cel": cel,
                        "width": info["width"],
                        "height": info["height"],
                        "compression": info["compression"],
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
                        "path": path.relative_to(output).as_posix(),
                        "note": (
                            f"rendered cel; position={i16(data, header + 38)},{i16(data, header + 40)}; "
                            f"priority={i16(data, header + 36)}"
                        ),
                    }
                )

    manifest_path = output / "manifest.csv"
    with manifest_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=manifest[0].keys())
        writer.writeheader()
        writer.writerows(manifest)
    print(f"resources={len(resources)}")
    print(f"rendered_png={sum(1 for row in manifest if str(row['path']).endswith('.png'))}")
    print(f"manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
