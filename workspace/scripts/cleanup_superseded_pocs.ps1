$ErrorActionPreference = 'Stop'

$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$ProjectPrefix = $ProjectRoot.TrimEnd('\') + '\'
$KeepBuilds = @(
    'scummvm_ko_poc_009_intro_galmuri11',
    'scummvm_ko_poc_010_pic00922_museum_guests',
    'scummvm_ko_poc_011_pic_batch_01030',
    'scummvm_ko_poc_012_pic_batch_03113'
)
$KeepRuns = @(
    'manual_ko_intro_poc_009',
    'manual_ko_pic00922_poc_010_fast',
    'manual_ko_pic_batch_01030_poc_011',
    'manual_ko_pic_batch_03113_poc_012'
)
$KeepLogs = @(
    'manual_ko_intro_poc_009.log',
    'manual_ko_pic00922_poc_010_fast.log',
    'manual_ko_pic_batch_01030_poc_011.log',
    'manual_ko_pic_batch_03113_poc_012.log',
    'BASELINE_2026-08-30.md'
)
$KeepScreenshotDirs = @(
    'manual_ko_intro_poc_009',
    'manual_ko_pic00922_poc_010_fast',
    'manual_ko_pic_batch_01030_poc_011',
    'manual_ko_pic_batch_03113_poc_012'
)

$CleanupRoots = @(
    (Join-Path $ProjectRoot 'build'),
    (Join-Path $ProjectRoot 'work\scummvm_runs'),
    (Join-Path $ProjectRoot 'qa\logs\scummvm'),
    (Join-Path $ProjectRoot 'qa\screenshots\scummvm'),
    (Join-Path $ProjectRoot 'work\tmp')
)

$Targets = [System.Collections.Generic.List[string]]::new()

$BuildRoot = $CleanupRoots[0]
if (Test-Path -LiteralPath $BuildRoot) {
    Get-ChildItem -LiteralPath $BuildRoot -Directory -Force |
        Where-Object Name -notin $KeepBuilds |
        ForEach-Object { $Targets.Add($_.FullName) }
}

$RunRoot = $CleanupRoots[1]
if (Test-Path -LiteralPath $RunRoot) {
    Get-ChildItem -LiteralPath $RunRoot -Directory -Force |
        Where-Object Name -notin $KeepRuns |
        ForEach-Object { $Targets.Add($_.FullName) }
}

$LogRoot = $CleanupRoots[2]
if (Test-Path -LiteralPath $LogRoot) {
    Get-ChildItem -LiteralPath $LogRoot -File -Force |
        Where-Object Name -notin $KeepLogs |
        ForEach-Object { $Targets.Add($_.FullName) }
}

$ScreenshotRoot = $CleanupRoots[3]
if (Test-Path -LiteralPath $ScreenshotRoot) {
    Get-ChildItem -LiteralPath $ScreenshotRoot -Force |
        Where-Object Name -notin $KeepScreenshotDirs |
        ForEach-Object { $Targets.Add($_.FullName) }
}

$TemporaryRoot = $CleanupRoots[4]
if (Test-Path -LiteralPath $TemporaryRoot) {
    Get-ChildItem -LiteralPath $TemporaryRoot -Force |
        ForEach-Object { $Targets.Add($_.FullName) }
}

$PythonCacheRoot = Join-Path $ProjectRoot 'workspace\scripts\__pycache__'
if (Test-Path -LiteralPath $PythonCacheRoot) {
    $Targets.Add($PythonCacheRoot)
}

$Validated = [System.Collections.Generic.List[string]]::new()
foreach ($Target in $Targets) {
    $FullPath = [IO.Path]::GetFullPath($Target)
    if (-not $FullPath.StartsWith($ProjectPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe cleanup target outside project: $FullPath"
    }
    if ($CleanupRoots -contains $FullPath) {
        throw "Refusing to remove a cleanup root: $FullPath"
    }
    if ($KeepBuilds -contains [IO.Path]::GetFileName($FullPath)) {
        throw "Current build entered cleanup list: $FullPath"
    }
    if ($KeepRuns -contains [IO.Path]::GetFileName($FullPath)) {
        throw "Current run entered cleanup list: $FullPath"
    }
    if ($KeepLogs -contains [IO.Path]::GetFileName($FullPath)) {
        throw "Current or baseline log entered cleanup list: $FullPath"
    }
    if ($KeepScreenshotDirs -contains [IO.Path]::GetFileName($FullPath)) {
        throw "Current screenshot directory entered cleanup list: $FullPath"
    }
    $Validated.Add($FullPath)
}

$DeletedFiles = 0L
$LogicalBytes = 0L
foreach ($FullPath in $Validated) {
    $Item = Get-Item -LiteralPath $FullPath -Force
    if ($Item.PSIsContainer) {
        $Files = @(Get-ChildItem -LiteralPath $FullPath -File -Recurse -Force -ErrorAction SilentlyContinue)
        $DeletedFiles += $Files.Count
        $LogicalBytes += ($Files | Measure-Object Length -Sum).Sum
    } else {
        $DeletedFiles++
        $LogicalBytes += $Item.Length
    }
}

foreach ($FullPath in $Validated) {
    Remove-Item -LiteralPath $FullPath -Recurse -Force
}

[pscustomobject]@{
    DeletedTargets = $Validated.Count
    DeletedFiles = $DeletedFiles
    LogicalBytes = $LogicalBytes
    LogicalGiB = [math]::Round($LogicalBytes / 1GB, 3)
}

'REMAINING_BUILDS'
Get-ChildItem -LiteralPath $BuildRoot -Force | Select-Object Name, FullName
'REMAINING_RUNS'
Get-ChildItem -LiteralPath $RunRoot -Force | Select-Object Name, FullName
'REMAINING_LOGS'
Get-ChildItem -LiteralPath $LogRoot -Force | Select-Object Name, FullName
