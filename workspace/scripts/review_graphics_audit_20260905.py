"""Build diagnostic previews without modifying canonical artwork."""
import csv
import json
from PIL import Image, ImageDraw
from audit_graphics_coverage_20260905 import ROOT, ASSETS, OUT, BUILD, sha, render, save_json
from extract_sci21_graphics import (merge_palette, parse_hunk_palette, u32,
    decode_cel, iter_pic_cels, iter_view_cels)

def review_duplicates():
    population=json.loads((OUT/'population.json').read_text('utf-8'))
    duplicate_groups=json.loads((OUT/'duplicate_candidates.json').read_text('utf-8'))
    b=json.loads((BUILD/'build_manifest.json').read_text('utf-8'))
    originals={r['path']:r for r in population}
    effective_changed=set()
    base=merge_palette([(True,i,i,i) for i in range(256)],parse_hunk_palette((ASSETS/'raw/palette/00999.pal').read_bytes()))
    for g in b['graphics']:
        kind,num=g['type'],g['number']
        data=(BUILD/g['patch']).read_bytes()[26 if kind=='view' else 4:]
        off=u32(data,8 if kind=='view' else 6)
        pal=merge_palette(base,parse_hunk_palette(data,off)) if off else base
        cels=iter_view_cels(data) if kind=='view' else ((0,c,h,-1) for c,h in iter_pic_cels(data))
        for loop,cel,header,alias in cels:
            path=f'png/{kind}/{num:05d}/'+(f'loop_{loop:03d}_' if kind=='view' else '')+f'cel_{cel:03d}.png'
            pixels,info=decode_cel(data,header)
            im=render(pixels,info,pal,kind=='view' or info['transparent'])
            if sha(im.tobytes())!=originals[path]['pixel_sha256']:
                effective_changed.add(path)
    filtered=[]
    for group in duplicate_groups:
        targets=[r for r in group['untranslated'] if r['path'] not in effective_changed]
        if targets:
            filtered.append(dict(translated=group['translated'],untranslated=targets))
    save_json('duplicate_candidates_effective.json',filtered)
    print('effective changed cells',len(effective_changed),'duplicate groups',len(filtered))
    for group in filtered:
        print('FROM',[(r['type'],r['number'],r['loop'],r['cel']) for r in group['translated']],
              'TO',[(r['type'],r['number'],r['loop'],r['cel']) for r in group['untranslated']])

def representative_views():
    population=json.loads((OUT/'population.json').read_text('utf-8'))
    summary=json.loads((OUT/'summary.json').read_text('utf-8'))
    rows=[r for r in population if r['type']=='view' and not r['selected'] and r['width']>=200 and r['height']>=140 and r['alias']==-1]
    assert len(rows)==summary['visual_contact_cells']['excluded_view'], 'contact index needs review'
    chosen={}
    for index,r in enumerate(rows):
        if r['number'] not in chosen:
            chosen[r['number']]=(index,r)
    items=[]
    folder=OUT/'representative_views'
    folder.mkdir(exist_ok=True)
    for number,(index,r) in chosen.items():
        with Image.open(OUT/f'excluded_view_{index//24+1:03d}.png') as sheet:
            slot=index%24
            x,y=slot%4*270,slot//4*200
            tile=sheet.crop((x,y+24,x+270,y+198))
        path=folder/f'{number:05d}.png'
        tile.save(path)
        items.append((f"view {number:05d} L{r['loop']} C{r['cel']}",path))
    sheet_images(items,'excluded_view_representative')
    print('large unselected view resources',len(chosen))

def sheet_images(items, prefix):
    for start in range(0,len(items),20):
        im = Image.new('RGB',(1200,1100),(35,35,35))
        draw = ImageDraw.Draw(im)
        for slot,(label,path) in enumerate(items[start:start+20]):
            with Image.open(path) as src:
                thumb=src.convert('RGBA')
                thumb.thumbnail((290,188))
                x,y=slot%4*300,slot//4*220
                draw.text((x+4,y+4),label,fill='white')
                im.paste(thumb,(x+4,y+25),thumb)
        im.save(OUT/f'{prefix}_{start//20+1:03d}.png')

def main():
    rows=list(csv.DictReader((ASSETS/'manifest.csv').open(encoding='utf-8-sig')))
    items=[]
    seen=set()
    for r in rows:
        if not r['path'].endswith('.png') or int(r['width'])<140 or int(r['height'])<70:
            continue
        path=ASSETS/r['path']
        if sha(path.read_bytes()) != r['sha256']:
            continue
        with Image.open(path) as im:
            key=(im.size,sha(im.convert('RGBA').tobytes()))
        if key in seen:
            continue
        seen.add(key)
        items.append((f"{r['type_name']} {int(r['number']):05d} L{r['loop']} C{r['cel']}",path))
    sheet_images(items,'selected_unchanged_review')
    print(f'unique large unchanged selected cells={len(items)}')

if __name__=='__main__':
    main()
