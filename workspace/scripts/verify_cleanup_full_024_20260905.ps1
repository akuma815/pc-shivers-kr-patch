param([switch]$DeleteOldBuilds)
$ErrorActionPreference = 'Stop'
$project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$buildRoot = Join-Path $project 'build'
$latest = Join-Path $buildRoot 'shivers_ko_full_024_20260905'
$qa = Join-Path $project 'qa/build_full_024_20260905'
$manifestPath = Join-Path $latest 'build_manifest.json'
$manifest = Get-Content -Raw -Encoding utf8 -LiteralPath $manifestPath | ConvertFrom-Json
function Check-Hash($path, $expected) {
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash -ne $expected) { throw "Hash mismatch: $path" }
}
function Check-Current {
    foreach ($file in $manifest.files.PSObject.Properties) { Check-Hash (Join-Path $latest $file.Name) $file.Value }
    $existing = Get-Content -Raw -Encoding utf8 -LiteralPath (Join-Path $project 'backups/graphics/blueprint_catalog_before_024_20260905/existing_png_hashes.json') | ConvertFrom-Json
    foreach ($file in $existing.PSObject.Properties) { Check-Hash (Join-Path $project ('workspace/graphics/english_assets/' + $file.Name)) $file.Value }
    $saves = Get-Content -Raw -Encoding utf8 -LiteralPath (Join-Path $project 'backups/saves/before_full_024_20260905/save_inventory.json') | ConvertFrom-Json
    foreach ($save in $saves) { Check-Hash (Join-Path $project $save.source) $save.sha256; Check-Hash (Join-Path $project $save.backup) $save.sha256 }
}
Check-Current
$previousPath = Join-Path $buildRoot 'shivers_ko_full_023_20260905/build_manifest.json'
if (-not (Test-Path -LiteralPath $previousPath)) { $previousPath = Join-Path $qa 'shivers_ko_full_023_20260905_build_manifest.json' }
$previous = Get-Content -Raw -Encoding utf8 -LiteralPath $previousPath | ConvertFrom-Json
foreach ($g in $previous.graphics) { Check-Hash (Join-Path $latest $g.patch) $g.sha256 }
$priorPaths = @($previous.graphics | ForEach-Object { $_.patch })
$newGraphics = @($manifest.graphics | Where-Object { $_.patch -notin $priorPaths })
if ($newGraphics.Count -ne 3 -or @($newGraphics | Where-Object { $_.type -ne 'view' -or $_.number -notin @(12183,12184,12185) }).Count) { throw 'Unexpected new graphics' }
if ($manifest.counts.pic -ne 142 -or $manifest.counts.view -ne 72 -or $manifest.movie_subtitle_count -ne 117 -or $manifest.audio_subtitle_count -ne 86) { throw 'Unexpected build counts' }
foreach ($f in $previous.files.PSObject.Properties) {
    if ($f.Name -match '\.srt$|\.exe$|\.fnt$|\.ttf$') { Check-Hash (Join-Path $latest $f.Name) $f.Value }
}
$result = [ordered]@{static_validation='PASS';manifest_sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $manifestPath).Hash;verified_build_files=@($manifest.files.PSObject.Properties).Count;preexisting_png_unchanged=809;prior_graphics_patches_unchanged=$previous.graphics.Count;only_added_views=@(12183,12184,12185);save_originals_and_backups='PASS';runtime_qa='not performed for 024';deleted_builds=@()}
$cleanupPath = Join-Path $qa 'cleanup_inventory.json'
if (Test-Path -LiteralPath $cleanupPath) {
    $cleanup = Get-Content -Raw -Encoding utf8 -LiteralPath $cleanupPath | ConvertFrom-Json
    $result.deleted_builds = @($cleanup.authorized_targets | Where-Object { -not (Test-Path -LiteralPath $_) })
    if ($result.deleted_builds.Count -eq 4) { $result.post_cleanup_validation = 'PASS' }
}
$result | ConvertTo-Json -Depth 5 | Out-File -Encoding utf8 -LiteralPath (Join-Path $qa 'verification.json')
if (-not $DeleteOldBuilds) { $result | ConvertTo-Json -Depth 5; exit 0 }
$names = @('shivers_ko_full_020_20260905','shivers_ko_full_021_20260905','shivers_ko_full_022_20260905','shivers_ko_full_023_20260905')
$processes = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath })
$targets = @()
foreach ($name in $names) {
    $target = Join-Path $buildRoot $name
    if (-not (Test-Path -LiteralPath $target)) { continue }
    $resolved = (Resolve-Path -LiteralPath $target).Path
    if ((Split-Path -Parent $resolved) -ne $buildRoot -or $resolved -eq $latest -or (Split-Path -Leaf $resolved) -notin $names) { throw "Unsafe deletion target: $resolved" }
    $items = @(Get-Item -LiteralPath $resolved) + @(Get-ChildItem -LiteralPath $resolved -Recurse -Force)
    if (@($items | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) { throw "Reparse point: $resolved" }
    if (@($items | Where-Object { -not $_.PSIsContainer -and $_.Name -match '^shivers.*\.\d{3}$' }).Count) { throw "Save file in old build: $resolved" }
    if (@($processes | Where-Object { $_.ExecutablePath.StartsWith($resolved + '\', [StringComparison]::OrdinalIgnoreCase) }).Count) { throw "Running game: $resolved" }
    Copy-Item -LiteralPath (Join-Path $resolved 'build_manifest.json') -Destination (Join-Path $qa ($name + '_build_manifest.json'))
    $targets += $resolved
}
[ordered]@{authorized_targets=$targets;latest_retained=$latest;save_backup='backups/saves/before_full_024_20260905';deletion='permanent; source snapshots and QA retained'} | ConvertTo-Json -Depth 5 | Out-File -Encoding utf8 -LiteralPath (Join-Path $qa 'cleanup_inventory.json')
foreach ($target in $targets) {
    Remove-Item -LiteralPath $target -Recurse -Force
    if (Test-Path -LiteralPath $target) { throw "Deletion incomplete: $target" }
    $result.deleted_builds += $target
    $result | ConvertTo-Json -Depth 5 | Out-File -Encoding utf8 -LiteralPath (Join-Path $qa 'verification.json')
    Write-Output "Deleted: $target"
}
Check-Current
$result.post_cleanup_validation = 'PASS'
$result | ConvertTo-Json -Depth 5 | Out-File -Encoding utf8 -LiteralPath (Join-Path $qa 'verification.json')
$result | ConvertTo-Json -Depth 5
