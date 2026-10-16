param([string]$Case = 'native_off', [switch]$NativeOn, [switch]$Visible, [int[]]$CaptureSeconds = @(25,40,90))
$ErrorActionPreference = 'Stop'
$project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$build = Join-Path $project 'build/shivers_ko_full_024_20260905'
$qa = Join-Path $project ('qa/subtitle_launch_fix_024_20260905/' + $Case)
if (Test-Path -LiteralPath $qa) { throw 'Use a new case name; existing QA is immutable' }
New-Item -ItemType Directory -Path (Join-Path $qa 'saves') -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $build 'scummvm.ini') -Destination (Join-Path $qa 'run.ini')
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class ShiversProbeWindow {
 [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
 public delegate bool EnumProc(IntPtr h, IntPtr p);
 [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
 [DllImport("user32.dll", CharSet=CharSet.Auto)] public static extern int GetClassName(IntPtr h, System.Text.StringBuilder b, int n);
 public static IntPtr Find(uint pid) { IntPtr found=IntPtr.Zero; EnumWindows((h,p)=>{uint owner; GetWindowThreadProcessId(h,out owner); var name=new System.Text.StringBuilder(256); GetClassName(h,name,256); if(owner==pid && name.ToString()=="SDL_app") {found=h;return false;} return true;},IntPtr.Zero); return found; }
 [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
 [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
 [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
}
'@
$null = [ShiversProbeWindow]::SetProcessDPIAware()
$toggle = if ($NativeOn) { '--subtitles' } else { '--no-subtitles' }
$argsList = @('--config="' + (Join-Path $qa 'run.ini') + '"', '--path="' + $build + '"', '--savepath="' + (Join-Path $qa 'saves') + '"', '--logfile="' + (Join-Path $qa 'run.log') + '"', '--debuglevel=1', '--opl-driver=nuked', $toggle, '--language=ko', 'shivers-ko-full')
$process = Start-Process -FilePath (Join-Path $build 'runtime/scummvm_shivers_ko_full_subtitles_021.exe') -WorkingDirectory $build -ArgumentList $argsList -WindowStyle Hidden -PassThru
$timer = [Diagnostics.Stopwatch]::StartNew()
try {
 if ($Visible) { Start-Sleep -Seconds 2; $window=[ShiversProbeWindow]::Find($process.Id); $null=[ShiversProbeWindow]::ShowWindow($window,5); $null=[ShiversProbeWindow]::SetForegroundWindow($window) }
 foreach ($second in $CaptureSeconds) {
  while ($timer.Elapsed.TotalSeconds -lt $second) { Start-Sleep -Milliseconds 500; if ($process.HasExited) { throw "Game exited: $($process.ExitCode)" } }
  $process.Refresh()
  $r = New-Object ShiversProbeWindow+RECT
  $window = [ShiversProbeWindow]::Find($process.Id)
  if (-not [ShiversProbeWindow]::GetWindowRect($window, [ref]$r)) { throw 'No game window' }
  $bitmap = New-Object Drawing.Bitmap(($r.Right-$r.Left),($r.Bottom-$r.Top))
  $graphics = [Drawing.Graphics]::FromImage($bitmap)
  $dc = $graphics.GetHdc()
  try { $ok = [ShiversProbeWindow]::PrintWindow($window,$dc,2) } finally { $graphics.ReleaseHdc($dc) }
  if ($Visible) { $graphics.CopyFromScreen($r.Left,$r.Top,0,0,$bitmap.Size) }
  $graphics.Dispose()
  $file = Join-Path $qa ("frame_{0:D3}.png" -f $second)
  $bitmap.Save($file,[Drawing.Imaging.ImageFormat]::Png)
  $bitmap.Dispose()
  Write-Output "capture=$file; PrintWindow=$ok"
 }
} finally {
 if (-not $process.HasExited) { $null = $process.CloseMainWindow(); if (-not $process.WaitForExit(5000)) { Stop-Process -Id $process.Id } }
}
