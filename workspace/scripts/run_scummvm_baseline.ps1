[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$ScummVmExe = 'H:\scummvm\scummvm.exe',
    [string]$RunId = 'baseline_20260830_01',
    [ValidateSet('baseline', 'menu', 'intro-text', 'intro-subtitles', 'poc-new-game', 'poc-earliest-name', 'poc-pic922', 'poc-first-subtitles', 'poc-audio-subtitle', 'poc-full-movie-subtitles')]
    [string]$CaptureProfile = 'baseline',
    [string]$GamePath = '',
    [ValidateSet('en', 'ko')]
    [string]$GameLanguage = 'en',
    [switch]$EnableSciDebug,
    [string]$TargetId = ''
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
}

if (-not (Test-Path -LiteralPath $ScummVmExe -PathType Leaf)) {
    throw "ScummVM executable not found: $ScummVmExe"
}

if ([string]::IsNullOrWhiteSpace($GamePath)) {
    $GamePath = Join-Path $ProjectRoot 'extracted\installer'
}
else {
    $GamePath = (Resolve-Path -LiteralPath $GamePath).Path
}

$configRoot = Join-Path $ProjectRoot "work\scummvm_runs\$RunId"
$savePath = Join-Path $configRoot 'saves'
$logRoot = Join-Path $ProjectRoot 'qa\logs\scummvm'
$screenshotPath = Join-Path $ProjectRoot "qa\screenshots\scummvm\$RunId"

foreach ($directory in @($configRoot, $savePath, $logRoot, $screenshotPath)) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
}

$existingScreenshots = @(Get-ChildItem -LiteralPath $screenshotPath -File -Filter '*.png')
if ($existingScreenshots.Count -ne 0) {
    throw "Run directory already contains screenshots: $screenshotPath"
}

$configPath = Join-Path $configRoot 'scummvm.ini'
$logPath = Join-Path $logRoot "$RunId.log"
$launchModeArguments = @('--auto-detect')
if (-not [string]::IsNullOrWhiteSpace($TargetId)) {
    $launchModeArguments = @($TargetId)
    $escapedPath = $GamePath.Replace('\\', '\\')
    $targetConfig = @"
[scummvm]
versioninfo=2026.3.0

[$TargetId]
description=Shivers Korean PoC
engineid=sci
gameid=shivers
language=$GameLanguage
platform=windows
path=$escapedPath
"@
    [System.IO.File]::WriteAllText($configPath, $targetConfig, [System.Text.UTF8Encoding]::new($false))
}

$speechVolume = if ($CaptureProfile -in @('poc-audio-subtitle', 'poc-full-movie-subtitles')) { 192 } else { 0 }
$musicDriver = if ($CaptureProfile -in @('poc-audio-subtitle', 'poc-full-movie-subtitles')) { 'null' } else { 'auto' }

$argumentList = @(
    ('--path="{0}"' -f $GamePath)
    ('--config="{0}"' -f $configPath)
    ('--logfile="{0}"' -f $logPath)
    ('--savepath="{0}"' -f $savePath)
    ('--screenshotpath="{0}"' -f $screenshotPath)
    '--no-fullscreen'
    '--no-filtering'
    '--scaler=normal'
    '--scale-factor=1'
    '--subtitles'
    '--opl-driver=nuked'
    ('--music-driver={0}' -f $musicDriver)
    '--music-volume=0'
    '--sfx-volume=0'
    ('--speech-volume={0}' -f $speechVolume)
    ('--language={0}' -f $GameLanguage)
)

if ($CaptureProfile -notin @('poc-audio-subtitle', 'poc-full-movie-subtitles')) {
    $argumentList += '--window-size=640,480'
}

if ($EnableSciDebug) {
    $argumentList += @('--debuglevel=2', '--debugflags=ResMan,Patcher,Video')
}
$argumentList += $launchModeArguments

