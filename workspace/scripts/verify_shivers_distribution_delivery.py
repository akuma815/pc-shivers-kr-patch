"""Validate the actual shipped ZIP and apply its extracted executable once."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[2]
NAME='Shivers_Korean_Patch_v1.0_RC1'
PACKAGE=ROOT/'dist'/NAME
QA=ROOT/'qa/installer_rc1_20260905_04'
WORK=ROOT/'work/installer_delivery_20260905'


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest().upper()


def main():
    integration=json.loads((QA/'integration.json').read_text('utf-8'))
    assert integration['status']=='PASS'
    package=json.loads((PACKAGE/'package_manifest.json').read_text('utf-8'))
    for name,h in package['files'].items():
        assert sha(PACKAGE/name)==h,name
    payload=json.loads((ROOT/'work'/('distribution_'+NAME)/'manifest.json').read_text('utf-8'))
    archive=ROOT/'dist'/(NAME+'.zip')
    if WORK.exists():
        raise FileExistsError(WORK)
    unpack=WORK/'배포 ZIP 압축 해제'
    unpack.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        names=set(z.namelist())
        expected={NAME+'/'+p.relative_to(PACKAGE).as_posix() for p in PACKAGE.rglob('*') if p.is_file()}
        assert names==expected
        for entry in z.infolist():
            assert not entry.filename.startswith(('/', '\\')) and '..' not in Path(entry.filename).parts
            with z.open(entry) as f:
                digest=hashlib.file_digest(f,'sha256').hexdigest().upper()
            assert digest==sha(PACKAGE/entry.filename[len(NAME)+1:])
            z.extract(entry,unpack)
    game=WORK/'신규 설치 게임'
    game.mkdir()
    original=ROOT/'extracted/installer'
    original_hashes={p.relative_to(original).as_posix():sha(p) for p in original.rglob('*') if p.is_file()}
    for relative in original_hashes:
        dest=game/relative
        dest.parent.mkdir(parents=True,exist_ok=True)
        os.link(original/relative,dest)
    exe=unpack/NAME/'ShiversKoreanPatch.exe'
    proc=subprocess.run([str(exe),'--apply',str(game)],capture_output=True,timeout=180)
    (QA/'zip_apply.log').write_bytes(proc.stdout+proc.stderr)
    assert proc.returncode==0,proc.stderr
    for e in payload['files']:
        assert sha(game/e['path'])==e['sha256'],e['path']
    for relative,digest in original_hashes.items():
        assert sha(original/relative)==sha(game/relative)==digest
    assert not (game/'korean.fnt').exists()
    assert sha(game/'ShiversKorean.ttf')==sha(Path(os.environ['WINDIR'])/'Fonts/malgun.ttf')
    assert subprocess.run([str(game/'Shivers Korean.exe'),'--prepare-only']).returncode==0
    assert (game/'_shivers_ko/scummvm.ini').read_text('utf-8').count('subtitles=false')==2
    report=dict(status='PASS',zip_sha256=sha(archive),zip_size=archive.stat().st_size,
                installer_sha256=sha(exe),patch_sha256=sha(PACKAGE/'patch.xdelta'),
                package_files=len(expected),installed_payload_files=len(payload['files']),
                zip_crc_and_entry_hashes=True,extracted_package_real_apply=True,
                original_files_unchanged=len(original_hashes),native_english_subtitles_disabled=True,
                local_malgun_matches_windows=True,legacy_bitmap_font_absent=True,
                package_is_release_candidate=True)
    (QA/'delivery.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':
    main()
