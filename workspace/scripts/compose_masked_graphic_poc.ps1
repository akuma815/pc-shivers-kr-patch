param(
    [Parameter(Mandatory = $true)]
    [string]$OriginalPath,

    [Parameter(Mandatory = $true)]
    [string]$GeneratedPath,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath,

    [int]$OuterLeft,
    [int]$OuterTop,
    [int]$OuterRight,
    [int]$OuterBottom,
    [int]$InnerLeft,
    [int]$InnerTop,
    [int]$InnerRight,
    [int]$InnerBottom
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

function Get-SmoothStep([double]$value) {
    $clamped = [Math]::Max(0.0, [Math]::Min(1.0, $value))
    return $clamped * $clamped * (3.0 - 2.0 * $clamped)
}

function Get-AxisAlpha(
    [int]$position,
    [int]$outerStart,
    [int]$innerStart,
    [int]$innerEnd,
    [int]$outerEnd
) {
    if ($position -lt $outerStart -or $position -ge $outerEnd) {
        return 0.0
    }
    if ($position -ge $innerStart -and $position -lt $innerEnd) {
        return 1.0
    }
    if ($position -lt $innerStart) {
        return Get-SmoothStep (($position - $outerStart) / [double]($innerStart - $outerStart))
    }
    return Get-SmoothStep (($outerEnd - 1 - $position) / [double]($outerEnd - $innerEnd))
}

$resolvedOriginal = (Resolve-Path -LiteralPath $OriginalPath).Path
$resolvedGenerated = (Resolve-Path -LiteralPath $GeneratedPath).Path
$outputFullPath = [System.IO.Path]::GetFullPath($OutputPath)
$outputDirectory = Split-Path -Parent $outputFullPath
[System.IO.Directory]::CreateDirectory($outputDirectory) | Out-Null

$original = [System.Drawing.Bitmap]::new($resolvedOriginal)
$generated = [System.Drawing.Bitmap]::new($resolvedGenerated)
$candidate = [System.Drawing.Bitmap]::new(
    $original.Width,
    $original.Height,
    [System.Drawing.Imaging.PixelFormat]::Format32bppArgb
)
$result = [System.Drawing.Bitmap]::new(
    $original.Width,
    $original.Height,
    [System.Drawing.Imaging.PixelFormat]::Format32bppArgb
)

try {
    $graphics = [System.Drawing.Graphics]::FromImage($candidate)
    try {
        $graphics.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceCopy
        $graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
        $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
        $graphics.DrawImage(
            $generated,
            [System.Drawing.Rectangle]::new(0, 0, $candidate.Width, $candidate.Height),
            0,
            0,
            $generated.Width,
            $generated.Height,
            [System.Drawing.GraphicsUnit]::Pixel
        )
    }
    finally {
        $graphics.Dispose()
    }

    $resultGraphics = [System.Drawing.Graphics]::FromImage($result)
    try {
        $resultGraphics.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceCopy
        $resultGraphics.DrawImageUnscaled($original, 0, 0)
    }
    finally {
        $resultGraphics.Dispose()
    }

    for ($y = $OuterTop; $y -lt $OuterBottom; $y++) {
        $alphaY = Get-AxisAlpha $y $OuterTop $InnerTop $InnerBottom $OuterBottom
        for ($x = $OuterLeft; $x -lt $OuterRight; $x++) {
            $alphaX = Get-AxisAlpha $x $OuterLeft $InnerLeft $InnerRight $OuterRight
            $alpha = [Math]::Min($alphaX, $alphaY)
            if ($alpha -le 0.0) {
                continue
            }
            $source = $original.GetPixel($x, $y)
            $edit = $candidate.GetPixel($x, $y)
            $red = [int][Math]::Round($source.R * (1.0 - $alpha) + $edit.R * $alpha)
            $green = [int][Math]::Round($source.G * (1.0 - $alpha) + $edit.G * $alpha)
            $blue = [int][Math]::Round($source.B * (1.0 - $alpha) + $edit.B * $alpha)
            $result.SetPixel($x, $y, [System.Drawing.Color]::FromArgb($source.A, $red, $green, $blue))
        }
    }

    $result.Save($outputFullPath, [System.Drawing.Imaging.ImageFormat]::Png)
}
finally {
    $result.Dispose()
    $candidate.Dispose()
    $generated.Dispose()
    $original.Dispose()
}

Write-Output "output=$outputFullPath"
Write-Output "outer_mask=$OuterLeft,$OuterTop,$OuterRight,$OuterBottom"
Write-Output "inner_mask=$InnerLeft,$InnerTop,$InnerRight,$InnerBottom"
