<#
.SYNOPSIS
  Convert a marketing clip recorded in the viewer (WebM) to a widely-playable
  MP4 (H.264/AAC, +faststart) you can post on LinkedIn/Instagram/YouTube.

.EXAMPLE
  .\webm-to-mp4.ps1 C:\Downloads\marketingclip-sjoerd3.webm
  # -> C:\Downloads\marketingclip-sjoerd3.mp4

.EXAMPLE
  .\webm-to-mp4.ps1 clip.webm -Out promo.mp4 -Crf 18
#>
param(
  [Parameter(Mandatory = $true, Position = 0)] [string] $File,
  [string] $Out,
  [int]    $Crf = 20
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
  Write-Error "ffmpeg not found on PATH. Install it (same as for publish-to-r2.ps1)."
  exit 1
}
if (-not (Test-Path $File)) { Write-Error "File not found: $File"; exit 1 }

if (-not $Out) { $Out = [IO.Path]::ChangeExtension($File, '.mp4') }

Write-Host "Converting $File -> $Out (crf $Crf)..." -ForegroundColor Cyan
# yuv420p + faststart so it plays inline everywhere; scale to even dims just in case.
& ffmpeg -y -hide_banner -loglevel error -stats -i $File `
  -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" `
  -c:v libx264 -pix_fmt yuv420p -preset slow -crf $Crf `
  -c:a aac -b:a 192k -movflags +faststart $Out

if ($LASTEXITCODE -ne 0) { Write-Error "ffmpeg failed."; exit 1 }
Write-Host "Done: $Out" -ForegroundColor Green
