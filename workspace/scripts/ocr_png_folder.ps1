param(
    [Parameter(Mandatory = $true)]
    [string]$InputRoot,
    [Parameter(Mandatory = $true)]
    [string]$OutputCsv,
    [ValidateRange(1, 16)]
    [int]$Scale = 1
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null

function Await-Result($Operation, [Type]$ResultType) {
    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq 'AsTask' -and
            $_.IsGenericMethod -and
            $_.GetGenericArguments().Count -eq 1 -and
            $_.GetParameters().Count -eq 1 -and
            $_.ReturnType.IsGenericType
        } |
        Select-Object -First 1
    $task = $method.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    $task.Wait()
    return $task.Result
}

$resolvedInput = (Resolve-Path -LiteralPath $InputRoot).Path
$outputPath = [System.IO.Path]::GetFullPath($OutputCsv)
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) {
    throw 'Windows OCR engine is unavailable.'
}

$rows = foreach ($fileInfo in Get-ChildItem -LiteralPath $resolvedInput -Recurse -File -Filter '*.png') {
    $file = Await-Result ([Windows.Storage.StorageFile]::GetFileFromPathAsync($fileInfo.FullName)) ([Windows.Storage.StorageFile])
    $stream = Await-Result ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    try {
        $decoder = Await-Result ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        if ($Scale -gt 1) {
            $transform = [Windows.Graphics.Imaging.BitmapTransform]::new()
            $transform.ScaledWidth = [uint32]([Math]::Min(2400, $decoder.PixelWidth * $Scale))
            $transform.ScaledHeight = [uint32]([Math]::Min(2400, $decoder.PixelHeight * $Scale))
            $operation = $decoder.GetSoftwareBitmapAsync(
                [Windows.Graphics.Imaging.BitmapPixelFormat]::Rgba8,
                [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied,
                $transform,
                [Windows.Graphics.Imaging.ExifOrientationMode]::IgnoreExifOrientation,
                [Windows.Graphics.Imaging.ColorManagementMode]::DoNotColorManage
            )
            $bitmap = Await-Result $operation ([Windows.Graphics.Imaging.SoftwareBitmap])
        }
        else {
            $bitmap = Await-Result ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        }
        try {
            $result = Await-Result ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
            [pscustomobject]@{
                path = $fileInfo.FullName.Substring($resolvedInput.Length).TrimStart('\').Replace('\', '/')
                text = ($result.Text -replace "`r?`n", ' ' -replace '\s+', ' ').Trim()
            }
        }
        finally {
            $bitmap.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }
}

$outputDirectory = Split-Path -Parent $outputPath
if ($outputDirectory) {
    New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
}
$rows | Export-Csv -LiteralPath $outputPath -NoTypeInformation -Encoding UTF8
Write-Output "images=$($rows.Count)"
Write-Output "recognized=$(@($rows | Where-Object text).Count)"
Write-Output "output=$outputPath"
