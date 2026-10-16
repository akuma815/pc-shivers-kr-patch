"""Read-only graphics population/build audit; writes evidence only below qa/.

Byte changes are not proof of translation. Exact source pixel matches identify
reuse candidates, not permission to transfer artwork or proof of runtime use.
"""
import csv
import hashlib
import json
from collections import defaultdict, Counter
from pathlib import Path

from PIL import Image, ImageDraw
from extract_sci21_graphics import (parse_sci21_map, read_resource, merge_palette,
    parse_hunk_palette, u32, decode_cel, iter_pic_cels, iter_view_cels)

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'workspace/graphics/english_assets'
OUT = ROOT / 'qa/graphics_coverage_20260905'
BUILD = ROOT / 'build/shivers_ko_full_023_20260905'
SNAP = ROOT / 'backups/graphics/pic_view_manual_journal_complete_20260905'

def sha(data):
    return hashlib.sha256(data).hexdigest().upper()

def save_json(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def render(pixels, info, palette, transparent):
    im = Image.frombytes('P', (info['width'], info['height']), pixels)
    im.putpalette([v for _,r,g,b in palette for v in (r,g,b)])
    rgba = im.convert('RGBA')
    if transparent:
        alpha = im.point([0 if i == info['skip_color'] else 255 for i in range(256)], 'L')
        rgba.putalpha(alpha)
        rgba.paste((0,0,0,0), mask=alpha.point(lambda x: 255-x))
    return rgba

def main():
    OUT.mkdir(exist_ok=True, parents=True)
    manifest = list(csv.DictReader((ASSETS/'manifest.csv').open(encoding='utf-8-sig')))
    selected = {r['path']:r for r in manifest if r['path'].endswith('.png')}
    snap = {r['path']:r for r in json.loads((SNAP/'inputs.json').read_text('utf-8')) if r['path'].endswith('.png')}
    build = json.loads((BUILD/'build_manifest.json').read_text('utf-8'))
    patched = {(r['type'],r['number']):r for r in build['graphics']}
    frames = {r['input'] for r in build['graphics'] if r['type']=='pic'}
    frames.update(c['path'] for r in build['graphics'] if r['type']=='view' for c in r['cels'])
    drift, omitted, changed = [], [], set()
    for path,r in selected.items():
        current = sha((ASSETS/path).read_bytes()) if (ASSETS/path).exists() else 'MISSING'
        if current != snap.get(path,{}).get('working_sha256'):
            drift.append(path)
        if current != r['sha256']:
            changed.add(path)
            if path not in frames:
                omitted.append(path)
    integrity = [p for p,h in build['files'].items() if not (BUILD/p).exists() or sha((BUILD/p).read_bytes()) != h]
    unregistered = sorted({p.relative_to(ASSETS).as_posix() for p in (ASSETS/'png').rglob('*.png')} - selected.keys())
    checks = dict(selected_pngs=len(selected), changed_pngs=len(changed), snapshot_drift=drift,
        changed_not_listed_in_build=omitted, build_hash_failures=integrity, unregistered_pngs=unregistered)
    save_json('build_checks.json',checks)
    print(json.dumps(checks),flush=True)
    rows,_ = parse_sci21_map(ROOT/'extracted/installer/RESMAP.000',ROOT/'extracted/installer/RESSCI.000')
    base = merge_palette([(True,i,i,i) for i in range(256)],parse_hunk_palette((ASSETS/'raw/palette/00999.pal').read_bytes()))
    inventory, errors, sheets = [], [], defaultdict(list)
    pop = [r for r in rows if r['type_name'] in ('pic','view')]
    with (ROOT/'extracted/installer/RESSCI.000').open('rb') as volume:
        for index,row in enumerate(pop):
            kind,num = row['type_name'],int(row['number'])
            try:
                data = read_resource(volume,row)
                paloff = u32(data,8 if kind=='view' else 6)
                pal = merge_palette(base,parse_hunk_palette(data,paloff)) if paloff else base
                cels = iter_view_cels(data) if kind=='view' else ((0,c,h,-1) for c,h in iter_pic_cels(data))
                seen_headers = {}
                for loop,cel,header,alias in cels:
                    path = f'png/{kind}/{num:05d}/' + (f'loop_{loop:03d}_' if kind=='view' else '') + f'cel_{cel:03d}.png'
                    if header in seen_headers:
                        record = dict(seen_headers[header],path=path,loop=loop,cel=cel,alias=alias,selected=path in selected,changed=path in changed)
                        inventory.append(record)
                        continue
                    pixels,info = decode_cel(data,header)
                    im = render(pixels,info,pal,kind=='view' or info['transparent'])
                    record = dict(type=kind,number=num,loop=loop,cel=cel,alias=alias,path=path,
                        width=im.width,height=im.height,pixel_sha256=sha(im.tobytes()),
                        selected=path in selected,changed=path in changed,patched_resource=(kind,num) in patched)
                    seen_headers[header] = record
                    inventory.append(record)
                    # Original contact sheets for excluded resources; live artwork for unchanged selected cells.
                    group = None
                    if path not in selected and (kind=='pic' or (im.width>=200 and im.height>=140)):
                        group = 'excluded_'+kind
                    elif path in selected and path not in changed and im.width>=140 and im.height>=70:
                        group = 'unchanged_selected'
                    if group:
                        label = f'{kind} {num:05d} L{loop} C{cel}'
                        thumb = im.copy()
                        thumb.thumbnail((256,168))
                        sheets[group].append((label,thumb))
            except Exception as exc:
                errors.append(dict(type=kind,number=num,error=str(exc)))
            if index%200==0:
                print(f'processed {index}/{len(pop)} resources; cells={len(inventory)} errors={len(errors)}',flush=True)
    save_json('population.json',inventory)
    save_json('decode_errors.json',errors)
    groups = defaultdict(list)
    for r in inventory:
        groups[(r['width'],r['height'],r['pixel_sha256'])].append(r)
    duplicates = [dict(translated=[r for r in group if r['changed']],untranslated=[r for r in group if not r['changed']])
        for group in groups.values() if any(r['changed'] for r in group) and any(not r['changed'] for r in group)]
    save_json('duplicate_candidates.json',duplicates)
    for group,items in sheets.items():
        for start in range(0,len(items),24):
            sheet = Image.new('RGB',(1080,1200),(40,40,40))
            draw = ImageDraw.Draw(sheet)
            for j,(label,im) in enumerate(items[start:start+24]):
                x,y = j%4*270,j//4*200
                draw.text((x+5,y+4),label,fill='white')
                sheet.paste(im,(x+(270-im.width)//2,y+25),im)
            sheet.save(OUT/f'{group}_{start//24+1:03d}.png')
    summary = dict(resources=dict(Counter(r['type_name'] for r in pop)),cells=len(inventory),errors=errors,
        duplicate_groups=len(duplicates),duplicate_targets=sum(len(g['untranslated']) for g in duplicates),
        visual_contact_cells={k:len(v) for k,v in sheets.items()},**checks)
    save_json('summary.json',summary)
    print(json.dumps(summary),flush=True)

if __name__ == '__main__':
    main()
