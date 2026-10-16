"""Package the verified 025 product as an original-checked xdelta GUI installer.

No original game/movie, Windows font or legacy bitmap font is packaged.
The product build is checked against its complete manifest before packaging.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'workspace/installer'
CSC = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
XDELTA = ROOT.parents[1] / 'tools/xdelta3-3.2.0-windows-x86_64'
COMMIT = 'fed42f2068dcafc6aafa1c28c77e4c88def74b66'
VCPKG_COMMIT = '61a6d90a8cecbbc4b2c926219e7f25e957ef7dbc'


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest().upper()


def run(*args):
    subprocess.run([str(x) for x in args], check=True)


def record(path, name):
    return dict(path=name, size=path.stat().st_size, sha256=sha(path))


def zip_files(destination, files):
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, path in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 9, 5, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, path.read_bytes())


def compile_exe(output, files, resources=()):
    run(CSC, '/nologo', '/target:winexe', '/platform:x64', '/optimize+',
        '/r:System.Windows.Forms.dll', '/r:System.Drawing.dll', '/r:System.Web.Extensions.dll',
        '/r:System.IO.Compression.dll', '/r:System.IO.Compression.FileSystem.dll',
        '/out:' + str(output), *('/resource:' + str(p) + ',' + name for p, name in resources), *files)


def finalize(out, temp, product_sha256, runner_hash):
    """Also used to rebuild installer code without regenerating unchanged deltas."""
    codec_files = {
        'licenses/xz-COPYING.txt': 'https://raw.githubusercontent.com/tukaani-project/xz/v5.8.3/COPYING',
        'licenses/xz-0BSD.txt': 'https://raw.githubusercontent.com/tukaani-project/xz/v5.8.3/COPYING.0BSD',
        'licenses/BLAKE3-Apache.txt': 'https://raw.githubusercontent.com/BLAKE3-team/BLAKE3/1.8.5/LICENSE_A2',
        'licenses/BLAKE3-CC0.txt': 'https://raw.githubusercontent.com/BLAKE3-team/BLAKE3/1.8.5/LICENSE_CC0',
        'sources/dependencies/xz-5.8.3.tar.gz': 'https://codeload.github.com/tukaani-project/xz/tar.gz/refs/tags/v5.8.3',
        'sources/dependencies/BLAKE3-1.8.5.tar.gz': 'https://codeload.github.com/BLAKE3-team/BLAKE3/tar.gz/refs/tags/1.8.5',
    }
    for relative, url in codec_files.items():
        destination = out / relative
        if not destination.exists():
            with urllib.request.urlopen(url) as response:
                destination.write_bytes(response.read())
    compile_exe(out / 'ShiversKoreanPatch.exe', [SOURCE / 'Patcher.cs'],
                [(temp / 'manifest.json', 'manifest.json'), (SOURCE / 'guide.txt', 'guide.txt')])
    zip_files(out / 'sources/installer-source.zip',
              {**{p.name: p for p in SOURCE.iterdir() if p.is_file()},
               'RuntimeIdentity.cs': temp / 'RuntimeIdentity.cs', 'manifest.json': temp / 'manifest.json',
               'build_shivers_distribution.py': Path(__file__)})
    manifest_name = 'package_manifest.json'
    report = dict(package=out.name, product_manifest_sha256=product_sha256,
                  files={p.relative_to(out).as_posix():sha(p) for p in sorted(out.rglob('*'))
                         if p.is_file() and p.name != manifest_name},
                  windows_fonts_in_package=False, original_game_files_in_package=False,
                  source_commit=COMMIT, runtime_sha256=runner_hash)
    (out / manifest_name).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    zip_path = out.parent / (out.name + '.zip')
    zip_files(zip_path, {out.name + '/' + p.relative_to(out).as_posix():p for p in out.rglob('*') if p.is_file()})
    print(json.dumps({'package':str(out), 'zip':str(zip_path), 'patch_bytes':(out/'patch.xdelta').stat().st_size}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--name', default='Shivers_Korean_Patch_1.0_RC1')
    parser.add_argument('--build', default='build/shivers_ko_malgun_poc_025_20260905')
    parser.add_argument('--finalize-existing', action='store_true')
    args = parser.parse_args()
    out = ROOT / 'dist' / args.name
    if out.parent.resolve() != (ROOT / 'dist').resolve():
        raise ValueError('Use a new direct child of dist')
    if args.finalize_existing:
        old = json.loads((out / 'package_manifest.json').read_text(encoding='utf-8'))
        for relative, digest in old['files'].items():
            if sha(out / relative) != digest:
                raise ValueError('Existing package was changed: ' + relative)
        finalize(out, ROOT / 'work' / ('distribution_' + args.name), old['product_manifest_sha256'], old['runtime_sha256'])
        return
    if out.exists():
        raise FileExistsError(out)
    build = (ROOT / args.build).resolve()
    m = json.loads((build / 'build_manifest.json').read_text(encoding='utf-8'))
    for rel, digest in m['files'].items():
        if sha(build / rel) != digest:
            raise ValueError(f'Product identity changed: {rel}')
    if m['runtime']['runner']['sha256'] != '350CD093E1C82D350C3055B36852A5D82ABC6A5C3B62783D03E4BB11E3ADE326':
        raise ValueError('The user-verified Malgun runner is required')
    out.mkdir()
    temp = ROOT / 'work' / ('distribution_' + args.name)
    temp.mkdir()
    generated = temp / 'RuntimeIdentity.cs'
    runner = m['runtime']['runner']
    generated.write_text('internal static class RuntimeIdentity { public const string Name = '
                         + json.dumps(runner['path']) + '; public const string Hash = '
                         + json.dumps(runner['sha256']) + '; }\n', encoding='utf-8')
    launcher = temp / 'Shivers Korean.exe'
    compile_exe(launcher, [SOURCE / 'Launcher.cs', generated])
    files = {p.name: p for p in build.iterdir() if p.suffix in ('.p56', '.v56')}
    files.update({'MOVIES/' + p.name: p for p in (build / 'MOVIES').glob('*.srt')})
    files['audio_subtitles_ko.csv'] = build / 'audio_subtitles_ko.csv'
    for p in (build / 'runtime').iterdir():
        if p.suffix.lower() in ('.exe', '.dll'):
            files['_shivers_ko/runtime/' + p.name] = p
    files['Shivers Korean.exe'] = launcher
    for name, contents in {
        'play.cmd': '@echo off\r\n"%~dp0Shivers Korean.exe"\r\n',
        'continue.cmd': '@echo off\r\n"%~dp0Shivers Korean.exe" --continue\r\n',
    }.items():
        p = temp / name
        p.write_bytes(contents.encode('ascii'))
        files[name] = p
    licenses = out / 'licenses'
    licenses.mkdir()
    cache = ROOT / 'work/cache/scummvm-src-2026.3.0'
    license_text = subprocess.check_output(['git', '-C', str(cache), 'show', 'HEAD:COPYING'])
    (licenses / 'ScummVM-GPL-3.0.txt').write_bytes(license_text)
    share = ROOT / 'work/cache/vcpkg_full_subtitle_017/x64-windows/share'
    for dep in ('brotli', 'bzip2', 'freetype', 'libpng', 'sdl2', 'zlib'):
        shutil.copy2(share / dep / 'copyright', licenses / (dep + '.txt'))
    with urllib.request.urlopen('https://raw.githubusercontent.com/jmacd/xdelta/v3.2.0/xdelta3/LICENSE') as response:
        (licenses / 'xdelta-3.2.0.txt').write_bytes(response.read())
    shutil.copy2(SOURCE / 'LICENSE.txt', licenses / 'Installer-MIT.txt')
    shutil.copy2(SOURCE / 'guide.txt', out / '사용 안내.txt')
    shutil.copy2(SOURCE / 'NOTICE.txt', out / 'NOTICE.txt')
    files['_shivers_ko/사용 안내.txt'] = out / '사용 안내.txt'
    files['_shivers_ko/NOTICE.txt'] = out / 'NOTICE.txt'
    for p in licenses.iterdir():
        files['_shivers_ko/licenses/' + p.name] = p
    assert not any(Path(n).suffix.lower() in ('.ttf', '.fnt', '.vmd', '.000', '.iso') for n in files)
    archive = temp / 'payload.zip'
    zip_files(archive, files)
    env = dict(os.environ)
    env.pop('XDELTA', None)
    subprocess.run([str(XDELTA / 'xdelta3.exe'), '-e', '-9', '-A', '-s', str(build / 'RESSCI.000'),
                    str(archive), str(out / 'patch.xdelta')], check=True, env=env)
    # Upstream's tiny decode-only binary lacks the LZMA secondary codec.
    # Ship the full self-contained binary under our private decoder name.
    shutil.copy2(XDELTA / 'xdelta3.exe', out / 'xdelta3decode.exe')
    mandatory = {'RESSCI.000', 'RESMAP.000', '65535.MAP', 'RESMDT.000', 'RESOURCE.SFX'}
    original_files = [record(build / e['path'], e['path']) for e in m['original_files']
                      if e['path'] in mandatory or e['path'].startswith('MOVIES/')]
    manifest = dict(version='1.0 RC1', payload_sha256=sha(out / 'patch.xdelta'),
                    archive_sha256=sha(archive), decoder_sha256=sha(out / 'xdelta3decode.exe'),
                    files=[record(p, name) for name, p in sorted(files.items())], originals=original_files)
    manifest_path = temp / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    compile_exe(out / 'ShiversKoreanPatch.exe', [SOURCE / 'Patcher.cs'],
                [(manifest_path, 'manifest.json'), (SOURCE / 'guide.txt', 'guide.txt')])
    # Complete unmodified upstream source plus exact patch and build machinery.
    sources = out / 'sources'
    sources.mkdir()
    run('git', '-C', cache, 'archive', '--format=zip', '--prefix=scummvm/',
        '--output=' + str(sources / 'scummvm-2026.3.0.zip'), COMMIT)
    shutil.copy2(ROOT / m['runtime']['source_patch'], sources / 'shivers-malgun.patch')
    shutil.copy2(ROOT / 'workspace/scripts/build_scummvm_full_subtitle_layout_runner.ps1', sources)
    shutil.copy2(ROOT / 'workspace/scummvm_full_subtitles/vcpkg.json', sources)
    shutil.copy2(SOURCE / 'SOURCE_BUILD.md', sources)
    shutil.copy2(ROOT / 'work/cache/vcpkg_full_subtitle_017/vcpkg/status', sources / 'dependency-versions.txt')
    # Include the exact dependency source archives and vcpkg port patches, not just URLs.
    downloads = Path(os.environ['LOCALAPPDATA']) / 'vcpkg/downloads'
    dependencies = ('bzip2-1.0.8.tar.gz', 'freetype-freetype-VER-2-14-3.tar.gz',
                    'google-brotli-v1.2.0.tar.gz', 'libsdl-org-SDL-release-2.32.10.tar.gz',
                    'madler-zlib-v1.3.2.tar.gz', 'pnggroup-libpng-v1.6.58.tar.gz')
    (sources / 'dependencies').mkdir()
    for name in dependencies:
        shutil.copy2(downloads / name, sources / 'dependencies' / name)
    registry = Path(os.environ['LOCALAPPDATA']) / 'vcpkg/registries/git'
    run('git', '-C', registry, 'archive', '--format=zip', '--prefix=vcpkg/',
        '--output=' + str(sources / 'vcpkg-ports-and-scripts.zip'), VCPKG_COMMIT)
    with urllib.request.urlopen('https://github.com/jmacd/xdelta/releases/download/v3.2.0/xdelta3-3.2.0.tar.gz') as response:
        (sources / 'xdelta-3.2.0.tar.gz').write_bytes(response.read())
    zip_files(sources / 'installer-source.zip',
              {**{p.name: p for p in SOURCE.iterdir() if p.is_file()},
               'RuntimeIdentity.cs': generated, 'manifest.json': manifest_path,
               'build_shivers_distribution.py': Path(__file__)})
    finalize(out, temp, sha(build / 'build_manifest.json'), runner['sha256'])


if __name__ == '__main__':
    main()
