$ErrorActionPreference = 'Stop'

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$queuePath = Join-Path $projectRoot 'workspace\graphics\graphics_translation_queue_20260901.csv'
$workingRoot = Join-Path $projectRoot 'workspace\graphics\english_assets'
$backupRoot = Join-Path $projectRoot 'backups\graphics\superseded_working_before_user_authored_restore_except_titles_20260903'
$phaseOneReportPath = Join-Path $backupRoot 'restore_report.json'
$inventoryPath = Join-Path $backupRoot 'inventory.csv'

function Get-Sha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash
}

$expectedQueueHash = 'B450F579666B3BBB0285D9022D053602F6A56F5578B768B3CC345A22A06A17AA'
if ((Get-Sha256 $queuePath) -ne $expectedQueueHash) {
    throw 'Queue changed after phase-one user-authored restore'
}

$phaseOneReport = Get-Content -LiteralPath $phaseOneReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($phaseOneReport.restored_count -ne 81) {
    throw 'Phase-one restore report does not contain 81 user-authored targets'
}
foreach ($target in $phaseOneReport.targets) {
    $workingPath = Join-Path $workingRoot $target.queue_path
    if ((Get-Sha256 $workingPath) -ne $target.source_sha256) {
        throw "User-authored target changed after phase one: $($target.queue_path)"
    }
}

$titleHashes = @{
    910 = '020B6B2FC674326419A2FFFD18A80FAF69923AA0D966779B4290C3B4A487B8DD'
    911 = 'E1E4F851DF72269DE9C0DE5A707D643FD26789F3E2DD582224067AE68BFF89E0'
    920 = 'C41A7EA188F4502F36979C31BF39D271E5F0D4D50D06DF93162EB2BD3C2A0AAA'
    921 = '00D21665D2BC7196280AF076EDB84C0C4451FA4244FC3B4991D0ABD3DCEE1E77'
}
foreach ($number in $titleHashes.Keys) {
    $id = '{0:D5}' -f $number
    $path = Join-Path $workingRoot "png\pic\$id\cel_000.png"
    if ((Get-Sha256 $path) -ne $titleHashes[$number]) {
        throw "Title baseline mismatch: pic $id"
    }
}

$resets = @(
    [pscustomobject]@{ number = 902; current = '9D260AF41AF89A7F8FDF761308BA99855FEDA80D67C063B945D7BA52FB42EB3F'; original = '7894069C100CB643C286D3D8DBA1F019341415CC6B5B2AFBB0251F00CD1CD155' },
    [pscustomobject]@{ number = 993; current = '3BE731343D72BE9D6E3A3B1B8E2664335D9998D7DA3AAF88A9BEA008E7172F67'; original = '433C6BD3EC422FAEA3E2871B380A248B6C6A08583E7732EA2F582A89F266F8F4' },
    [pscustomobject]@{ number = 994; current = 'F94BC7FC7B7DFEAF149D4C6A53AC2952B40D374A7FB575AB3FEFB6F9567EDF72'; original = 'AC863545AFC7B1C18DCEB1812D582431310FA458A228E4E34B9CF80A42ED6F88' }
)

$inventory = @(Import-Csv -LiteralPath $inventoryPath)
if ($inventory.Count -ne 21) {
    throw "Expected 21 phase-one superseded working files, got $($inventory.Count)"
}

foreach ($reset in $resets) {
    $id = '{0:D5}' -f $reset.number
    $relative = "png/pic/$id/cel_000.png"
    $workingPath = Join-Path $workingRoot $relative
    $originalPath = Join-Path $projectRoot "backups\graphics\pic_${id}_english_before_sequential_localization_20260901\cel_000.png"
    if ((Get-Sha256 $workingPath) -ne $reset.current) {
        throw "Unexpected current AI working hash: pic $id"
    }
    if ((Get-Sha256 $originalPath) -ne $reset.original) {
        throw "Original backup hash mismatch: pic $id"
    }

    $backupPath = Join-Path $backupRoot $relative
    if (Test-Path -LiteralPath $backupPath) {
        throw "Superseded backup already exists: $backupPath"
    }
    [IO.Directory]::CreateDirectory((Split-Path -Parent $backupPath)) | Out-Null
    Copy-Item -LiteralPath $workingPath -Destination $backupPath
    if ((Get-Sha256 $backupPath) -ne $reset.current) {
        throw "Superseded backup copy mismatch: pic $id"
    }
    $inventory += [pscustomobject]@{
        relative_path = $relative
        bytes = (Get-Item -LiteralPath $backupPath).Length
        sha256 = $reset.current
        original_sha256 = $reset.original
        restored_user_sha256 = 'NO_USER_AUTHORED_SOURCE_RESTORED_TO_ENGLISH_ORIGINAL'
    }

    Copy-Item -LiteralPath $originalPath -Destination $workingPath -Force
    if ((Get-Sha256 $workingPath) -ne $reset.original) {
        throw "English original restore mismatch: pic $id"
    }
}
$inventory | Sort-Object relative_path | Export-Csv -LiteralPath $inventoryPath -NoTypeInformation -Encoding UTF8

$rows = @(Import-Csv -LiteralPath $queuePath)
foreach ($reset in $resets) {
    $matches = @($rows | Where-Object { $_.type_name -eq 'pic' -and [int]$_.number -eq $reset.number })
    if ($matches.Count -ne 1) {
        throw "Expected one pic queue row for $($reset.number), got $($matches.Count)"
    }
    $matches[0].current_sha256 = $reset.original
    $matches[0].status = 'restored_english_original_no_user_work_20260903'
    $matches[0].note = 'no preserved user-authored working image existed; superseded AI localization backed up and English original restored on 2026-09-03; title assets 00910, 00911, 00920, 00921 excluded'
}
$queueTemp = "$queuePath.restore_tmp"
$rows | Export-Csv -LiteralPath $queueTemp -NoTypeInformation -Encoding UTF8
Move-Item -LiteralPath $queueTemp -Destination $queuePath -Force

$missing = 0
$mismatch = 0
$changed = 0
foreach ($row in $rows) {
    $workingPath = Join-Path $workingRoot $row.path
    if (-not (Test-Path -LiteralPath $workingPath -PathType Leaf)) {
        $missing++
        continue
    }
    $actual = Get-Sha256 $workingPath
    if ($actual -ne $row.current_sha256) {
        $mismatch++
    }
    if ($actual -ne $row.original_sha256) {
        $changed++
    }
}
if ($missing -ne 0 -or $mismatch -ne 0 -or $changed -ne 85) {
    throw "Final restore audit failed: missing=$missing mismatch=$mismatch changed=$changed"
}

$finalReport = [ordered]@{
    schema_version = 1
    action = 'finalize_user_authored_graphics_restore_except_titles'
    date = '2026-09-03'
    restored_user_authored_count = 81
    restored_english_original_count = 3
    preserved_title_count = 4
    preserved_title_numbers = @('00910', '00911', '00920', '00921')
    superseded_working_backup_count = $inventory.Count
    queue_rows = $rows.Count
    missing = $missing
    hash_mismatch = $mismatch
    changed_from_original = $changed
    queue_sha256 = Get-Sha256 $queuePath
    superseded_backup_inventory_sha256 = Get-Sha256 $inventoryPath
    phase_one_report_sha256 = Get-Sha256 $phaseOneReportPath
    reset_to_english_original = @($resets | ForEach-Object { '{0:D5}' -f $_.number })
}
$finalReportPath = Join-Path $backupRoot 'final_restore_report.json'
$finalReport | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $finalReportPath -Encoding UTF8
$finalReport | ConvertTo-Json -Depth 4
