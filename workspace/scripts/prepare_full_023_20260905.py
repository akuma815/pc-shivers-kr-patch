"""Preserve all known saves and promote six user-translated journal PNGs."""
import csv
import hashlib
import json
import shutil
from pathlib import Path
from PIL import Image

P=Path(__file__).resolve().parents[2]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest().upper()

def main():
    backup=P/'backups/saves/before_full_023_20260905'
    backup.mkdir(parents=True,exist_ok=False)
    shared=P/'work/scummvm_saves/full';shared.mkdir(parents=True,exist_ok=True)
    files=sorted([p for root in (P/'work/scummvm_saves',P/'work/scummvm_runs') for p in root.rglob('shivers*.???') if p.is_file() and p.suffix[1:].isdigit()],key=lambda p:p.stat().st_mtime,reverse=True)
    records=[]
    for src in files:
        dst=backup/src.relative_to(P)
        dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
        assert sha(src)==sha(dst)
        records.append({'source':src.relative_to(P).as_posix(),'backup':dst.relative_to(P).as_posix(),'sha256':sha(src)})
    existing={sha(p):p for p in shared.glob('shivers-ko-full.???')}
    for src,record in zip(files,records):
        digest=record['sha256']
        if digest in existing:
            dst=existing[digest]
        else:
            slot=next(i for i in range(1,1000) if not (shared/f'shivers-ko-full.{i:03d}').exists())
            dst=shared/f'shivers-ko-full.{slot:03d}'
            shutil.copy2(src,dst);assert sha(dst)==digest
            existing[digest]=dst
        record['shared_save']=dst.relative_to(P).as_posix()
    (backup/'save_inventory.json').write_text(json.dumps(records,indent=2)+'\n',encoding='utf-8')
    root=P/'workspace/graphics/english_assets'
    source=P/'workspace/graphics/journal_missing_20260905'
    with (root/'manifest.csv').open(encoding='utf-8-sig',newline='') as f:originals={r['path']:r['sha256'] for r in csv.DictReader(f)}
    q=P/'workspace/graphics/graphics_translation_queue_20260901.csv'
    with q.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f);fields=reader.fieldnames;rows=list(reader)
    history=P/'backups/graphics/journal_before_apply_023_20260905';history.mkdir(parents=True,exist_ok=False)
    shutil.copy2(q,history/q.name)
    prepared=[]
    for n in (37253,37255,37256,37260,37262,37265):
        rel=f'png/view/{n}/loop_000_cel_000.png';src=source/rel;dst=root/rel
        assert sha(dst)==originals[rel],f'Canonical file was independently edited: {dst}'
        assert sha(src)!=originals[rel],f'Translation unchanged: {src}'
        with Image.open(src) as im, Image.open(dst) as before:
            assert im.size==before.size==(528,345)
            assert im.convert('RGBA').getchannel('A').tobytes()==before.convert('RGBA').getchannel('A').tobytes()
        prepared.append((n,rel,src,dst))
    for n,rel,src,dst in prepared:
        b=history/rel;b.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dst,b)
        shutil.copy2(src,dst);assert sha(src)==sha(dst)
        row=next(r for r in rows if r['type_name']=='view' and int(r['number'])==n)
        row.update(current_sha256=sha(dst),status='translated_working_manual_complete_20260905',note='User journal translation copied from journal_missing_20260905; original dimensions and alpha preserved; included in 023')
    with q.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    print(json.dumps({'save_files_backed_up':len(files),'shared_slots':[r['shared_save'] for r in records],'journal_translations_applied':len(prepared)}))

if __name__=='__main__':main()
