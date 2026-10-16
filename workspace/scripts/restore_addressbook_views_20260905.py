"""Transfer user PIC translations to omitted, equivalent address-book VIEWs.

Preserve VIEW-specific pixels wherever the user did not edit the PIC. No resize,
new artwork, or text generation. Fail on unexpected source differences.
"""
import csv
import hashlib
import json
import shutil
from pathlib import Path
from PIL import Image
from extract_sci21_graphics import decode_cel,iter_pic_cels,make_png,merge_palette,parse_hunk_palette,u32

P=Path(__file__).resolve().parents[2]
A=P/'workspace/graphics/english_assets'
S=P/'backups/graphics/addressbook_original_20260905'
IDS=(10205,10206,10207,10208,10209,10211,10212)
CAT='books_scrapbook_diary_blueprints_and_notes'

def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:
        r=csv.DictReader(f)
        return r.fieldnames,list(r)

def write(path,fields,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest().upper()

def main():
    paths=[A/'manifest.csv',A/'english_graphics_catalog.csv',A/'overview_index.csv',P/'workspace/graphics/graphics_translation_queue_20260901.csv']
    tables=[read(p) for p in paths]
    mf,mr=tables[0];cf,cr=tables[1];of,orr=tables[2];qf,qr=tables[3]
    _,incoming=read(S/'manifest.csv')
    incoming=[r for r in incoming if r['type_name']=='view']
    assert len(incoming)==14
    assert not any(r['type_name']=='view' and int(r['number']) in IDS for r in cr)
    base=merge_palette([(True,i,i,i) for i in range(256)],parse_hunk_palette((S/'raw/palette/00999.pal').read_bytes()))
    prepared=[]
    for n in IDS:
        src=(A/f'raw/pic/{n}.p56').read_bytes()
        pixels,info=decode_cel(src,next(iter_pic_cels(src))[1])
        pal=merge_palette(base,parse_hunk_palette(src,u32(src,6)))
        original=make_png(pixels,info,pal,True).convert('RGBA')
        with Image.open(A/f'png/pic/{n}/cel_000.png') as im:translated=im.convert('RGBA')
        with Image.open(S/f'png/view/{n}/loop_000_cel_000.png') as im:view=im.convert('RGBA')
        assert original.size==translated.size==view.size==(528,345)
        a,b,c=original.tobytes(),translated.tobytes(),view.tobytes()
        diff=sum(a[i:i+4]!=c[i:i+4] for i in range(0,len(a),4))
        assert diff==(691 if n==10207 else 0),(n,diff)
        output=bytearray(c);edits=0
        for i in range(0,len(a),4):
            assert b[i+3]==c[i+3]==255
            if a[i:i+4]!=b[i:i+4]:output[i:i+4]=b[i:i+4];edits+=1
        assert edits
        assert all(output[i:i+4]==c[i:i+4] for i in range(0,len(a),4) if a[i:i+4]==b[i:i+4])
        prepared.append((n,Image.frombytes('RGBA',view.size,bytes(output)),{'number':n,'source_pic_view_difference_pixels':diff,'translation_mask_pixels':edits,'outside_translation_mask_changes':0,'translation_pic_sha256':sha(A/f'png/pic/{n}/cel_000.png')}))
    for row in incoming:assert not (A/row['path']).exists()
    backup=P/'backups/graphics/addressbook_catalog_before_20260905';backup.mkdir(parents=True,exist_ok=False)
    for p in paths:shutil.copy2(p,backup/p.name)
    for row in incoming:
        dst=A/row['path'];dst.parent.mkdir(parents=True,exist_ok=True)
        if row['path'].startswith('raw/'):
            shutil.copy2(S/row['path'],dst);assert sha(dst)==row['sha256']
    reports=[]
    for n,image,report in prepared:
        png=f'png/view/{n}/loop_000_cel_000.png';image.save(A/png,optimize=True);image.close()
        report['view_png_sha256']=sha(A/png);reports.append(report)
        raw=next(r for r in incoming if int(r['number'])==n and r['path'].startswith('raw/'))
        original=next(r for r in incoming if r['path']==png)
        cr.append(dict(zip(cf,['view',str(n),CAT,'english_visible_manual_review_2026-09-05',raw['sha256'],raw['path'],f'png/view/{n}','1'])))
        orr.append({'path':png,'text':CAT,'label':f'V:{n}'})
        qr.append({'sequence':str(max(int(r['sequence']) for r in qr)+1),'type_name':'view','number':str(n),'loop':'0','cel':'0','path':png,'category':CAT,'original_sha256':original['sha256'],'current_sha256':report['view_png_sha256'],'status':'translated_reused_manual_pic','note':'User PIC translation transferred at native dimensions; source VIEW-specific pixels preserved outside PIC edit mask; runtime address-book page QA pending'})
    mr.extend(incoming)
    for path,(fields,rows) in zip(paths,tables):write(path,fields,rows)
    out=P/'qa/addressbook_fix_20260905';out.mkdir(parents=True,exist_ok=True)
    (out/'transfer.json').write_text(json.dumps(reports,indent=2)+'\n',encoding='utf-8')
    print('addressbook_views=7; preserved_original_dimensions=528x345; outside_translation_mask_changes=0; total_png='+str(len(list((A/'png').rglob('*.png')))))

if __name__=='__main__':main()
