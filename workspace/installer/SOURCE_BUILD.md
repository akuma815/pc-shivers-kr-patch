# Corresponding source and reproducibility

The bundled executable is custom ScummVM 2026.3.0 from commit
`fed42f2068dcafc6aafa1c28c77e4c88def74b66`, plus `shivers-malgun.patch`.
The complete unmodified source is `scummvm-2026.3.0.zip`.
Unzip it, then run `git apply --check ../shivers-malgun.patch` and
`git apply ../shivers-malgun.patch` from its `scummvm` directory.
No game data is needed to build the executable.

Use Visual Studio 2022 C++ Build Tools, its Windows SDK, CMake and MSBuild.
`build_scummvm_full_subtitle_layout_runner.ps1` documents the exact feature flags,
create_project invocation and MSBuild Release/x64 target. Its project-local
paths are a reference layout: provide a fresh ProjectRoot/SourceCache/OutputRoot
or reproduce the following commands using your own absolute source paths.

1. Set up vcpkg. The exact ports/scripts source is in `vcpkg-ports-and-scripts.zip`
   at baseline `61a6d90a8cecbbc4b2c926219e7f25e957ef7dbc`. Obtain the vcpkg executable
   using its bootstrap instructions. Use the adjacent vcpkg.json as manifest.
   The original source tarballs for the six runtime dependencies are supplied
   in dependencies/; set VCPKG_DOWNLOADS to that directory to reuse them.
2. Run `vcpkg install --triplet x64-windows --x-manifest-root=MANIFEST_DIRECTORY
   --x-install-root=LIBRARY_DIRECTORY`. The bundled status file records the exact
   installed dependency versions. The port patches and build recipes are in the
   vcpkg archive; each library's upstream build sources are in dependencies/.
3. `cmake -S SCUMMVM/devtools/create_project/cmake -B HELPER -G "Visual Studio 17 2022" -A x64`
   then `cmake --build HELPER --config Release`.
4. In a new MSVC build directory run HELPER/Release/create_project.exe with the
   ScummVM source path, `--msvc --msvc-version 17 --output-dir . --libs-path
   LIBRARY_DIRECTORY/x64-windows` and these flags:
   `--disable-zlib --disable-mad --disable-fribidi --disable-ogg --disable-vorbis
   --disable-flac --disable-png --disable-jpeg --disable-fluidsynth --disable-libcurl
   --disable-sdlnet --disable-mt32emu --disable-nasm --disable-opengl --disable-tinygl
   --disable-taskbar --disable-printing --disable-dialogs --disable-langdetect
   --disable-tts --disable-detection-full`.
5. `MSBuild scummvm.sln /m /p:Configuration=Release /p:Platform=x64 /t:scummvm`.
   Take Releasex64/scummvm.exe and the runtime DLLs from the library bin directory.

Installer and launcher source, embedded manifest and generated runtime identity
are in installer-source.zip. Compile Launcher.cs + RuntimeIdentity.cs with .NET
Framework 4.8 csc, /target:winexe /platform:x64 and references to System.Windows.Forms,
System.Drawing, System.Web.Extensions. Compile Patcher.cs with those plus
System.IO.Compression and System.IO.Compression.FileSystem, embedding manifest.json
as `manifest.json` and guide.txt as `guide.txt`. The packaging script shows exact
commands. Rebuilt binaries may differ with compiler/SDK versions; a different
runtime requires updating the launcher identity and payload manifest together.

CLI checks (same apply/recovery engine as GUI):
`ShiversKoreanPatch.exe --apply GAME_DIRECTORY [--saves SAVE_DIRECTORY]`
`ShiversKoreanPatch.exe --restore GAME_DIRECTORY BACKUP_DIRECTORY`
For fault testing on disposable game copies only, add `--fail-after 5` to apply.
`Shivers Korean.exe --prepare-only` regenerates its private subtitle settings
without starting the game. It does not bypass font/runtime checks.

Original game, user-translated graphics and Windows fonts are not source-code
licenses. The full localization asset build remains a separate, original-input
workflow; the installer manifest declares every file it may apply. xdelta is
decoded against the exact original RESSCI.000 and its decoded ZIP/hash/file list
are checked before any managed game file is replaced.
