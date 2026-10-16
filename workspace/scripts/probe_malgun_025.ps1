param([string]$Case = 'opening', [int[]]$CaptureSeconds = @(8,20,30,40,55,75,100,130), [switch]$LeaveRunning)
$ErrorActionPreference = 'Stop'
$project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$build = Join-Path $project 'build/shivers_ko_malgun_poc_025_20260905'
if ($Case -notmatch '^[a-zA-Z0-9_-]+$') { throw 'Invalid case name' }
$qa = Join-Path $project ('qa/malgun_poc_025_20260905/' + $Case)
if (Test-Path -LiteralPath $qa) { throw 'Existing QA must not be overwritten' }
if (Get-Process -Name 'scummvm*' -ErrorAction SilentlyContinue) { throw 'A game is already running; leave it untouched' }
New-Item -ItemType Directory -Path (Join-Path $qa 'saves') -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $build 'scummvm.ini') -Destination (Join-Path $qa 'run.ini')
Get-ChildItem -LiteralPath (Join-Path $project 'work/scummvm_saves/full') -File | Copy-Item -Destination (Join-Path $qa 'saves')
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class MalgunProbeWindow {
 [DllImport("user32.dll")] public static extern IntPtr SetThreadDpiAwarenessContext(IntPtr value);
 public delegate bool EnumProc(IntPtr h, IntPtr p);
 [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
 [DllImport("user32.dll", CharSet=CharSet.Auto)] public static extern int GetClassName(IntPtr h, System.Text.StringBuilder b, int n);
 public static IntPtr Find(uint pid) { IntPtr found=IntPtr.Zero; EnumWindows((h,p)=>{uint owner; GetWindowThreadProcessId(h,out owner); var name=new System.Text.StringBuilder(256); GetClassName(h,name,256); if(owner==pid && name.ToString()=="SDL_app") {found=h;return false;} return true;},IntPtr.Zero); return found; }
 [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
 [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
 [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
 [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
 [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
}
'@
$argsList = @('--config="' + (Join-Path $qa 'run.ini') + '"', '--path="' + $build + '"', '--savepath="' + (Join-Path $qa 'saves') + '"', '--logfile="' + (Join-Path $qa 'run.log') + '"', '--debuglevel=1', '--opl-driver=nuked', '--no-subtitles', '--language=ko', 'shivers-ko-full')
$process = Start-Process -FilePath (Join-Path $build 'runtime/scummvm_shivers_ko_full_subtitles_025.exe') -WorkingDirectory $build -ArgumentList $argsList -WindowStyle Hidden -PassThru
$timer = [Diagnostics.Stopwatch]::StartNew()
Write-Output "QA process=$($process.Id); saves are isolated copies"
try {
 Start-Sleep -Seconds 2
 $window = [MalgunProbeWindow]::Find($process.Id)
 $null = [MalgunProbeWindow]::ShowWindow($window,5)
 $null = [MalgunProbeWindow]::SetForegroundWindow($window)
 foreach ($second in $CaptureSeconds) {
  while ($timer.Elapsed.TotalSeconds -lt $second -and -not $process.HasExited) { Start-Sleep -Milliseconds 250 }
  if ($process.HasExited) { Write-Output "Game exited: $($process.ExitCode)"; break }
  $window = [MalgunProbeWindow]::Find($process.Id)
  if ([MalgunProbeWindow]::GetForegroundWindow() -ne $window) { Write-Output "capture_skipped=$second game not foreground"; continue }
  $previousDpi = [MalgunProbeWindow]::SetThreadDpiAwarenessContext([IntPtr](-4))
  try {
   $r = New-Object MalgunProbeWindow+RECT
   $origin = New-Object MalgunProbeWindow+POINT
   if (-not [MalgunProbeWindow]::GetClientRect($window,[ref]$r)) { throw 'No game client area' }
   if (-not [MalgunProbeWindow]::ClientToScreen($window,[ref]$origin)) { throw 'No game origin' }
   $bitmap = New-Object Drawing.Bitmap(($r.Right-$r.Left),($r.Bottom-$r.Top))
   $graphics = [Drawing.Graphics]::FromImage($bitmap)
   try {
    $graphics.CopyFromScreen($origin.X,$origin.Y,0,0,$bitmap.Size)
    $file = Join-Path $qa ("frame_{0:D3}.png" -f $second)
    $bitmap.Save($file,[Drawing.Imaging.ImageFormat]::Png)
    Write-Output "capture=$file; size=$($bitmap.Width)x$($bitmap.Height) origin=$($origin.X),$($origin.Y)"
   } finally { $graphics.Dispose(); $bitmap.Dispose() }
  } finally { $null = [MalgunProbeWindow]::SetThreadDpiAwarenessContext($previousDpi) }
 }
} finally {
 if (-not $LeaveRunning -and -not $process.HasExited) {
  $null = $process.CloseMainWindow()
  if (-not $process.WaitForExit(5000)) { Stop-Process -Id $process.Id }
 }
}
