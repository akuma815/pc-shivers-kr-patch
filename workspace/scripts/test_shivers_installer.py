"""Integration tests against disposable originals; never writes the user's saves."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import argparse

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / 'dist/Shivers_Korean_Patch_1.0_RC1'
QA = ROOT / 'qa/installer_rc1_20260905'
TEMP = ROOT / 'work/installer_qa_20260905'
ORIGINAL = ROOT / 'extracted/installer'
RESULTS = []


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest().upper()


def inventory(folder, exclude=False):
    return {p.relative_to(folder).as_posix():sha(p) for p in folder.rglob('*') if p.is_file()
            and (not exclude or not p.relative_to(folder).parts[0].startswith('_shivers_ko_backups'))}


def fixture(name):
    target = TEMP / name
    target.mkdir(parents=True)
    for p in ORIGINAL.rglob('*'):
        if p.is_file():
            dest = target / p.relative_to(ORIGINAL)
            dest.parent.mkdir(parents=True,exist_ok=True)
            os.link(p,dest)
    return target


def invoke(exe, *args, success=True):
    process = subprocess.run([str(exe),*(str(x) for x in args)],capture_output=True,timeout=240)
    log = process.stdout.decode('cp949',errors='replace')+process.stderr.decode('cp949',errors='replace')
    (QA / ('command_%02d.log' % len(RESULTS))).write_text(log,encoding='utf-8')
    RESULTS.append(dict(command=[str(exe),*(str(x) for x in args)],exit=process.returncode))
    if (process.returncode==0)!=success:
        raise AssertionError(f'Unexpected exit {process.returncode}: {log}')


def main():
    global PACKAGE, QA, TEMP
    parser=argparse.ArgumentParser()
    parser.add_argument('--package',default='Shivers_Korean_Patch_v1.0_RC1')
    parser.add_argument('--run',default='02')
    args=parser.parse_args()
    if not args.run.isalnum():
        raise ValueError('Invalid run name')
    PACKAGE=ROOT/'dist'/args.package
    QA=ROOT/('qa/installer_rc1_20260905_'+args.run)
    TEMP=ROOT/('work/installer_qa_20260905_'+args.run)
    QA.mkdir(parents=True,exist_ok=True)
    if TEMP.exists():
        raise FileExistsError('Use a new QA run; old evidence is immutable')
    TEMP.mkdir()
    original_before=inventory(ORIGINAL)
    saves_before=inventory(ROOT / 'work/scummvm_saves/full')
    exe=PACKAGE / 'ShiversKoreanPatch.exe'
    manifest=json.loads((ROOT/('work/distribution_'+args.package)/'manifest.json').read_text('utf-8'))
    target=fixture('한글 경로 & 100% 게임')
    saves=TEMP / '기존 저장 복사본'
    shutil.copytree(ROOT/'work/scummvm_saves/full',saves)
    invoke(exe,'--apply',target,'--saves',saves)
    for item in manifest['files']:
        assert sha(target/item['path'])==item['sha256'],item['path']
    assert sha(target/'ShiversKorean.ttf')==sha(Path('C:/Windows/Fonts/malgun.ttf'))
    assert not (target/'korean.fnt').exists()
    assert inventory(saves)==saves_before
    assert all(sha(target/p)==h for p,h in original_before.items())
    config=target/'_shivers_ko/scummvm.ini'
    config.write_text('[scummvm]\nsubtitles=true\nfullscreen=false\n[shivers-ko-full]\nsubtitles=true\nlanguage=en\n',encoding='ascii')
    invoke(target/'Shivers Korean.exe','--prepare-only')
    ini=config.read_text('utf-8')
    assert ini.count('subtitles=false')==2 and 'subtitles=true' not in ini
    assert 'fullscreen=false' in ini and 'language=ko' in ini
    state=(target/'_shivers_ko/install.json').read_bytes()
    invoke(exe,'--apply',target)
    assert (target/'_shivers_ko/install.json').read_bytes()==state
    assert inventory(saves)==saves_before
    bad=fixture('잘못된 원본')
    replacement=bad/'replacement.bin'
    replacement.write_bytes(b'not a supported RESMAP')
    os.replace(replacement,bad/'RESMAP.000') # break the test hardlink, never alter ORIGINAL
    bad_before=inventory(bad)
    invoke(exe,'--apply',bad,success=False)
    assert inventory(bad)==bad_before
    failure=fixture('실패 복구 시험')
    first=manifest['files'][0]['path']
    custom=failure/first
    custom.parent.mkdir(parents=True,exist_ok=True)
    custom.write_bytes(b'Previous user file preserved during rollback')
    failure_before=inventory(failure)
    invoke(exe,'--apply',failure,'--fail-after','5',success=False)
    assert inventory(failure,True)==failure_before
    assert not list(failure.glob('_shivers_ko_stage_*'))
    recovery=fixture('완료 패치 되돌리기')
    recover_before=inventory(recovery)
    invoke(exe,'--apply',recovery)
    backup=next((recovery/'_shivers_ko_backups').iterdir())
    changed=recovery/manifest['files'][0]['path']
    installed_bytes=changed.read_bytes()
    changed.write_bytes(b'Player edit after patch must not be overwritten by restore')
    edited_before=inventory(recovery)
    invoke(exe,'--restore',recovery,backup,success=False)
    assert inventory(recovery)==edited_before
    changed.write_bytes(installed_bytes)
    invoke(exe,'--restore',recovery,backup)
    assert inventory(recovery,True)==recover_before
    corrupt=TEMP/'손상 패키지'
    corrupt.mkdir()
    for name in ('ShiversKoreanPatch.exe','xdelta3decode.exe'):
        shutil.copy2(PACKAGE/name,corrupt/name)
    (corrupt/'patch.xdelta').write_bytes(b'damaged patch')
    invoke(corrupt/'ShiversKoreanPatch.exe','--apply',recovery,success=False)
    assert inventory(recovery,True)==recover_before
    assert inventory(ORIGINAL)==original_before
    assert inventory(ROOT/'work/scummvm_saves/full')==saves_before
    report=dict(status='PASS',commands=RESULTS, original_files=len(original_before),
                installed_files=len(manifest['files'])+2,saves_preserved=len(saves_before),
                unicode_space_ampersand_percent_path=True, runtime_glyph_qa='separate',
                wrong_revision_rejected=True, corrupted_package_rejected=True,
                repeated_apply=True, forced_subtitle_settings=True, private_preferences_preserved=True,
                injected_failure_rollback=True, completed_patch_restore=True,
                post_install_edits_protected_on_restore=True,
                windows_font_not_in_payload=True, legacy_bitmap_font_absent=True)
    (QA/'integration.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    try:
        main()
    except Exception:
        QA.mkdir(parents=True,exist_ok=True)
        (QA/'failed_commands.json').write_text(json.dumps(RESULTS,ensure_ascii=False,indent=2),encoding='utf-8')
        raise
