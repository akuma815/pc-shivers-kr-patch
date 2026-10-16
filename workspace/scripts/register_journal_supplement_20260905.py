"""Register the six omitted journal views without replacing user artwork."""
import csv
import hashlib
import shutil
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
ROOT = PROJECT / 'workspace/graphics/english_assets'
SUPPLEMENT = PROJECT / 'workspace/graphics/journal_missing_20260905'
NUMBERS = {37253, 37255, 37256, 37260, 37262, 37265}
CATEGORY = 'books_scrapbook_diary_blueprints_and_notes'


def read(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames, list(reader)


def write(path, fields, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main():
    manifest = ROOT / 'manifest.csv'
    catalog = ROOT / 'english_graphics_catalog.csv'
    queue = PROJECT / 'workspace/graphics/graphics_translation_queue_20260901.csv'
    mf, mr = read(manifest)
    cf, cr = read(catalog)
    qf, qr = read(queue)
    _, incoming = read(SUPPLEMENT / 'manifest.csv')
    incoming = [r for r in incoming if r['type_name']=='view' and int(r['number']) in NUMBERS]
    assert len(incoming)==12
    if any(r['type_name']=='view' and int(r['number']) in NUMBERS for r in cr):
        raise ValueError('Supplement already registered; refusing to modify artwork')
    for row in incoming:
        assert not (ROOT / row['path']).exists(), row['path']
        assert sha(SUPPLEMENT / row['path'])==row['sha256']
    backup = PROJECT / 'backups/graphics/journal_catalog_before_20260905'
    backup.mkdir(parents=True, exist_ok=False)
    for path in (manifest, catalog, queue):
        shutil.copy2(path, backup / path.name)
    for row in incoming:
        dst = ROOT / row['path']
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SUPPLEMENT / row['path'], dst)
        assert sha(dst)==row['sha256']
    mr.extend(incoming)
    for number in sorted(NUMBERS):
        raw = next(r for r in incoming if int(r['number'])==number and r['path'].startswith('raw/'))
        png = next(r for r in incoming if int(r['number'])==number and r['path'].endswith('.png'))
        entry = dict(zip(cf, ['view',str(number),CATEGORY,'english_visible_manual_review_2026-09-05',raw['sha256'],raw['path'],f'png/view/{number:05d}','1']))
        cr.append(entry)
        qr.append({'sequence':str(max(int(r['sequence']) for r in qr)+1),
                   'type_name':'view','number':str(number),'loop':'0','cel':'0',
                   'path':png['path'],'category':CATEGORY,'original_sha256':png['sha256'],
                   'current_sha256':png['sha256'],'status':'untranslated_newly_extracted',
                   'note':'Original journal page omitted from initial selection; screenshot confirmed 2026-09-05; manual translation pending'})
    write(manifest,mf,mr)
    write(catalog,cf,cr)
    write(queue,qf,qr)
    assert len(list((ROOT/'png').rglob('*.png')))==802
    print('registered_views=6 png_total=802; existing artwork preserved; translation pending')


if __name__=='__main__':
    main()
