#!/usr/bin/env python3
"""Build current PIC/VIEW artwork and all subtitles directly from original assets.

First invocation freezes PNG inputs; --snapshot reuses that immutable input set.
VIEW uses SCI32 RLE literal rows, preserving loop aliases, geometry and skip masks.
Only cel data pointers (24..35) change in the original resource prefix; encoded
streams are appended. Unknown fields and old streams remain byte-identical.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import struct
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image
from extract_sci21_graphics import (
    decode_cel, iter_view_cels, make_png, merge_palette, parse_hunk_palette, u32,
)
from build_translated_pic_batch_poc import build_picture, quantize_to_source_palette, sha256
from build_shivers_full_subtitles_poc import (
    build_movie_srts, build_audio_table, EXPECTED_FONT_SHA256, DEFAULT_MOVIE_CSV,
    DEFAULT_AUDIO_CSV, DEFAULT_AUDIO_BASE_CSV,
)
from build_intro_korean_draft_poc import (
    build_font_from_atlas, SOURCE_ISO_SHA256, HANGUL_ATLAS_SHA256, ASCII_FONT_SHA256,
)

PROJECT = Path(__file__).resolve().parents[2]
ASSETS = PROJECT / 'workspace/graphics/english_assets'
RUNTIME = PROJECT / 'work/scummvm_full_subtitle_runner_019'
PATCH = PROJECT / 'workspace/scummvm_audio_subtitles/scummvm_v2026.3.0_shivers_full_subtitles_layout_019.patch'
VIEW_HEADER = b'\x80' + bytes(25)  # SCI view patch: 2 + 2 + 22 bytes, byte 3 = 0.


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def freeze(snapshot):
    if snapshot.exists():
        raise FileExistsError(snapshot)
    rows = list(csv.DictReader((ASSETS / 'manifest.csv').open(encoding='utf-8-sig')))
    png_rows = [r for r in rows if r['path'].endswith('.png')]
    actual = {p.relative_to(ASSETS).as_posix() for p in (ASSETS / 'png').rglob('*.png')}
    expected = {r['path'] for r in png_rows}
    if actual != expected:
        raise ValueError(f'PNG catalog mismatch: extra={actual-expected}, missing={expected-actual}')
    snapshot.mkdir(parents=True)
    for row in png_rows:
        src = ASSETS / row['path']
        dst = snapshot / row['path']
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        row['working_sha256'] = sha256(src)
        if sha256(dst) != row['working_sha256']:
            raise ValueError(f'Input changed while freezing: {src}')
    # Subtitle inputs belong to the same reproducible snapshot.
    for rel in (DEFAULT_MOVIE_CSV, DEFAULT_AUDIO_CSV, DEFAULT_AUDIO_BASE_CSV):
        shutil.copy2(PROJECT / rel, snapshot / Path(rel).name)
    dump(snapshot / 'inputs.json', rows)


def append_rle(target, header, pixels, width, height):
    """Literal runs 1..127 match ScummVM celobj32.cpp READER_Compressed."""
    controls, literals = bytearray(), bytearray()
    control_rows, literal_rows = [], []
    for y in range(height):
        control_rows.append(len(controls))
        literal_rows.append(len(literals))
        row = pixels[y * width:(y + 1) * width]
        for x in range(0, width, 127):
            chunk = row[x:x + 127]
            controls.append(len(chunk))
            literals.extend(chunk)
    data_offset = len(target)
    target.extend(controls)
    literal_offset = len(target)
    target.extend(literals)
    table_offset = len(target)
    target.extend(struct.pack('<' + 'I' * (height * 2), *(control_rows + literal_rows)))
    struct.pack_into('<III', target, header + 24, data_offset, literal_offset, table_offset)


def build_view(source, rows, snapshot, palette):
    by_id = {(l, c): h for l, c, h, _ in iter_view_cels(source)}
    replacements, reports = {}, []
    for row in rows:
        header = by_id[(int(row['loop']), int(row['cel']))]
        pixels, info = decode_cel(source, header)
        if info['compression'] != 138:
            raise ValueError('Only verified SCI32 RLE views are supported')
        path = snapshot / row['path']
        with Image.open(path) as image:
            image = image.convert('RGBA')
            if image.size != (info['width'], info['height']):
                raise ValueError(f'VIEW must retain source dimensions: {path}')
            skip = int(info['skip_color'])
            alpha = image.getchannel('A').tobytes()
            if any((p == skip) != (a < 128) for p, a in zip(pixels, alpha)):
                raise ValueError(f'VIEW transparency changed: {path}')
            candidates = bytes(p for p in pixels if p != skip)
            quantized = quantize_to_source_palette(image, candidates, palette)
            result = bytes(skip if p == skip else q for p, q in zip(pixels, quantized))
        if header in replacements and replacements[header] != result:
            raise ValueError(f'Conflicting translations of shared loop: {path}')
        replacements[header] = result
        reports.append({'path': row['path'], 'sha256': row['working_sha256'],
                        'header': header, 'changed_pixels': sum(a != b for a,b in zip(pixels,result))})
    # Every cel, including aliases and unmodified cels, is verified after patching.
    patched = bytearray(source)
    allowed = set()
    for header, pixels in replacements.items():
        original, info = decode_cel(source, header)
        # Unchanged semantic roundtrip tests the new encoder on actual source data.
        trial = bytearray(source)
        append_rle(trial, header, original, int(info['width']), int(info['height']))
        if decode_cel(trial, header) != (original, info):
            raise AssertionError('VIEW unchanged roundtrip failed')
        append_rle(patched, header, pixels, int(info['width']), int(info['height']))
        allowed.update(range(header + 24, header + 36))
    if any(a != b and i not in allowed for i,(a,b) in enumerate(zip(source,patched))):
        raise AssertionError('VIEW protected prefix changed')
    for _, _, header, _ in iter_view_cels(source):
        original, info = decode_cel(source, header)
        if decode_cel(patched, header) != (replacements.get(header, original), info):
            raise AssertionError('VIEW cel readback failed')
    return bytes(patched), reports


def main():
    global RUNTIME, PATCH
    parser = argparse.ArgumentParser()
    parser.add_argument('--build-id', default='shivers_ko_full_024_20260905')
    parser.add_argument('--layout-id', choices=('019', '021', '025', '026', '027'), default='021')
    parser.add_argument('--snapshot', default='backups/graphics/pic_view_manual_existing_complete_024_20260905')
    args = parser.parse_args()
    RUNTIME = PROJECT / f'work/scummvm_full_subtitle_runner_{args.layout_id}'
    PATCH = PROJECT / f'workspace/scummvm_audio_subtitles/scummvm_v2026.3.0_shivers_full_subtitles_layout_{args.layout_id}.patch'
    output = PROJECT / 'build' / args.build_id
    snapshot = (PROJECT / args.snapshot).resolve()
    if output.parent.resolve() != (PROJECT / 'build').resolve() or output.exists():
        raise ValueError('Output must be a new direct child of build')
    if not snapshot.is_relative_to(PROJECT / 'backups/graphics'):
        raise ValueError('Snapshot must be inside backups/graphics')
    if not snapshot.exists():
        freeze(snapshot)
    rows = json.loads((snapshot / 'inputs.json').read_text(encoding='utf-8'))
    for row in rows:
        path = snapshot / row['path'] if row['path'].endswith('.png') else ASSETS / row['path']
        if sha256(path) != row.get('working_sha256', row['sha256']):
            raise ValueError(f'Input identity changed: {path}')
    if sha256(PROJECT / 'original/installer/SHIVCD.iso') != SOURCE_ISO_SHA256:
        raise ValueError('Original ISO identity mismatch')
    atlas = PROJECT.parent.parent / 'Font/Galmuri11_16x16.png'
    ascii_font = Path('C:/Windows/Fonts/consola.ttf')
    if sha256(atlas) != HANGUL_ATLAS_SHA256 or sha256(ascii_font) != ASCII_FONT_SHA256:
        raise ValueError('Font source identity mismatch')
    runtime_manifest = json.loads((RUNTIME / 'runner_manifest.json').read_text(encoding='utf-8-sig'))
    for entry in [runtime_manifest['runner'], *runtime_manifest['dependency_dlls']]:
        if sha256(RUNTIME / entry['path']) != entry['sha256']:
            raise ValueError('Runner identity mismatch')
    if sha256(PATCH) != runtime_manifest['source_patch_sha256']:
        raise ValueError('Runner source patch mismatch')
    output.mkdir(parents=True)
    original_files = []
    for src in sorted((PROJECT / 'extracted/installer').rglob('*')):
        if src.is_file():
            rel = src.relative_to(PROJECT / 'extracted/installer')
            dst = output / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.link(src, dst)
            original_files.append({'path': rel.as_posix(), 'sha256': sha256(src)})
    font, _ = build_font_from_atlas(atlas, ascii_font, set())
    (output / 'korean.fnt').write_bytes(font)
    if sha256(output / 'korean.fnt') != EXPECTED_FONT_SHA256:
        raise ValueError('Korean font regeneration mismatch')
    shutil.copy2('C:/Windows/Fonts/malgun.ttf', output / 'ShiversKorean.ttf')
    movies, subtitle_count = build_movie_srts(PROJECT, output, snapshot / Path(DEFAULT_MOVIE_CSV).name)
    audio, excluded = build_audio_table(output, snapshot / Path(DEFAULT_AUDIO_CSV).name,
                                       snapshot / Path(DEFAULT_AUDIO_BASE_CSV).name)
    if args.layout_id in ('025', '026', '027'):
        audio_path = output / 'audio_subtitles_ko.csv'
        legacy_text = audio_path.read_bytes().decode('cp949')
        utf8_text = legacy_text.replace('text_cp949', 'text_utf8', 1)
        audio_path.write_bytes(utf8_text.encode('utf-8'))
        if audio_path.read_bytes().decode('utf-8').replace('text_utf8', 'text_cp949', 1) != legacy_text:
            raise ValueError('Audio UTF-8 conversion changed subtitle content')
    changed = [r for r in rows if r['path'].endswith('.png') and r['working_sha256'] != r['sha256']]
    reports = []
    for row in (r for r in changed if r['type_name'] == 'pic'):
        number = int(row['number'])
        source = (ASSETS / f'raw/pic/{number:05d}.p56').read_bytes()
        path = snapshot / row['path']
        with Image.open(path) as image:
            dimensions = image.size
        patched, preview, report = build_picture(source, path, (int(row['width']),int(row['height'])), dimensions)
        dst = output / f'{number}.p56'
        dst.write_bytes(b'\x81\0\0\0' + patched)
        preview.close()
        reports.append({'type': 'pic', 'number': number, 'patch': dst.name,
                        'sha256': sha256(dst), 'input': row['path'], **report})
    views = defaultdict(list)
    for row in (r for r in changed if r['type_name'] == 'view'):
        views[int(row['number'])].append(row)
    base_palette = merge_palette([(True,i,i,i) for i in range(256)],
                                  parse_hunk_palette((ASSETS / 'raw/palette/00999.pal').read_bytes()))
    for number, view_rows in sorted(views.items()):
        source = (ASSETS / f'raw/view/{number:05d}.v56').read_bytes()
        offset = u32(source, 8)
        palette = merge_palette(base_palette, parse_hunk_palette(source, offset)) if offset else base_palette
        patched, cels = build_view(source, view_rows, snapshot, palette)
        dst = output / f'{number}.v56'
        dst.write_bytes(VIEW_HEADER + patched)
        if dst.read_bytes()[26:] != patched:
            raise AssertionError('VIEW patch readback mismatch')
        reports.append({'type': 'view', 'number': number, 'patch': dst.name,
                        'sha256': sha256(dst), 'cels': cels,
                        'protected_prefix': 'all original bytes except cel pointers 24..35',
                        'new_stream_bytes': len(patched)-len(source)})
    shutil.copytree(RUNTIME, output / 'runtime')
    # Native subtitles are English. Fan SRT and custom audio captions are independent.
    (output / 'scummvm.ini').write_text('[scummvm]\nsubtitles=false\n\n[shivers-ko-full]\ngameid=shivers\nplatform=windows\nlanguage=ko\npath=.\ndescription=Shivers Korean Full\nsubtitles=false\n', encoding='ascii')
    (output / 'play.cmd').write_text(('@echo off\r\ncd /d "%~dp0"\r\nif not exist "..\\..\\work\\scummvm_saves\\full" mkdir "..\\..\\work\\scummvm_saves\\full"\r\n"runtime\\RUNNER_EXE" --config="scummvm.ini" --path="." --savepath="..\\..\\work\\scummvm_saves\\full" --opl-driver=nuked --no-subtitles --language=ko %* shivers-ko-full\r\n').replace('RUNNER_EXE', runtime_manifest['runner']['path']), encoding='ascii')
    (output / 'continue.cmd').write_text('@echo off\r\ncall "%~dp0play.cmd" --save-slot=1\r\n', encoding='ascii')
    counts = Counter(r['type'] for r in reports)
    manifest = {'build_id': args.build_id, 'snapshot': snapshot.relative_to(PROJECT).as_posix(),
        'snapshot_sha256': sha256(snapshot / 'inputs.json'), 'original_iso_sha256': SOURCE_ISO_SHA256,
        'original_files': original_files, 'graphics': reports, 'counts': dict(counts),
        'view_changed_frames': sum(len(r['cels']) for r in reports if r['type']=='view'),
        'movie_subtitles': movies, 'movie_subtitle_count': subtitle_count,
        'audio_subtitle_count': len(audio), 'excluded_audio': excluded,
        'runtime': runtime_manifest, 'movie_layout': {'font_size':13 if args.layout_id in ('021', '025', '026', '027') else 15, 'top':'drawRect.bottom - 110' if args.layout_id in ('021', '025', '026', '027') else 'drawRect.bottom - 75', 'bottom':'drawRect.bottom - 10', 'horizontal_scale_denominator':'screen width' if args.layout_id == '027' else 'video width'},
        'audio_font': {'file':'ShiversKorean.ttf', 'size_mode':'cell', 'size':16, 'encoding':'utf-8'} if args.layout_id in ('025', '026', '027') else {'file':'korean.fnt', 'encoding':'cp949'},
        'audio_layout': {'top':366, 'anchor':'fixed native framebuffer y', 'max_lines':2, 'padding_y':2} if args.layout_id in ('026', '027') else {'bottom_margin':20, 'max_lines':2},
        'save_compatibility': {'target':'shivers-ko-full','directory':'work/scummvm_saves/full','continue_slot':1,'save_files_in_build':False},
        'static_validation':'PASS', 'runtime_visual_qa':'pending manual gameplay',
        'files': {p.relative_to(output).as_posix():sha256(p) for p in sorted(output.rglob('*')) if p.is_file()}}
    dump(output / 'build_manifest.json', manifest)
    print(json.dumps({'output':str(output), 'counts':dict(counts), 'view_frames':manifest['view_changed_frames'],
                      'movie_subtitles':subtitle_count, 'audio_subtitles':len(audio), 'static_validation':'PASS'}))


if __name__ == '__main__':
    main()
