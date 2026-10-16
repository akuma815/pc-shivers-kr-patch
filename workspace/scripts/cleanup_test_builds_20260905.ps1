$ErrorActionPreference = 'Stop'
$project = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$latest = Join-Path $project 'build/shivers_ko_full_020_20260905'
$manifest = Get-Content -Raw -Encoding utf8 -LiteralPath (Join-Path $latest 'build_manifest.json') | ConvertFrom-Json
foreach ($file in $manifest.files.PSObject.Properties) {
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $latest $file.Name)).Hash -ne $file.Value) {
        throw "Latest build validation failed: $($file.Name)"
    }
}
$buildNames = @(
    'scummvm_ko_poc_009_intro_galmuri11',
    'scummvm_ko_poc_010_pic00922_museum_guests',
    'scummvm_ko_poc_011_pic_batch_01030',
    'scummvm_ko_poc_012_pic_batch_03113',
    'scummvm_ko_poc_015_audio_subtitle_35036',
    'scummvm_ko_poc_016_pic_all_manual_20260903',
    'scummvm_ko_poc_017_full_subtitles_pic_20260903',
    'scummvm_ko_poc_018_full_subtitles_pic_20260903',
    'scummvm_ko_poc_019_full_subtitles_layout_20260903',
    'scummvm_ko_poc_019_full_subtitles_layout_20260903_reprocheck',
    'shivers_ko_full_020_20260905_reprocheck'
)
$runnerNames = @('scummvm_audio_subtitle_runner_015', 'scummvm_full_subtitle_runner_017', 'scummvm_poc_runner')
$targets = @($buildNames | ForEach-Object { Join-Path $project "build/$_" })
$targets += @($runnerNames | ForEach-Object { Join-Path $project "work/$_" })
$auditRoot = Join-Path $project 'qa/build_full_020_20260905'
New-Item -ItemType Directory -Force -Path $auditRoot | Out-Null
$records = @()
$processes = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath })
foreach ($target in $targets) {
    if (-not (Test-Path -LiteralPath $target)) { continue }
    $resolved = (Resolve-Path -LiteralPath $target).Path
    $parent = Split-Path -Parent $resolved
    if ($parent -notin @((Join-Path $project 'build'), (Join-Path $project 'work')) -or $resolved -eq $latest) {
        throw "Deletion target outside explicit scope: $resolved"
    }
    $items = @(Get-Item -LiteralPath $resolved) + @(Get-ChildItem -LiteralPath $resolved -Recurse -Force)
    if (@($items | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) {
        throw "Reparse point in deletion target: $resolved"
    }
    if (@($processes | Where-Object { $_.ExecutablePath.StartsWith($resolved + '\', [StringComparison]::OrdinalIgnoreCase) }).Count) {
        throw "Target contains a running process: $resolved"
    }
    $files = @($items | Where-Object { -not $_.PSIsContainer })
    foreach ($name in @('poc_manifest.json','build_manifest.json','runner_manifest.json')) {
        $metadata = Join-Path $resolved $name
        if (Test-Path -LiteralPath $metadata) {
            Copy-Item -LiteralPath $metadata -Destination (Join-Path $auditRoot ((Split-Path -Leaf $resolved) + '_' + $name))
        }
    }
    $records += [pscustomobject]@{path=$resolved;files=$files.Count;logical_bytes=($files | Measure-Object Length -Sum).Sum}
}
$audit = [ordered]@{latest_build=$latest;latest_manifest_sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $latest 'build_manifest.json')).Hash;targets=$records;note='Permanent deletion authorized by user. Originals, translation snapshots, saves, QA and current runner 019 retained.'}
$audit | ConvertTo-Json -Depth 5 | Out-File -LiteralPath (Join-Path $auditRoot 'cleanup_inventory.json') -Encoding utf8
foreach ($record in $records) {
    Remove-Item -LiteralPath $record.path -Recurse -Force
    if (Test-Path -LiteralPath $record.path) { throw "Deletion incomplete: $($record.path)" }
    Write-Output "deleted=$($record.path)"
}
foreach ($file in $manifest.files.PSObject.Properties) {
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $latest $file.Name)).Hash -ne $file.Value) {
        throw "Post-cleanup validation failed: $($file.Name)"
    }
}
Write-Output "deleted_directories=$($records.Count); latest_build_post_cleanup=PASS"
