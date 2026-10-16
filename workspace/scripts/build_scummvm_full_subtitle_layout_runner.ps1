[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$SourceCache = '',
    [string]$OutputRoot = '',
    [string]$LayoutId = '021'
)

$ErrorActionPreference = 'Stop'
if ($LayoutId -notin @('019', '021', '025', '026', '027')) { throw 'Unsupported layout ID' }

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
}
else {
    $ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
}
if ([string]::IsNullOrWhiteSpace($SourceCache)) {
    $SourceCache = Join-Path $ProjectRoot 'work\cache\scummvm-src-2026.3.0'
}
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $ProjectRoot "work\scummvm_full_subtitle_runner_$LayoutId"
}

$expectedCommit = 'fed42f2068dcafc6aafa1c28c77e4c88def74b66'
$patchRelative = "workspace/scummvm_audio_subtitles/scummvm_v2026.3.0_shivers_full_subtitles_layout_$LayoutId.patch"
$patchPath = Join-Path $ProjectRoot $patchRelative
$manifestRoot = Join-Path $ProjectRoot 'workspace\scummvm_full_subtitles'
$vcpkgExe = 'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\vcpkg\vcpkg.exe'
$cmakeExe = 'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe'
$msbuildExe = 'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\MSBuild.exe'
$tmpRoot = Join-Path $ProjectRoot 'work\tmp'
$sourceRoot = Join-Path $tmpRoot "scummvm_full_subtitle_src_build_$LayoutId"
$helperRoot = Join-Path $tmpRoot "create_project_full_subtitle_build_$LayoutId"
$msvcRoot = Join-Path $tmpRoot "scummvm_full_subtitle_msvc_build_$LayoutId"
$vcpkgRoot = Join-Path $ProjectRoot 'work\cache\vcpkg_full_subtitle_017'

foreach ($requiredFile in @($patchPath, $vcpkgExe, $cmakeExe, $msbuildExe)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required file not found: $requiredFile"
    }
}
if (-not (Test-Path -LiteralPath $SourceCache -PathType Container)) {
    throw "ScummVM source cache not found: $SourceCache"
}
if (Test-Path -LiteralPath $OutputRoot) {
    throw "Refusing to replace existing runner: $OutputRoot"
}
foreach ($temporaryPath in @($sourceRoot, $helperRoot, $msvcRoot)) {
    if (Test-Path -LiteralPath $temporaryPath) {
        throw "Refusing to use non-empty temporary path: $temporaryPath"
    }
    if ([System.IO.Path]::GetFullPath((Split-Path -Parent $temporaryPath)) -ne [System.IO.Path]::GetFullPath($tmpRoot)) {
        throw "Temporary path escaped work\tmp: $temporaryPath"
    }
}

$actualCommit = (& git -C $SourceCache rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $actualCommit -ne $expectedCommit) {
    throw "ScummVM source identity mismatch: $actualCommit"
}

