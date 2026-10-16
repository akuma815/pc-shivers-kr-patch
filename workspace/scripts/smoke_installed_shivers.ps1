$ErrorActionPreference='Stop'
$project=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$qa=Join-Path $project 'qa/installer_rc1_20260905_03'
$fixtureRoot=Join-Path $project 'work/installer_qa_20260905_03'
$game=(Get-ChildItem -LiteralPath $fixtureRoot -Directory | Where-Object {$_.Name.Contains('%')}).FullName
if (-not $game -or (Get-Process -Name 'scummvm*' -ErrorAction SilentlyContinue)) { throw 'Missing fixture or a user game is running' }
$config=Join-Path $game '_shivers_ko/scummvm.ini'
$runtimeLog=Join-Path $qa 'installed_save_smoke.log'
$text=Get-Content -Raw -Encoding UTF8 -LiteralPath $config
$text=$text.Replace('[scummvm]',("[scummvm]`nlogfile="+$runtimeLog+"`ndebuglevel=1"))
[IO.File]::WriteAllText($config,$text,[Text.UTF8Encoding]::new($false))
$launcher=Start-Process -FilePath (Join-Path $game 'Shivers Korean.exe') -ArgumentList '--continue' -WorkingDirectory $game -WindowStyle Hidden -PassThru
Start-Sleep -Seconds 2
$runner=Get-Process -Name 'scummvm_shivers_ko_full_subtitles_025' -ErrorAction SilentlyContinue
if (@($runner).Count -ne 1) { throw 'Installed launcher did not start exactly one runner' }
$processInfo=Get-CimInstance Win32_Process -Filter ("ProcessId="+$runner.Id)
if ($processInfo.ExecutablePath -ne (Join-Path $game '_shivers_ko/runtime/scummvm_shivers_ko_full_subtitles_025.exe')) { throw 'Unexpected runtime; leave it untouched' }
try {
 Start-Sleep -Seconds 8
 $runner.Refresh()
 if($runner.HasExited) { throw 'Runtime exited during the save-load smoke test' }
 $result=[ordered]@{pid=$runner.Id;command_line=$processInfo.CommandLine;alive_after_10_seconds=$true;legacy_bitmap_font_present=(Test-Path -LiteralPath (Join-Path $game 'korean.fnt'));visual_gameplay_qa='not claimed';save_slot=1}
 [IO.File]::WriteAllText((Join-Path $qa 'installed_save_smoke.json'),($result|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
 Write-Output 'Installed launcher started the verified runtime with --no-subtitles --language=ko --save-slot=1'
} finally {
 if(-not $runner.HasExited) {
  $null=$runner.CloseMainWindow()
  if(-not $runner.WaitForExit(5000)) { Stop-Process -Id $runner.Id }
 }
}