$process = Start-Process -FilePath $ScummVmExe -ArgumentList $argumentList -PassThru
$windowDeadline = [DateTime]::UtcNow.AddSeconds(12)
do {
    Start-Sleep -Milliseconds 250
    $process.Refresh()
} while (-not $process.HasExited -and $process.MainWindowHandle -eq 0 -and [DateTime]::UtcNow -lt $windowDeadline)

Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public static class ShiversWindowCapture {
    public sealed class WindowInfo {
        public IntPtr Handle;
        public string Title;
        public string ClassName;
        public Rect Bounds;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct Rect {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr windowHandle, out Rect rect);

    [DllImport("user32.dll")]
    public static extern uint GetDpiForWindow(IntPtr windowHandle);

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr parameter);

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr windowHandle, out uint processId);

    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr windowHandle);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowText(IntPtr windowHandle, StringBuilder text, int count);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetClassName(IntPtr windowHandle, StringBuilder className, int count);

    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr windowHandle);

    [DllImport("user32.dll")]
    public static extern bool SetCursorPos(int x, int y);

    [DllImport("user32.dll")]
    public static extern bool MoveWindow(IntPtr windowHandle, int x, int y, int width, int height, bool repaint);

    [DllImport("user32.dll")]
    public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extraInfo);

    public static void ClickAt(int x, int y) {
        SetCursorPos(x, y);
        mouse_event(0x0002, 0, 0, 0, UIntPtr.Zero);
        mouse_event(0x0004, 0, 0, 0, UIntPtr.Zero);
    }

    private delegate bool EnumWindowsProc(IntPtr windowHandle, IntPtr parameter);

    public static WindowInfo[] GetVisibleWindows(int targetProcessId) {
        var windows = new List<WindowInfo>();
        EnumWindows(delegate(IntPtr windowHandle, IntPtr parameter) {
            uint processId;
            GetWindowThreadProcessId(windowHandle, out processId);
            if (processId != (uint)targetProcessId || !IsWindowVisible(windowHandle)) {
                return true;
            }

            var title = new StringBuilder(512);
            var className = new StringBuilder(256);
            Rect bounds;
            GetWindowText(windowHandle, title, title.Capacity);
            GetClassName(windowHandle, className, className.Capacity);
            if (GetWindowRect(windowHandle, out bounds)) {
                windows.Add(new WindowInfo {
                    Handle = windowHandle,
                    Title = title.ToString(),
                    ClassName = className.ToString(),
                    Bounds = bounds
                });
            }
            return true;
        }, IntPtr.Zero);
        return windows.ToArray();
    }
}
'@

function Get-ScummVmGameWindow {
    param([System.Diagnostics.Process]$TargetProcess)

    $windows = @([ShiversWindowCapture]::GetVisibleWindows($TargetProcess.Id))
    $preferred = @($windows | Where-Object {
        ($_.Title -like 'Shivers*' -or $_.ClassName -eq 'SDL_app') -and $_.ClassName -ne 'ConsoleWindowClass'
    } | Sort-Object @{ Expression = { ($_.Bounds.Right - $_.Bounds.Left) * ($_.Bounds.Bottom - $_.Bounds.Top) }; Descending = $true })
    if ($preferred.Count -eq 0) {
        throw 'Could not locate the visible ScummVM game window.'
    }
    return $preferred[0]
}