$worktreeAdded = $false
try {
    & git -C $SourceCache worktree add --detach $sourceRoot $expectedCommit
    if ($LASTEXITCODE -ne 0) { throw 'git worktree add failed' }
    $worktreeAdded = $true

    & git -C $sourceRoot sparse-checkout set --cone audio backends base common devtools dists engines/sci graphics gui icons image math po video
    if ($LASTEXITCODE -ne 0) { throw 'git sparse-checkout failed' }
    & git -C $sourceRoot apply --check $patchPath
    if ($LASTEXITCODE -ne 0) { throw 'ScummVM source patch preflight failed' }
    & git -C $sourceRoot apply $patchPath
    if ($LASTEXITCODE -ne 0) { throw 'ScummVM source patch failed' }
    & git -C $sourceRoot diff --check
    if ($LASTEXITCODE -ne 0) { throw 'Patched ScummVM source has whitespace errors' }

    & $cmakeExe -S (Join-Path $sourceRoot 'devtools\create_project\cmake') -B $helperRoot -G 'Visual Studio 17 2022' -A x64
    if ($LASTEXITCODE -ne 0) { throw 'create_project CMake configure failed' }
    & $cmakeExe --build $helperRoot --config Release
    if ($LASTEXITCODE -ne 0) { throw 'create_project build failed' }

    & $vcpkgExe install --triplet x64-windows --x-manifest-root=$manifestRoot --x-install-root=$vcpkgRoot
    if ($LASTEXITCODE -ne 0) { throw 'SDL2 vcpkg install failed' }

    New-Item -ItemType Directory -Force -Path $msvcRoot | Out-Null
    $relativeSource = "..\scummvm_full_subtitle_src_build_$LayoutId"
    $createProjectExe = Join-Path $helperRoot 'Release\create_project.exe'
    $libraryRoot = Join-Path $vcpkgRoot 'x64-windows'
    $featureFlags = @(
        '--disable-zlib', '--disable-mad', '--disable-fribidi', '--disable-ogg',
        '--disable-vorbis', '--disable-flac', '--disable-png',
        '--disable-jpeg', '--disable-fluidsynth', '--disable-libcurl', '--disable-sdlnet',
        '--disable-mt32emu', '--disable-nasm', '--disable-opengl', '--disable-tinygl',
        '--disable-taskbar', '--disable-printing', '--disable-dialogs', '--disable-langdetect',
        '--disable-tts', '--disable-detection-full'
    )
    Push-Location $msvcRoot
    try {
        & $createProjectExe $relativeSource --msvc --msvc-version 17 --output-dir '.' --libs-path $libraryRoot @featureFlags
        if ($LASTEXITCODE -ne 0) { throw 'ScummVM Visual Studio project generation failed' }
        & $msbuildExe '.\scummvm.sln' /m /p:Configuration=Release /p:Platform=x64 /t:scummvm /v:minimal
        if ($LASTEXITCODE -ne 0) { throw 'ScummVM runner build failed' }
    }
    finally {
        Pop-Location
    }

    New-Item -ItemType Directory -Path $OutputRoot | Out-Null
    $runnerExe = Join-Path $OutputRoot "scummvm_shivers_ko_full_subtitles_$LayoutId.exe"
    $sdlDll = Join-Path $OutputRoot 'SDL2.dll'
    Copy-Item -LiteralPath (Join-Path $msvcRoot 'Releasex64\scummvm.exe') -Destination $runnerExe
    Get-ChildItem -LiteralPath (Join-Path $libraryRoot 'bin') -Filter '*.dll' -File |
        Copy-Item -Destination $OutputRoot

    $dependencyDlls = @(
        Get-ChildItem -LiteralPath $OutputRoot -Filter '*.dll' -File |
            Sort-Object Name |
            ForEach-Object {
                [ordered]@{
                    path = $_.Name
                    sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash
                    size = $_.Length
                }
            }
    )

    $manifest = [ordered]@{
        schema_version = 1
        scummvm_source_commit = $expectedCommit
        source_patch = $patchRelative
        source_patch_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $patchPath).Hash
        vcpkg_manifest_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $manifestRoot 'vcpkg.json')).Hash
        runner = [ordered]@{
            path = (Split-Path -Leaf $runnerExe)
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $runnerExe).Hash
            size = (Get-Item -LiteralPath $runnerExe).Length
        }
        sdl2 = [ordered]@{
            path = (Split-Path -Leaf $sdlDll)
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $sdlDll).Hash
            size = (Get-Item -LiteralPath $sdlDll).Length
        }
        dependency_dlls = $dependencyDlls
    }
    $manifestJson = $manifest | ConvertTo-Json -Depth 6
    [System.IO.File]::WriteAllText(
        (Join-Path $OutputRoot 'runner_manifest.json'),
        $manifestJson + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false)
    )
    $versionOutput = & $runnerExe --version
    if ($LASTEXITCODE -ne 0) { throw 'Built runner version check failed' }
    $versionOutput | Select-Object -First 1
    Write-Output "runner=$runnerExe"
}
finally {
    if ($worktreeAdded) {
        & git -C $SourceCache worktree remove --force $sourceRoot
    }
    foreach ($temporaryPath in @($helperRoot, $msvcRoot)) {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Recurse -Force
        }
    }
}
