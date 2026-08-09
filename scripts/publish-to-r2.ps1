<#
.SYNOPSIS
  Upload a (locally rendered) video to Cloudflare R2 and build a ready-to-share
  viewer link — in one command. Copies the viewer link to your clipboard.

.DESCRIPTION
  Does the whole chain so you never hand-encode a URL again:
    1. rclone copy <file>  -> r2:<bucket>/<dest>/<name>   (copy, never sync)
    2. rclone link ... --expire <hours>h                  -> presigned URL
    3. URL-encode it and build  viewer.html?v=<encoded>
    4. print both + copy the viewer link to the clipboard

  Requirements (already set up on this PC):
    - rclone configured with a remote named "r2" (see rclone.conf)
    - the bucket below exists and the token can Read & Write it

.PARAMETER File
  Path to the local video, e.g.  C:\media\test.mp4

.PARAMETER Dest
  Folder (key prefix) inside the bucket. Default: swim/2026

.PARAMETER Edit
  Add &edit=1 so the viewer opens straight in annotate mode.

.PARAMETER Annot
  Optional annotation id to append as &a=<id>.

.PARAMETER ExpireHours
  Presigned-URL validity in hours. Max 168 (7 days, a hard SigV4 limit). Default 168.

.EXAMPLE
  .\publish-to-r2.ps1 -File C:\media\test.mp4
  .\publish-to-r2.ps1 C:\media\jeroen.mp4 -Dest swim/2026 -Edit
#>

[CmdletBinding()]
param(
  [Parameter(Mandatory = $true, Position = 0)] [string] $File,
  [Parameter(Position = 1)] [string] $Dest = "swim/2026",
  [switch] $Edit,
  [string] $Annot = "",
  [int] $ExpireHours = 168
)

# ---- config (no secrets here; credentials live in the rclone "r2" remote) ----
$Remote     = "r2"
$Bucket     = "media-private"
$ViewerBase = "https://ryanifa.github.io/eoSwimming/viewer.html"
# -----------------------------------------------------------------------------

$ErrorActionPreference = "Stop"

if (-not (Get-Command rclone -ErrorAction SilentlyContinue)) {
  throw "rclone not found on PATH. Install it or open the shell where it works."
}
if (-not (Test-Path -LiteralPath $File)) {
  throw "File not found: $File"
}
if ($ExpireHours -lt 1 -or $ExpireHours -gt 168) {
  throw "ExpireHours must be between 1 and 168 (7 days is the presigned max)."
}

$name = Split-Path -Leaf $File
$dst  = ($Dest.Trim("/"))            # normalise: no leading/trailing slash
$key  = "$dst/$name"                 # object key inside the bucket
$target = "${Remote}:${Bucket}/${dst}/"

Write-Host "1/3  Uploading $name -> ${Remote}:${Bucket}/${key}" -ForegroundColor Cyan
# copy (never sync): sync would delete other files on the R2 side.
# rclone sets Content-Type from the .mp4 extension automatically (video/mp4).
rclone copy --progress $File $target
if ($LASTEXITCODE -ne 0) { throw "rclone copy failed (exit $LASTEXITCODE)." }

Write-Host "2/3  Making a presigned link (valid $ExpireHours h)" -ForegroundColor Cyan
$presigned = (rclone link "${Remote}:${Bucket}/${key}" --expire "${ExpireHours}h").Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($presigned)) {
  throw "rclone link failed (exit $LASTEXITCODE)."
}

Write-Host "3/3  Building the viewer link" -ForegroundColor Cyan
$encoded = [System.Uri]::EscapeDataString($presigned)
$viewer  = "$ViewerBase`?v=$encoded"
if ($Annot -ne "") { $viewer += "&a=$Annot" }
if ($Edit)          { $viewer += "&edit=1" }

# copy the viewer link to the clipboard for easy sharing/opening
try { Set-Clipboard -Value $viewer; $copied = $true } catch { $copied = $false }

$days = [math]::Round($ExpireHours / 24, 1)
Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "  object    : ${Bucket}/${key}"
Write-Host "  presigned : $presigned"
Write-Host ""
Write-Host "  VIEWER LINK (valid ~$days days):" -ForegroundColor Yellow
Write-Host "  $viewer"
if ($copied) { Write-Host "  (copied to clipboard)" -ForegroundColor DarkGray }
Write-Host ""
Write-Host "Note: the link stops working after $ExpireHours h (presigned limit)." -ForegroundColor DarkGray
Write-Host "For a permanent shareable link you'll want the Cloudflare Worker path later." -ForegroundColor DarkGray
