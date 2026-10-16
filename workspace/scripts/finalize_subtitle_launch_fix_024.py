"""Validate a launcher-only fix against its immutable pre-fix manifest."""
import hashlib
import json
from pathlib import Path

P = Path(__file__).resolve().parents[2]
B = P/'build/shivers_ko_full_024_20260905'
Q = P/'qa/subtitle_launch_fix_024_20260905'
BACK = P/'backups/runtime/subtitle_launch_024_before_20260905'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()

def main():
    old = json.loads((BACK/'build_manifest.json').read_text(encoding='utf-8-sig'))
    allowed = {'play.cmd','scummvm.ini'}
    for path, digest in old['files'].items():
        if path not in allowed:
            assert sha(B/path)==digest, path
    before = (BACK/'play.cmd').read_text(encoding='ascii')
    after = (B/'play.cmd').read_text(encoding='ascii')
    assert before.count('--subtitles')==1
    assert after.rstrip()==before.replace('--subtitles','--no-subtitles').rstrip()
    assert 'subtitles=true' not in (B/'scummvm.ini').read_text(encoding='ascii')
    assert '--no-subtitles' in (P/'workspace/scripts/build_shivers_all_assets.py').read_text(encoding='utf-8')
    manifest = dict(old)
    manifest['files'] = dict(old['files'])
    for path in allowed:
        manifest['files'][path] = sha(B/path)
    manifest['launcher_fix'] = {
        'date':'2026-09-05', 'native_english_subtitles':False,
        'external_korean_srt':'unchanged; rendered with native subtitles disabled',
        'custom_audio_captions':'unchanged; independent of native subtitle toggle',
        'changed_runtime_files':sorted(allowed),
        'baseline_manifest_sha256':sha(BACK/'build_manifest.json'),
        'qa':'qa/subtitle_launch_fix_024_20260905',
    }
    manifest['runtime_visual_qa'] = 'User confirmed Korean subtitle output after --no-subtitles test; full-game QA not claimed'
    (B/'build_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for path,digest in manifest['files'].items():
        assert sha(B/path)==digest, path
    rows = json.loads((P/old['snapshot']/'inputs.json').read_text(encoding='utf-8-sig'))
    current_pngs = {'workspace/graphics/english_assets/'+r['path']:r['working_sha256']
                    for r in rows if r['path'].endswith('.png')}
    assert len(current_pngs)==812
    saves_before = {
        '001':'A6BFA1B9C987C836E7A8CA695B9C9BAEAFC71CEFDA20C3D8965472ADCC7F933D',
        '002':'F45A70008BDE1B7565BA256AEC56511A1024519B585FB3F87CBAABEE33FB5303',
        '003':'CB4B074B1AAF013B78DE351A5302737FB6354D38519D587B249EE8ABA940DEA2',
        '004':'8FF7735F711DE839A946F5B64E0F4D7443510112F0D68ECC6699A60926660D16',
    }
    current_pngs.update({'work/scummvm_saves/full/shivers-ko-full.'+slot:digest for slot,digest in saves_before.items()})
    for path,digest in current_pngs.items():
        assert sha(P/path)==digest, path
    result = {'validation':'PASS','build_manifest_sha256':sha(B/'build_manifest.json'),
              'verified_manifest_files':len(manifest['files']),
              'unchanged_runtime_files':len(old['files'])-len(allowed),
              'protected_png_and_save_files':len(current_pngs),
              'changed_runtime_files':sorted(allowed),
              'user_visual_confirmation':'자막 출력 확인했어',
              'scope':'existing build 024 launcher/config only; no translation edits'}
    (Q/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    main()
