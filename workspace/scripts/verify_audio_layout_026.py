"""Check the isolated audio-position candidate without modifying game or save data."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QA = ROOT / 'qa/audio_layout_026_20260906'
OLD = ROOT / 'build/shivers_ko_malgun_poc_025_20260905'
BUILD = ROOT / 'build/shivers_ko_audio_layout_026_20260906'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest().upper()


def dump(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def inventory():
    paths = []
    for directory in ('workspace/graphics/english_assets/png', 'workspace/translation',
                      'work/scummvm_saves/full'):
        paths.extend((ROOT / directory).rglob('*'))
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(paths) if p.is_file()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    QA.mkdir(parents=True, exist_ok=True)
    baseline = QA / 'preservation_before.json'
    if args.baseline:
        if baseline.exists():
            raise FileExistsError(baseline)
        dump(baseline, inventory())
        print('Preservation baseline recorded')
        return
    before = json.loads(baseline.read_text(encoding='utf-8'))
    after = inventory()
    differences = [p for p in sorted(before.keys() | after.keys()) if before.get(p) != after.get(p)]
    manifest = json.loads((BUILD / 'build_manifest.json').read_text(encoding='utf-8'))
    bad_files = [p for p, digest in manifest['files'].items() if sha(BUILD / p) != digest]
    protected = list(BUILD.glob('*.p56')) + list(BUILD.glob('*.v56'))
    protected += list((BUILD / 'MOVIES').glob('*.srt'))
    protected += [BUILD / 'audio_subtitles_ko.csv', BUILD / 'ShiversKorean.ttf']
    changed_content = [p.relative_to(BUILD).as_posix() for p in protected
                       if sha(p) != sha(OLD / p.relative_to(BUILD))]
    # Verify that the entire source patch differs only in the reviewed position block.
    patch_dir = ROOT / 'workspace/scummvm_audio_subtitles'
    old_patch = (patch_dir / 'scummvm_v2026.3.0_shivers_full_subtitles_layout_025.patch').read_text(encoding='utf-8')
    new_patch = (patch_dir / 'scummvm_v2026.3.0_shivers_full_subtitles_layout_026.patch').read_text(encoding='utf-8')
    old_line = '+\t_audioSubtitleRect = Common::Rect(4, _currentBuffer.h - 20 - rectHeight, _currentBuffer.w - 4, _currentBuffer.h - 20);'
    new_block = '''+\t// Shivers' 640x480 gameplay view ends near y=360. Keep captions in the
+\t// black band below it, above the inventory, with a stable top on every page.
+\tconst int subtitleTop = MIN(366, MAX(0, _currentBuffer.h - rectHeight));
+\t_audioSubtitleRect = Common::Rect(4, subtitleTop, _currentBuffer.w - 4, subtitleTop + rectHeight);'''
    def normalize(text):
        return '\n'.join(line for line in text.splitlines()
                         if not line.startswith(('index ', '@@ ')))
    source_only_position = (old_patch.count(old_line) == 1 and new_patch.count(new_block) == 1
                           and normalize(new_patch.replace(new_block, old_line)) == normalize(old_patch))
    rectangles = []
    for lines in (1, 2):
        height = lines * 16 + 4
        top = min(366, max(0, 480 - height))
        rectangles.append({'lines': lines, 'old_top': 480 - 20 - height,
                           'new_top': top, 'new_bottom_exclusive': top + height})
    geometry_ok = all(r['new_top'] >= 360 and r['new_bottom_exclusive'] <= 414 for r in rectangles)
    passed = not (differences or bad_files or changed_content) and source_only_position and geometry_ok
    report = {'build': str(BUILD.relative_to(ROOT)), 'preserved_file_count': len(before),
              'preservation_differences': differences, 'manifest_mismatches': bad_files,
              'protected_content_files': len(protected), 'changed_content': changed_content,
              'source_change_is_only_audio_position': source_only_position,
              'native_rectangles': rectangles, 'geometry_bounds_check': geometry_ok,
              'geometry_basis': 'User tape-recorder screenshot: scene ends near native y360, lower UI starts near y414; not a dynamic scene detector.',
              'movie_subtitle_count': manifest['movie_subtitle_count'],
              'audio_subtitle_count': manifest['audio_subtitle_count'],
              'runner_sha256': manifest['runtime']['runner']['sha256'],
              'source_patch_sha256': manifest['runtime']['source_patch_sha256'],
              'static_status': 'PASS' if passed else 'FAIL',
              'runtime_visual_qa': 'PENDING: tape-recorder 30601/30611 paging, stop/exit clearing, and registration voice; existing running game was not controlled.'}
    dump(QA / 'verification.json', report)
    print(json.dumps(report, ensure_ascii=False))
    if not passed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
