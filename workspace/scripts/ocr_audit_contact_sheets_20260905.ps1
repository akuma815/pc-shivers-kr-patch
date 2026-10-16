$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$auditRoot = Join-Path $projectRoot 'qa/graphics_coverage_20260905'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
$awaitMethod = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetGenericArguments().Count -eq 1 -and
    $_.GetParameters().Count -eq 1 -and $_.ReturnType.IsGenericType
} | Select-Object -First 1
function Await-Audit($Operation, [Type]$ResultType) {
    $task = $awaitMethod.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    $task.Wait()
    return $task.Result
}
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) { throw 'Windows OCR unavailable' }
$allRows = [Collections.Generic.List[object]]::new()
foreach ($fileInfo in Get-ChildItem -LiteralPath $auditRoot -File -Filter 'excluded_*.png') {
    if ($fileInfo.Name -notmatch '^excluded_(pic|view)_\d{3}\.png$') { continue }
    $file = Await-Audit ([Windows.Storage.StorageFile]::GetFileFromPathAsync($fileInfo.FullName)) ([Windows.Storage.StorageFile])
    $stream = Await-Audit ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    try {
        $decoder = Await-Audit ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bitmap = Await-Audit ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        try {
            $result = Await-Audit ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
            $cells = @{}
            foreach ($line in $result.Lines) {
                foreach ($word in $line.Words) {
                    $b = $word.BoundingRect
                    $col = [Math]::Floor(($b.X + $b.Width/2)/270)
                    $row = [Math]::Floor(($b.Y + $b.Height/2)/200)
                    if (($b.Y % 200) -lt 24) { continue }
                    $key = "$row,$col"
                    if (-not $cells.ContainsKey($key)) { $cells[$key] = [Collections.Generic.List[string]]::new() }
                    $cells[$key].Add($word.Text)
                }
            }
            foreach ($key in $cells.Keys) {
                $allRows.Add([pscustomobject]@{sheet=$fileInfo.Name; cell=$key; text=($cells[$key] -join ' ')})
            }
        } finally { $bitmap.Dispose() }
    } finally { $stream.Dispose() }
}
$allRows | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $auditRoot 'contact_ocr.json') -Encoding UTF8
Write-Output "OCR cells=$($allRows.Count); thumbnails are candidate evidence, not exhaustive text recognition"
