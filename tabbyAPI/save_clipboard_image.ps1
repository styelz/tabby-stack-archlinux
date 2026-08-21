param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Path
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

if (-not [IO.Path]::IsPathRooted($Path)) {
    $Path = Join-Path (Get-Location) $Path
}
$dir = Split-Path -Parent $Path
if ($dir) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

$img = [System.Windows.Forms.Clipboard]::GetImage()
if ($null -eq $img) {
    throw "Clipboard has no image. Copy the picture (Ctrl+C), then run this again."
}

$ext = [IO.Path]::GetExtension($Path).ToLowerInvariant()
$fmt = switch ($ext) {
    ".jpg" { [System.Drawing.Imaging.ImageFormat]::Jpeg }
    ".jpeg" { [System.Drawing.Imaging.ImageFormat]::Jpeg }
    ".bmp" { [System.Drawing.Imaging.ImageFormat]::Bmp }
    ".gif" { [System.Drawing.Imaging.ImageFormat]::Gif }
    default { [System.Drawing.Imaging.ImageFormat]::Png }
}
$img.Save($Path, $fmt)
Write-Output $Path
