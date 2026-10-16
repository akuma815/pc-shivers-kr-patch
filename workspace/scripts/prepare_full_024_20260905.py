"""Register existing user blueprint translations and preserve saves for build 024.

No new translation or generated artwork. Only the PIC edit mask is transferred
to its same-content VIEW, retaining VIEW-specific source pixels outside it.
"""
import csv
import hashlib
import json
import shutil
from pathlib import Path
from PIL import Image
from extract_sci21_graphics import decode_cel, iter_pic_cels, make_png, merge_palette, parse_hunk_palette, u32

P = Path(__file__).resolve().parents[2]
A = P / 'workspace/graphics/english_assets'
S = P / 'backups/graphics/missing_reuse_original_024_20260905'
IDS = (12183, 12184, 12185)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()

def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames, list(reader)

def main():
    paths = [A/'manifest.csv', A/'english_graphics_catalog.csv', A/'overview_index.csv',
             P/'workspace/graphics/graphics_translation_queue_20260901.csv']
    tables = [read_csv(path) for path in paths]
    mf, mr = tables[0]; cf, cr = tables[1]; of, overview = tables[2]; qf, queue = tables[3]
    _, incoming = read_csv(S/'manifest.csv')
    incoming = [r for r in incoming if r['type_name']=='view' and int(r['number']) in IDS]
    assert len(incoming)==6
    assert not any(r['type_name']=='view' and int(r['number']) in IDS for r in cr), 'Already registered; do not rerun'
    assert all(not (A/r['path']).exists() for r in incoming), 'Existing user files must not be overwritten'
    base = merge_palette([(True,i,i,i) for i in range(256)], parse_hunk_palette((S/'raw/palette/00999.pal').read_bytes()))
    prepared = []
    for n in IDS:
        src = (A/f'raw/pic/{n}.p56').read_bytes()
        pixels, info = decode_cel(src, next(iter_pic_cels(src))[1])
        palette = merge_palette(base, parse_hunk_palette(src,u32(src,6)))
        original = make_png(pixels,info,palette,False).convert('RGBA')
        user_path = A/f'png/pic/{n}/cel_000.png'
        with Image.open(user_path) as im:
            translated = im.convert('RGBA')
        with Image.open(S/f'png/view/{n}/loop_000_cel_000.png') as im:
            view = im.convert('RGBA')
        assert original.size==translated.size==view.size==(528,345)
        old, user, dst = original.tobytes(), translated.tobytes(), view.tobytes()
        differences = sum(old[i:i+4]!=dst[i:i+4] for i in range(0,len(old),4))
        assert differences==(155 if n==12183 else 0), (n,differences)
        result = bytearray(dst)
        edits = 0
        for i in range(0,len(old),4):
            assert old[i+3]==user[i+3]==dst[i+3]==255
            if old[i:i+4]!=user[i:i+4]:
                result[i:i+4]=user[i:i+4]
                edits += 1
        assert edits > 0
        assert all(result[i:i+4]==dst[i:i+4] for i in range(0,len(old),4) if old[i:i+4]==user[i:i+4])
        prepared.append((n, Image.frombytes('RGBA',view.size,bytes(result)),dict(number=n,
            source_pic_sha256=sha(user_path), original_pic_view_difference_pixels=differences,
            translation_mask_pixels=edits, outside_translation_mask_changes=0,
            original_dimensions=[528,345], alpha_changes=0)))
    history = P/'backups/graphics/blueprint_catalog_before_024_20260905'
    history.mkdir(parents=True,exist_ok=False)
    before_pngs = {p.relative_to(A).as_posix():sha(p) for p in (A/'png').rglob('*.png')}
    (history/'existing_png_hashes.json').write_text(json.dumps(before_pngs,indent=2),encoding='utf-8')
    for path in paths:
        shutil.copy2(path,history/path.name)
    save_history = P/'backups/saves/before_full_024_20260905'
    save_history.mkdir(parents=True,exist_ok=False)
    save_files = sorted({p for root in (P/'work/scummvm_saves',P/'work/scummvm_runs',P/'build')
                         for p in root.rglob('shivers*.???') if p.is_file() and p.suffix[1:].isdigit()})
    save_records = []
    for source in save_files:
        dest = save_history/source.relative_to(P)
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,dest)
        assert sha(source)==sha(dest)
        save_records.append(dict(source=source.relative_to(P).as_posix(),backup=dest.relative_to(P).as_posix(),sha256=sha(source)))
    (save_history/'save_inventory.json').write_text(json.dumps(save_records,indent=2),encoding='utf-8')
    reports=[]
    category='books_scrapbook_diary_blueprints_and_notes'
    for row in incoming:
        dest=A/row['path']; dest.parent.mkdir(parents=True,exist_ok=True)
        if row['path'].startswith('raw/'):
            shutil.copy2(S/row['path'],dest)
            assert sha(dest)==row['sha256']
    for n,image,report in prepared:
        png=f'png/view/{n}/loop_000_cel_000.png'
        image.save(A/png,optimize=True); image.close()
        report['view_png_sha256']=sha(A/png)
        reports.append(report)
        raw=next(r for r in incoming if int(r['number'])==n and r['path'].startswith('raw/'))
        original=next(r for r in incoming if r['path']==png)
        cr.append(dict(zip(cf,['view',str(n),category,'translated_reused_manual_pic',raw['sha256'],raw['path'],f'png/view/{n}','1'])))
        overview.append(dict(path=png,text=category,label=f'V:{n}'))
        queue.append(dict(sequence=str(max(int(r['sequence']) for r in queue)+1),type_name='view',number=str(n),loop='0',cel='0',
            path=png,category=category,original_sha256=original['sha256'],current_sha256=report['view_png_sha256'],
            status='translated_reused_manual_pic',note='Existing user PIC translation reused for the missing VIEW; native dimensions, alpha and VIEW pixels outside PIC edit mask preserved; no new translation'))
    mr.extend(incoming)
    for path,(fields,rows) in zip(paths,tables):
        with path.open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=fields)
            writer.writeheader();writer.writerows(rows)
    assert all(sha(A/path)==h for path,h in before_pngs.items()), 'Pre-existing artwork changed'
    assert all(sha(P/r['source'])==r['sha256'] for r in save_records), 'Save changed'
    out=P/'qa/build_full_024_20260905';out.mkdir(parents=True,exist_ok=True)
    (out/'blueprint_transfer.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
    print(json.dumps(dict(blueprint_views_registered=3,existing_pngs_preserved=len(before_pngs),
                         total_pngs=len(list((A/'png').rglob('*.png'))),save_files_backed_up=len(save_records))))

if __name__=='__main__':
    main()