function Save-WindowCapture {
    param(
        [int]$Left,
        [int]$Top,
        [int]$Right,
        [int]$Bottom,
        [string]$OutputPath
    )

    $width = $Right - $Left
    $height = $Bottom - $Top
    if ($width -le 0 -or $height -le 0) {
        throw "Invalid ScummVM window bounds: ${width}x${height}"
    }

    $bitmap = New-Object System.Drawing.Bitmap($width, $height)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen($Left, $Top, 0, 0, $bitmap.Size)
        $bitmap.Save($OutputPath, [System.Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

$shell = New-Object -ComObject WScript.Shell
$moveDeadline = [DateTime]::UtcNow.AddSeconds(25)
$initialWindow = $null
do {
    try {
        $initialWindow = Get-ScummVmGameWindow -TargetProcess $process
    }
    catch {
        Start-Sleep -Milliseconds 250
    }
} while ($null -eq $initialWindow -and [DateTime]::UtcNow -lt $moveDeadline)
if ($null -eq $initialWindow) {
    throw 'Could not locate the ScummVM game window for primary-monitor placement.'
}
[void][ShiversWindowCapture]::MoveWindow($initialWindow.Handle, 100, 100, 660, 520, $true)
Start-Sleep -Milliseconds 500
$captures = @()
$elapsed = 0
$captureDelays = switch ($CaptureProfile) {
    'menu' { @(35) }
    'intro-text' { @(25, 10, 10, 10) }
    'intro-subtitles' { @(55, 10, 10, 10, 10, 10, 10, 10, 10, 10) }
    'poc-new-game' { @(35, 5, 10, 10, 5, 5, 5, 5) }
    'poc-earliest-name' { @(35, 5, 5) }
    'poc-pic922' { @(20, 5, 5) }
    'poc-first-subtitles' { @(35, 5, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10) }
    'poc-audio-subtitle' { @(35, 1, 1, 4, 1, 4, 1) }
    'poc-full-movie-subtitles' { @(35, 6, 2, 16, 6, 6) }
    default { @(5, 8, 8) }
}
$captureIndex = 0
foreach ($delay in $captureDelays) {
    Start-Sleep -Seconds $delay
    $elapsed += $delay
    $process.Refresh()
    if ($process.HasExited) {
        break
    }

    $gameWindow = Get-ScummVmGameWindow -TargetProcess $process
    $activated = [ShiversWindowCapture]::SetForegroundWindow($gameWindow.Handle)
    Start-Sleep -Milliseconds 400
    $dpiScale = [ShiversWindowCapture]::GetDpiForWindow($gameWindow.Handle) / 96.0
    $physicalLeft = [int][Math]::Round($gameWindow.Bounds.Left * $dpiScale)
    $physicalTop = [int][Math]::Round($gameWindow.Bounds.Top * $dpiScale)
    $physicalRight = [int][Math]::Round($gameWindow.Bounds.Right * $dpiScale)
    $physicalBottom = [int][Math]::Round($gameWindow.Bounds.Bottom * $dpiScale)
    $capturePath = Join-Path $screenshotPath ('capture_{0:D3}s.png' -f $elapsed)
    Save-WindowCapture `
        -Left $physicalLeft `
        -Top $physicalTop `
        -Right $physicalRight `
        -Bottom $physicalBottom `
        -OutputPath $capturePath
    $captures += [PSCustomObject]@{
        ElapsedSeconds = $elapsed
        Activated = $activated
        WindowTitle = $gameWindow.Title
        WindowClass = $gameWindow.ClassName
        Left = $gameWindow.Bounds.Left
        Top = $gameWindow.Bounds.Top
        Right = $gameWindow.Bounds.Right
        Bottom = $gameWindow.Bounds.Bottom
        DpiScale = $dpiScale
        Capture = $capturePath
    }

    if ($CaptureProfile -in @('poc-new-game', 'poc-earliest-name', 'poc-pic922', 'poc-first-subtitles', 'poc-audio-subtitle', 'poc-full-movie-subtitles') -and $captureIndex -eq 0) {
        [void][ShiversWindowCapture]::SetForegroundWindow($gameWindow.Handle)
        Start-Sleep -Milliseconds 400
        $clickX = $gameWindow.Bounds.Left + [int][Math]::Round(($gameWindow.Bounds.Right - $gameWindow.Bounds.Left) * 0.35)
        $clickY = $gameWindow.Bounds.Top + [int][Math]::Round(($gameWindow.Bounds.Bottom - $gameWindow.Bounds.Top) * 0.80)
        [ShiversWindowCapture]::ClickAt($clickX, $clickY)
    }
    elseif ($CaptureProfile -in @('poc-new-game', 'poc-earliest-name', 'poc-pic922', 'poc-first-subtitles', 'poc-full-movie-subtitles') -and $captureIndex -eq 1) {
        [void][ShiversWindowCapture]::SetForegroundWindow($gameWindow.Handle)
        Start-Sleep -Milliseconds 400
        $letterAX = $gameWindow.Bounds.Left + [int][Math]::Round(($gameWindow.Bounds.Right - $gameWindow.Bounds.Left) * 0.24)
        $letterAY = $gameWindow.Bounds.Top + [int][Math]::Round(($gameWindow.Bounds.Bottom - $gameWindow.Bounds.Top) * 0.61)
        [ShiversWindowCapture]::ClickAt($letterAX, $letterAY)
    }
    elseif ($CaptureProfile -in @('poc-new-game', 'poc-first-subtitles', 'poc-full-movie-subtitles') -and $captureIndex -eq 2) {
        [void][ShiversWindowCapture]::SetForegroundWindow($gameWindow.Handle)
        Start-Sleep -Milliseconds 400
        $playX = $gameWindow.Bounds.Left + [int][Math]::Round(($gameWindow.Bounds.Right - $gameWindow.Bounds.Left) * 0.20)
        $playY = $gameWindow.Bounds.Top + [int][Math]::Round(($gameWindow.Bounds.Bottom - $gameWindow.Bounds.Top) * 0.91)
        [ShiversWindowCapture]::ClickAt($playX, $playY)
    }
    elseif ($CaptureProfile -eq 'poc-new-game' -and $captureIndex -eq 3) {
        [void][ShiversWindowCapture]::SetForegroundWindow($gameWindow.Handle)
        Start-Sleep -Milliseconds 400
        $skipX = $gameWindow.Bounds.Left + [int][Math]::Round(($gameWindow.Bounds.Right - $gameWindow.Bounds.Left) * 0.50)
        $skipY = $gameWindow.Bounds.Top + [int][Math]::Round(($gameWindow.Bounds.Bottom - $gameWindow.Bounds.Top) * 0.50)
        [ShiversWindowCapture]::ClickAt($skipX, $skipY)
    }
    elseif ($CaptureProfile -eq 'poc-new-game' -and $captureIndex -eq 4) {
        [void][ShiversWindowCapture]::SetForegroundWindow($gameWindow.Handle)
        Start-Sleep -Milliseconds 400
        $gateX = $gameWindow.Bounds.Left + [int][Math]::Round(($gameWindow.Bounds.Right - $gameWindow.Bounds.Left) * 0.50)
        $gateY = $gameWindow.Bounds.Top + [int][Math]::Round(($gameWindow.Bounds.Bottom - $gameWindow.Bounds.Top) * 0.29)
        [ShiversWindowCapture]::ClickAt($gateX, $gateY)
    }
    elseif ($CaptureProfile -eq 'poc-audio-subtitle' -and $captureIndex -eq 5) {
        [void][ShiversWindowCapture]::SetForegroundWindow($gameWindow.Handle)
        Start-Sleep -Milliseconds 400
        $letterAX = $gameWindow.Bounds.Left + [int][Math]::Round(($gameWindow.Bounds.Right - $gameWindow.Bounds.Left) * 0.24)
        $letterAY = $gameWindow.Bounds.Top + [int][Math]::Round(($gameWindow.Bounds.Bottom - $gameWindow.Bounds.Top) * 0.61)
        [ShiversWindowCapture]::ClickAt($letterAX, $letterAY)
    }
    $captureIndex++
}

$process.Refresh()
$gracefulClose = $true
if (-not $process.HasExited) {
    [void]$process.CloseMainWindow()
    if (-not $process.WaitForExit(5000)) {
        $gracefulClose = $false
        Stop-Process -Id $process.Id -Force
        $process.WaitForExit()
    }
}

$screenshots = @(Get-ChildItem -LiteralPath $screenshotPath -File -Filter '*.png' | Sort-Object LastWriteTime)
$result = [PSCustomObject]@{
    RunId = $RunId
    ScummVmVersion = (& $ScummVmExe --version | Select-Object -First 1)
    ScummVmSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $ScummVmExe).Hash
    GamePath = $GamePath
    GameLanguage = $GameLanguage
    ProcessId = $process.Id
    ExitCode = $process.ExitCode
    GracefulClose = $gracefulClose
    ScreenshotCount = $screenshots.Count
    ScreenshotPath = $screenshotPath
    LogPath = $logPath
}

$result | Format-List
$captures | Format-Table -AutoSize
$screenshots | Select-Object Name, Length, LastWriteTime | Format-Table -AutoSize

if ($screenshots.Count -eq 0) {
    throw 'ScummVM ran, but no screenshot was captured.'
}
