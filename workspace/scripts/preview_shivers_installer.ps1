param([string]$PackageName='Shivers_Korean_Patch_v1.0_RC1')
$ErrorActionPreference='Stop'
$project=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$exe=Join-Path $project ('dist/'+$PackageName+'/ShiversKoreanPatch.exe')
$qa=Join-Path $project 'qa/installer_rc1_20260905_03'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$assembly=[Reflection.Assembly]::LoadFile($exe)
$form=[Activator]::CreateInstance($assembly.GetType('PatcherForm'),$true)
try {
 $form.ShowInTaskbar=$false
 $form.StartPosition=[Windows.Forms.FormStartPosition]::Manual
 $form.Location=New-Object Drawing.Point(-30000,-30000)
 $form.Show()
 [Windows.Forms.Application]::DoEvents()
 $bitmap=New-Object Drawing.Bitmap($form.Width,$form.Height)
 try {
  $form.DrawToBitmap($bitmap,(New-Object Drawing.Rectangle(0,0,$form.Width,$form.Height)))
  $bitmap.Save((Join-Path $qa 'installer_ui.png'),[Drawing.Imaging.ImageFormat]::Png)
 } finally { $bitmap.Dispose() }
 Write-Output "ui_preview=$qa/installer_ui.png"
} finally { $form.Close(); $form.Dispose() }
