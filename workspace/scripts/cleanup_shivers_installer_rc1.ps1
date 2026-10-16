$ErrorActionPreference='Stop'
$project=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$qa=Join-Path $project 'qa/installer_rc1_20260905_04'
$report=Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $qa 'delivery.json') | ConvertFrom-Json
if($report.status -ne 'PASS') { throw 'Delivery QA must pass before cleanup' }
$release=Join-Path $project 'dist/Shivers_Korean_Patch_v1.0_RC1.zip'
if((Get-FileHash -Algorithm SHA256 -LiteralPath $release).Hash -ne $report.zip_sha256) { throw 'Release ZIP changed' }
if(Get-Process -Name 'scummvm*' -ErrorAction SilentlyContinue) { throw 'A game is running; cleanup paused' }
# Only superseded artifacts and disposable fixtures created by this installer task.
# Earlier policy-blocked Malgun worktree/captures are deliberately NOT targeted.
$relativeTargets=@(
 'dist/Shivers_Korean_Patch_1.0_RC1',
 'dist/Shivers_Korean_Patch_1.zip',
 'work/distribution_Shivers_Korean_Patch_1.0_RC1',
 'work/installer_qa_20260905',
 'work/installer_qa_20260905_02',
 'work/installer_qa_20260905_03',
 'work/installer_qa_20260905_04',
 'work/installer_delivery_20260905',
 'work/distribution_Shivers_Korean_Patch_v1.0_RC1/payload.zip'
)
$inventory=@()
foreach($relative in $relativeTargets) {
 $target=(Resolve-Path -LiteralPath (Join-Path $project $relative)).Path
 $expected=[IO.Path]::GetFullPath((Join-Path $project $relative))
 if($target -ne $expected -or -not $target.StartsWith($project+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Cleanup escaped its declared target' }
 $item=Get-Item -LiteralPath $target -Force
 $children=@($item)
 if($item.PSIsContainer) { $children+=@(Get-ChildItem -LiteralPath $target -Force -Recurse) }
 if(@($children | Where-Object {($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0}).Count) { throw 'Reparse point in cleanup target' }
 $files=@($children | Where-Object {-not $_.PSIsContainer})
 $inventory+=[ordered]@{path=$target;file_count=$files.Count;logical_bytes=($files|Measure-Object -Property Length -Sum).Sum}
}
[IO.File]::WriteAllText((Join-Path $qa 'cleanup_inventory.json'),($inventory|ConvertTo-Json -Depth 4),[Text.UTF8Encoding]::new($false))
foreach($entry in $inventory) {
 if((Get-Item -LiteralPath $entry.path).PSIsContainer) { Remove-Item -LiteralPath $entry.path -Recurse -Force }
 else { Remove-Item -LiteralPath $entry.path -Force }
 Write-Output ('removed='+$entry.path)
}
if((Get-FileHash -Algorithm SHA256 -LiteralPath $release).Hash -ne $report.zip_sha256) { throw 'Release changed during cleanup' }
Write-Output 'Cleanup complete; original game, translation sources, saves and verified game builds were not targets.'
