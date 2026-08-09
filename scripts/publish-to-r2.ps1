<#
.SYNOPSIS
  Upload a (locally rendered) video to Cloudflare R2 and build a ready-to-share
  viewer link in one command. Copies the viewer link to your clipboard.

.DESCRIPTION
  Two modes, chosen automatically:

  * TOKEN mode (preferred) — when both env vars are set:
        EOSWIM_MEDIA_BASE       e.g. https://eoswim-media.you.workers.dev
        EOSWIM_R2_TOKEN_SECRET  the same secret you gave the Worker
    Builds a short, private, long-lived link:
        viewer.html?k=<key>&e=<expiry>&t=<token>
    served by your media Worker. No 7-day limit; you choose -ExpireDays.

  * PRESIGNED mode (fallback) — when those env vars are NOT set:
    Uses `rclone link` (presigned, max 7 days) and builds viewer.html?v=<url>.
    Handy before the Worker is deployed.

  Upload is always `rclone copy` (never sync — sync deletes on the R2 side).

.PARAMETER File     Path to the local video, e.g. C:\media\test.mp4
.PARAMETER Dest     Folder (key prefix) in the bucket. Default: swim/2026
.PARAMETER Edit     Add &edit=1 so the viewer opens straight in annotate mode.
.PARAMETER Annot    Optional annotation id to append as &a=<id>.
.PARAMETER ExpireDays  Link validity in days. Default 365 (token mode).
                       Presigned mode is capped at 7 days regardless.

.EXAMPLE
  .\publish-to-r2.ps1 C:\media\test.mp4
  .\publish-to-r2.ps1 C:\media\jeroen.mp4 -Dest swim/2026 -Edit
#>

[CmdletBinding()]
param(
  [Parameter(Mandatory = $true, Position = 0)] [string] $File,
  [Parameter(Position = 1)] [string] $Dest = "swim/2026",
  [switch] $Edit,
  [string] $Annot = "",
  [int] $ExpireDays = 365
)

# ---- config (no secrets here; R2 credentials live in the rclone "r2" remote) --
$Remote     = "r2"
$Bucket     = "media-private"
$ViewerBase = "https://ryanifa.github.io/eoSwimming/viewer.html"
# media Worker + signing secret come from the environment (see worker/README.md)
$MediaBase  = $env:EOSWIM_MEDIA_BASE
$Secret     = $env:EOSWIM_R2_TOKEN_SECRET
# -----------------------------------------------------------------------------

$ErrorActionPreference = "Stop"

function Encode([string]$s) { [System.Uri]::EscapeDataString($s) }
function EncodeKey([string]$k) { (($k -split '/') | ForEach-Object { Encode $_ }) -join '/' }
function New-SignedToken([string]$secret, [string]$message) {
  $h = [System.Security.Cryptography.HMACSHA256]::new([Text.Encoding]::UTF8.GetBytes($secret))
  try { $bytes = $h.ComputeHash([Text.Encoding]::UTF8.GetBytes($message)) } finally { $h.Dispose() }
  [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

if (-not (Get-Command rclone -ErrorAction SilentlyContinue)) {
  throw "rclone not found on PATH."
}
if (-not (Test-Path -LiteralPath $File)) { throw "File not found: $File" }
if ($ExpireDays -lt 1) { throw "ExpireDays must be >= 1." }

$name   = Split-Path -Leaf $File
$dst    = $Dest.Trim("/")
$key    = "$dst/$name"                       # object key inside the bucket
$target = "${Remote}:${Bucket}/${dst}/"

Write-Host "1/3  Uploading $name -> ${Remote}:${Bucket}/${key}" -ForegroundColor Cyan
rclone copy --progress $File $target         # copy, never sync
if ($LASTEXITCODE -ne 0) { throw "rclone copy failed (exit $LASTEXITCODE)." }

$tokenMode = $MediaBase -and $Secret
if ($tokenMode) {
  Write-Host "2/3  Signing a private token (valid $ExpireDays days)" -ForegroundColor Cyan
  $exp = [int][DateTimeOffset]::UtcNow.ToUnixTimeSeconds() + ($ExpireDays * 86400)
  $sig = New-SignedToken $Secret "$key`n$exp"     # HMAC over "<key>\n<exp>"
  $base = $MediaBase.TrimEnd('/')
  $mediaUrl = "$base/$(EncodeKey $key)?e=$exp&t=$(Encode $sig)"
  $validNote = "$ExpireDays days"
  Write-Host "3/3  Building the short private viewer link" -ForegroundColor Cyan
  $viewer = "$ViewerBase`?k=$(EncodeKey $key)&e=$exp&t=$(Encode $sig)"
} else {
  Write-Host "2/3  No Worker configured -> presigned link (max 7 days)" -ForegroundColor DarkYellow
  $hours = [Math]::Min($ExpireDays * 24, 168)
  $presigned = (rclone link "${Remote}:${Bucket}/${key}" --expire "${hours}h").Trim()
  if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($presigned)) { throw "rclone link failed." }
  $mediaUrl = $presigned
  $validNote = "$([Math]::Round($hours/24,1)) days (presigned limit)"
  Write-Host "3/3  Building the viewer link" -ForegroundColor Cyan
  $viewer = "$ViewerBase`?v=$(Encode $presigned)"
}

if ($Annot -ne "") { $viewer += "&a=$Annot" }
if ($Edit)          { $viewer += "&edit=1" }

try { Set-Clipboard -Value $viewer; $copied = $true } catch { $copied = $false }

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "  object    : ${Bucket}/${key}"
Write-Host "  media URL : $mediaUrl"
Write-Host ""
Write-Host "  VIEWER LINK (valid $validNote):" -ForegroundColor Yellow
Write-Host "  $viewer"
if ($copied) { Write-Host "  (copied to clipboard)" -ForegroundColor DarkGray }
if (-not $tokenMode) {
  Write-Host ""
  Write-Host "Tip: deploy the media Worker and set EOSWIM_MEDIA_BASE + EOSWIM_R2_TOKEN_SECRET" -ForegroundColor DarkGray
  Write-Host "     to get short, private, long-lived links instead of this presigned one." -ForegroundColor DarkGray
}
