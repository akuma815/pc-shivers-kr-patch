"""Read-only product checks and saved QA records for the Malgun subtitle PoC.

Run --baseline before building/launching, then run without arguments after QA.
The baseline never overwrites existing evidence or user saves.
"""
import argparse
import hashlib
import json
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[2]
QA = ROOT / 'qa/malgun_poc_025_20260905'
BUILD = ROOT / 'build/shivers_ko_malgun_poc_025_20260905'
OLD = ROOT / 'build/shivers_ko_full_024_20260905'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest().upper()


def inventory():
    paths = list(OLD.rglob('*'))
    for directory in ('workspace/graphics/english_assets/png', 'workspace/translation',
                      'work/scummvm_saves/full'):
        paths.extend((ROOT / directory).rglob('*'))
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(paths) if p.is_file()}


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    QA.mkdir(parents=True, exist_ok=True)
    baseline = QA / 'preservation_before.json'
    if args.baseline:
        if baseline.exists():
            raise FileExistsError(baseline)
        save(baseline, inventory())
        print('Preservation baseline recorded')
        return
    expected = json.loads(baseline.read_text(encoding='utf-8'))
    actual = inventory()
    differences = [p for p in sorted(expected.keys() | actual.keys()) if expected.get(p) != actual.get(p)]
    manifest = json.loads((BUILD / 'build_manifest.json').read_text(encoding='utf-8'))
    mismatches = [p for p, digest in manifest['files'].items() if sha(BUILD / p) != digest]
    changed_graphics = [p.name for p in BUILD.iterdir() if p.suffix in ('.p56', '.v56')
                        and sha(p) != sha(OLD / p.name)]
    srts = sorted((BUILD / 'MOVIES').glob('*.srt'))
    changed_srts = [p.name for p in srts if sha(p) != sha(OLD / 'MOVIES' / p.name)]
    old_audio = (OLD / 'audio_subtitles_ko.csv').read_bytes().decode('cp949')
    audio = (BUILD / 'audio_subtitles_ko.csv').read_bytes().decode('utf-8')
    audio_equal = audio.replace('text_utf8', 'text_cp949', 1) == old_audio
    texts = [line.split(',', 2)[2] for line in audio.splitlines() if line and not line.startswith('#')]
    for srt in srts:
        texts.extend(srt.read_text(encoding='utf-8-sig').splitlines())
    characters = set(''.join(texts)) - {'\n', '\r', '\t', ' '}
    with TTFont(BUILD / 'ShiversKorean.ttf') as font:
        cmap = font.getBestCmap()
        missing = [f'U+{ord(char):04X}' for char in sorted(characters) if ord(char) not in cmap]
    font_same = sha(BUILD / 'ShiversKorean.ttf') == sha(Path('C:/Windows/Fonts/malgun.ttf'))
    report = {
        'build': BUILD.relative_to(ROOT).as_posix(),
        'preserved_file_count': len(expected), 'preservation_differences': differences,
        'manifest_file_count': len(manifest['files']), 'manifest_mismatches': mismatches,
        'changed_graphics_from_024': changed_graphics, 'changed_srts_from_024': changed_srts,
        'audio_text_timing_equal_after_encoding_conversion': audio_equal,
        'audio_entries': manifest['audio_subtitle_count'], 'movie_entries': manifest['movie_subtitle_count'],
        'required_characters': len(characters), 'missing_font_characters': missing,
        'font_matches_installed_malgun': font_same,
        'font_sha256': sha(BUILD / 'ShiversKorean.ttf'),
        'runtime_sha256': manifest['runtime']['runner']['sha256'],
        'runtime_visual_qa': 'record separately; file checks are not visual proof',
    }
    passed = not (differences or mismatches or changed_graphics or changed_srts or missing) and audio_equal and font_same
    report['static_status'] = 'PASS' if passed else 'FAIL'
    save(QA / 'verification.json', report)
    print(json.dumps(report, ensure_ascii=False))
    if not passed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
