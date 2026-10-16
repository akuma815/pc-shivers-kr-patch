param(
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$queuePath = Join-Path $projectRoot 'workspace\graphics\graphics_translation_queue_20260901.csv'
$workingRoot = Join-Path $projectRoot 'workspace\graphics\english_assets'
$userRoot = Join-Path $projectRoot 'backups\graphics\english_assets_modified_before_full_reextract_20260901'
$userInventoryPath = Join-Path $userRoot 'inventory.csv'
$backupRoot = Join-Path $projectRoot 'backups\graphics\superseded_working_before_user_authored_restore_except_titles_20260903'

$titleHashes = @{
    910 = '020B6B2FC674326419A2FFFD18A80FAF69923AA0D966779B4290C3B4A487B8DD'
    911 = 'E1E4F851DF72269DE9C0DE5A707D643FD26789F3E2DD582224067AE68BFF89E0'
    920 = 'C41A7EA188F4502F36979C31BF39D271E5F0D4D50D06DF93162EB2BD3C2A0AAA'
    921 = '00D21665D2BC7196280AF076EDB84C0C4451FA4244FC3B4991D0ABD3DCEE1E77'
}
$specialSources = @{
    1020 = 'png/pic/01020/cel_000_ko.png'
    1030 = 'png/pic/01030/cel_000_ko.png'
    6111 = 'png/pic/06111/cel_000_ko.png'
}

function Get-Sha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash
}

function Get-ImageSize([string]$Path) {
    $bitmap = [Drawing.Bitmap]::new((Resolve-Path -LiteralPath $Path).Path)
    try {
        return @($bitmap.Width, $bitmap.Height)
    }
    finally {
        $bitmap.Dispose()
    }
}

$rows = @(Import-Csv -LiteralPath $queuePath)
if ($rows.Count -ne 796) {
    throw "Expected 796 queue rows, got $($rows.Count)"
}

