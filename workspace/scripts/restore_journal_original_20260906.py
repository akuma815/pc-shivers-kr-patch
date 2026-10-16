"""Back up and restore only canonical journal PNGs; leave builds and saves alone."""
import csv
import hashlib
import io
import json
import shutil
from pathlib import Path
from extract_sci21_graphics import decode_cel, iter_view_cels, iter_pic_cels, make_png, merge_palette, parse_hunk_palette, u32

P = Path(__file__).resolve().parents[2]
A = P / 'workspace/graphics/english_assets'
B = P / 'backups/graphics/journal_before_original_restore_20260906'


def sha(data):
    return hashlib.sha256(data).hexdigest().upper()


def main():
    if B.exists():
        raise FileExistsError(B)
    with (A / 'manifest.csv').open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    entries = {r['path']: r for r in rows}
    selected = [r for r in rows if r['path'].endswith('.png') and
                ((r['type_name'] == 'view' and 37252 <= int(r['number']) <= 37265)
                 or (r['type_name'] == 'pic' and int(r['number']) == 37252))]
    assert len(selected) == 15
    pal_path = 'raw/palette/00999.pal'
    pal_data = (A / pal_path).read_bytes()
    assert sha(pal_data) == entries[pal_path]['sha256']
    base = merge_palette([(True, i, i, i) for i in range(256)], parse_hunk_palette(pal_data))
    plan = []
    for r in selected:
        kind, number = r['type_name'], int(r['number'])
        raw_path = f'raw/{kind}/{number:05d}.' + ('v56' if kind == 'view' else 'p56')
        data = (A / raw_path).read_bytes()
        assert sha(data) == entries[raw_path]['sha256']
        offset = u32(data, 8 if kind == 'view' else 6)
        palette = merge_palette(base, parse_hunk_palette(data, offset)) if offset else base
        if kind == 'view':
            header = next(h for l, c, h, _ in iter_view_cels(data) if l == int(r['loop']) and c == int(r['cel']))
        else:
            header = next(h for c, h in iter_pic_cels(data) if c == int(r['cel']))
        pixels, info = decode_cel(data, header)
        image = make_png(pixels, info, palette, True if kind == 'view' else bool(info['transparent']))
        stream = io.BytesIO()
        image.save(stream, format='PNG', optimize=True)
        image.close()
        original = stream.getvalue()
        assert sha(original) == r['sha256'], r['path']
        target = A / r['path']
        assert target.is_file() and target.resolve().is_relative_to((A / 'png').resolve())
        plan.append((target, original, sha(target.read_bytes())))
    before = {p.relative_to(A).as_posix(): sha(p.read_bytes()) for p in (A / 'png').rglob('*.png')}
    B.mkdir(parents=True)
    report = []
    for target, original, old_hash in plan:
        backup = B / target.relative_to(A)
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
        assert sha(backup.read_bytes()) == old_hash
        report.append({'path': target.relative_to(A).as_posix(), 'before_sha256': old_hash,
                       'original_sha256': sha(original)})
    (B / 'restore_manifest.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    for target, original, old_hash in plan:
        assert sha(target.read_bytes()) == old_hash
    for target, original, _ in plan:
        target.write_bytes(original)
        assert sha(target.read_bytes()) == sha(original)
    allowed = {r['path'] for r in report}
    after = {p.relative_to(A).as_posix(): sha(p.read_bytes()) for p in (A / 'png').rglob('*.png')}
    assert before.keys() == after.keys()
    assert all(before[p] == after[p] for p in before if p not in allowed)
    print(json.dumps({'restored_pngs': len(plan), 'other_pngs_preserved': len(before)-len(plan),
                      'backup': str(B), 'builds_modified': False}))


if __name__ == '__main__':
    main()
