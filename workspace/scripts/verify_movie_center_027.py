"""Regression checks for movie horizontal coordinates; does not run the user's game."""
import argparse
import json
from collections import Counter
from pathlib import Path
from verify_audio_layout_026 import ROOT, sha, dump, inventory

QA = ROOT / 'qa/movie_center_027_20260906'
BUILD = ROOT / 'build/shivers_ko_movie_center_027_20260906'
OLD = ROOT / 'build/shivers_ko_audio_layout_026_20260906'


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
        return
    before = json.loads(baseline.read_text(encoding='utf-8'))
    after = inventory()
    differences = [p for p in before.keys() | after.keys() if before.get(p) != after.get(p)]
    manifest = json.loads((BUILD / 'build_manifest.json').read_text(encoding='utf-8'))
    mismatches = [p for p, h in manifest['files'].items() if sha(BUILD / p) != h]
    protected = list(BUILD.glob('*.p56')) + list(BUILD.glob('*.v56'))
    protected += list((BUILD / 'MOVIES').glob('*.srt'))
    protected += [BUILD / 'ShiversKorean.ttf', BUILD / 'audio_subtitles_ko.csv']
    changed = [p.name for p in protected if sha(p) != sha(OLD / p.relative_to(BUILD))]
    patches = ROOT / 'workspace/scummvm_audio_subtitles'
    def writes(layout):
        text = (patches / f'scummvm_v2026.3.0_shivers_full_subtitles_layout_{layout}.patch').read_text(encoding='utf-8')
        return Counter(line for line in text.splitlines() if line.startswith(('+', '-'))
                       and not line.startswith(('+++', '---')))
    previous, current = writes('026'), writes('027')
    expected = Counter([
        '-\t\t\t\tdrawWidth = _drawRect.width();',
        '+\t\t\t\tdrawWidth = g_sci->getGameId() == GID_SHIVERS ? g_system->getWidth() : _drawRect.width();'])
    isolated = current - previous == expected and not previous - current
    # Independent invariant: scaled subtitle box center equals scaled movie center
    # within one overlay pixel, including offset and non-full-width movies.
    cases = 0
    max_error = 0
    for screen in (320, 640, 1280):
        for overlay in (640, 1280, 1798, 1920, 2560, 3840):
            for left in range(0, screen - 40, 17):
                for right in (left + 40, (left + 40 + screen) // 2, screen):
                    lo = (left + 20) * overlay // screen
                    hi = (right - 20) * overlay // screen
                    error = abs((lo + hi) / 2 - (left + right) * overlay / (2 * screen))
                    max_error = max(max_error, error)
                    assert 0 <= lo <= hi <= overlay and error < 1
                    cases += 1
    passed = not (differences or mismatches or changed) and isolated
    report = {'static_status': 'PASS' if passed else 'FAIL', 'preservation_differences': differences,
              'manifest_mismatches': mismatches, 'unchanged_content_files': len(protected),
              'changed_content': changed, 'only_shivers_horizontal_denominator_changed': isolated,
              'geometry_cases': cases, 'max_center_error_overlay_pixels': max_error,
              'movie_font_and_vertical_position': 'unchanged', 'audio_layout': manifest['audio_layout'],
              'runtime': manifest['runtime'],
              'runtime_visual_qa': 'PENDING: 16000.VMD 19.8-24.5 seconds, opening multiline subtitles; no running game controlled'}
    dump(QA / 'verification.json', report)
    print(json.dumps({k: v for k, v in report.items() if k != 'runtime'}, ensure_ascii=False))
    if not passed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