$inventory = @{}
foreach ($entry in (Import-Csv -LiteralPath $userInventoryPath)) {
    $key = $entry.relative_path.Replace('\', '/')
    $inventory[$key] = $entry
}

$preflightMissing = 0
$preflightMismatch = 0
foreach ($row in $rows) {
    $workingPath = Join-Path $workingRoot $row.path
    if (-not (Test-Path -LiteralPath $workingPath -PathType Leaf)) {
        $preflightMissing++
        continue
    }
    if ((Get-Sha256 $workingPath) -ne $row.current_sha256) {
        $preflightMismatch++
    }
}
if ($preflightMissing -ne 0 -or $preflightMismatch -ne 0) {
    throw "Queue preflight failed: missing=$preflightMissing mismatch=$preflightMismatch"
}

foreach ($number in $titleHashes.Keys) {
    $id = '{0:D5}' -f $number
    $path = Join-Path $workingRoot "png\pic\$id\cel_000.png"
    $actual = Get-Sha256 $path
    if ($actual -ne $titleHashes[$number]) {
        throw "Title baseline mismatch for pic ${id}: $actual"
    }
}

$targets = @()
foreach ($row in $rows) {
    $number = [int]$row.number
    if ($titleHashes.ContainsKey($number)) {
        continue
    }

    $sourceRelative = $null
    if ($specialSources.ContainsKey($number)) {
        $sourceRelative = $specialSources[$number]
    }
    else {
        $candidateRelative = $row.path.Replace('\', '/')
        if ($inventory.ContainsKey($candidateRelative)) {
            $candidate = $inventory[$candidateRelative]
            if ($candidate.sha256 -ne $row.original_sha256) {
                $sourceRelative = $candidateRelative
            }
        }
    }

    if ($null -eq $sourceRelative) {
        continue
    }
    if (-not $inventory.ContainsKey($sourceRelative)) {
        throw "Restore source is not present in the preserved inventory: $sourceRelative"
    }

    $sourcePath = Join-Path $userRoot $sourceRelative
    $targetPath = Join-Path $workingRoot $row.path
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "Missing restore source: $sourcePath"
    }
    $sourceHash = Get-Sha256 $sourcePath
    if ($sourceHash -ne $inventory[$sourceRelative].sha256) {
        throw "Preserved inventory hash mismatch: $sourceRelative"
    }

    $currentHash = Get-Sha256 $targetPath
    $sourceSize = Get-ImageSize $sourcePath
    $originalSize = Get-ImageSize $targetPath
    $sameAspect = [Math]::Abs(($sourceSize[0] / [double]$sourceSize[1]) - ($originalSize[0] / [double]$originalSize[1])) -lt 0.001
    $targets += [pscustomobject]@{
        sequence = [int]$row.sequence
        number = $number
        queue_path = $row.path.Replace('\', '/')
        source_relative_path = $sourceRelative
        source_sha256 = $sourceHash
        current_sha256 = $currentHash
        original_sha256 = $row.original_sha256
        source_dimensions = "$($sourceSize[0])x$($sourceSize[1])"
        current_dimensions = "$($originalSize[0])x$($originalSize[1])"
        same_aspect_as_current = $sameAspect
        current_was_modified = ($currentHash -ne $row.original_sha256)
        already_restored = ($currentHash -eq $sourceHash)
    }
}

if ($targets.Count -ne 81) {
    throw "Expected 81 non-title user-authored restore targets, got $($targets.Count)"
}
if ((@($targets.queue_path | Group-Object | Where-Object Count -ne 1)).Count -ne 0) {
    throw 'Duplicate restore target detected'
}

$preflight = [ordered]@{
    schema_version = 1
    action = 'restore_user_authored_graphics_except_titles'
    date = '2026-09-03'
    title_exclusions = @($titleHashes.Keys | Sort-Object | ForEach-Object { '{0:D5}' -f $_ })
    target_count = $targets.Count
    already_restored_count = @($targets | Where-Object already_restored).Count
    current_modified_target_count = @($targets | Where-Object current_was_modified).Count
    source_dimension_diff_count = @($targets | Where-Object { $_.source_dimensions -ne $_.current_dimensions }).Count
    source_aspect_diff_count = @($targets | Where-Object { -not $_.same_aspect_as_current }).Count
    targets = @($targets | Sort-Object sequence)
}

if (-not $Apply) {
    $preflight | ConvertTo-Json -Depth 5
    exit 0
}

if (Test-Path -LiteralPath $backupRoot) {
    throw "Backup root already exists: $backupRoot"
}
[IO.Directory]::CreateDirectory($backupRoot) | Out-Null

$backupRows = @()
foreach ($target in ($targets | Where-Object current_was_modified)) {
    $sourcePath = Join-Path $workingRoot $target.queue_path
    $backupPath = Join-Path $backupRoot $target.queue_path
    [IO.Directory]::CreateDirectory((Split-Path -Parent $backupPath)) | Out-Null
    Copy-Item -LiteralPath $sourcePath -Destination $backupPath
    $backupHash = Get-Sha256 $backupPath
    if ($backupHash -ne $target.current_sha256) {
        throw "Backup copy hash mismatch: $($target.queue_path)"
    }
    $backupRows += [pscustomobject]@{
        relative_path = $target.queue_path
        bytes = (Get-Item -LiteralPath $backupPath).Length
        sha256 = $backupHash
        original_sha256 = $target.original_sha256
        restored_user_sha256 = $target.source_sha256
    }
}
$backupRows | Export-Csv -LiteralPath (Join-Path $backupRoot 'inventory.csv') -NoTypeInformation -Encoding UTF8

foreach ($target in $targets) {
    $sourcePath = Join-Path $userRoot $target.source_relative_path
    $targetPath = Join-Path $workingRoot $target.queue_path
    Copy-Item -LiteralPath $sourcePath -Destination $targetPath -Force
    if ((Get-Sha256 $targetPath) -ne $target.source_sha256) {
        throw "Restore copy hash mismatch: $($target.queue_path)"
    }

    $row = $rows[$target.sequence - 1]
    if ([int]$row.number -ne $target.number) {
        throw "Queue sequence mismatch for pic $($target.number)"
    }
    $row.current_sha256 = $target.source_sha256
    $row.status = 'restored_user_authored_working_20260903'
    $row.note = "restored from preserved user-authored source $($target.source_relative_path) on 2026-09-03; current title assets 00910, 00911, 00920, 00921 excluded and preserved; static PNG restore only"
}

$queueTemp = "$queuePath.restore_tmp"
$rows | Export-Csv -LiteralPath $queueTemp -NoTypeInformation -Encoding UTF8
Move-Item -LiteralPath $queueTemp -Destination $queuePath -Force

$finalMissing = 0
$finalMismatch = 0
$finalChanged = 0
foreach ($row in $rows) {
    $workingPath = Join-Path $workingRoot $row.path
    if (-not (Test-Path -LiteralPath $workingPath -PathType Leaf)) {
        $finalMissing++
        continue
    }
    $actual = Get-Sha256 $workingPath
    if ($actual -ne $row.current_sha256) {
        $finalMismatch++
    }
    if ($actual -ne $row.original_sha256) {
        $finalChanged++
    }
}
if ($finalMissing -ne 0 -or $finalMismatch -ne 0) {
    throw "Final queue verification failed: missing=$finalMissing mismatch=$finalMismatch"
}
foreach ($number in $titleHashes.Keys) {
    $id = '{0:D5}' -f $number
    $path = Join-Path $workingRoot "png\pic\$id\cel_000.png"
    if ((Get-Sha256 $path) -ne $titleHashes[$number]) {
        throw "Title changed during restore: pic $id"
    }
}

$report = [ordered]@{
    schema_version = 1
    action = 'restore_user_authored_graphics_except_titles'
    date = '2026-09-03'
    title_exclusions = $preflight.title_exclusions
    restored_count = $targets.Count
    preserved_superseded_working_count = $backupRows.Count
    final_queue_rows = $rows.Count
    final_missing = $finalMissing
    final_hash_mismatch = $finalMismatch
    final_changed_from_original = $finalChanged
    queue_sha256 = Get-Sha256 $queuePath
    preserved_user_inventory_sha256 = Get-Sha256 $userInventoryPath
    superseded_backup_inventory_sha256 = Get-Sha256 (Join-Path $backupRoot 'inventory.csv')
    targets = @($targets | Sort-Object sequence)
}
$reportPath = Join-Path $backupRoot 'restore_report.json'
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8
$report | ConvertTo-Json -Depth 3
