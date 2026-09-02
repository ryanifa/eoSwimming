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

  Upload uses `rclone copyto` (never sync — sync deletes on the R2 side).

  By default the video is first NORMALISED with ffmpeg (rotation baked in, square
  pixels, +faststart, max 1080p) so it always fills the viewer — a raw camera file
  can otherwise show up small/rotated. Pass -NoReencode to skip this and upload the
  file as-is (only safe when it's already a clean, upright MP4, e.g. a workflow
  output).

.PARAMETER File     Path to the local video, e.g. C:\media\test.mp4
.PARAMETER Dest     Folder (key prefix) in the bucket. Default: swim/2026
.PARAMETER Edit     Add &edit=1 so the viewer opens straight in annotate mode.
.PARAMETER Annot    Optional annotation id to append as &a=<id>.
.PARAMETER ExpireDays  Link validity in days. Default 365 (token mode).
                       Presigned mode is capped at 7 days regardless.
.PARAMETER NoReencode  Skip the ffmpeg normalise step; upload the file unchanged.

.EXAMPLE
  .\publish-to-r2.ps1 C:\media\test.mp4
  .\publish-to-r2.ps1 C:\media\jeroen.mp4 -Dest swim/2026 -Edit
  .\publish-to-r2.ps1 C:\media\already-clean.mp4 -NoReencode
#>

[CmdletBinding()]
param(
  [Parameter(Mandatory = $true, Position = 0)] [string] $File,
  [Parameter(Position = 1)] [string] $Dest = "swim/2026",
  [switch] $Edit,
  [string] $Annot = "",
  [int] $ExpireDays = 365,
  [switch] $NoReencode
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
$dest   = "${Remote}:${Bucket}/${key}"

# --- normalise (default) so the video always fills the viewer ---
$uploadFrom = $File
$tmp = $null
if (-not $NoReencode) {
  if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    throw "ffmpeg not found on PATH. Install it (e.g. 'winget install Gyan.FFmpeg'), " +
          "or pass -NoReencode to upload as-is (only safe for an already-clean, upright MP4)."
  }
  Write-Host "1/4  Normalising video (bake rotation, square pixels, faststart)…" -ForegroundColor Cyan
  $tmp = Join-Path $env:TEMP ("eoswim-norm-" + [guid]::NewGuid().ToString('N').Substring(0, 8) + ".mp4")
  # ffmpeg auto-applies any rotation flag on decode -> upright frames, no rotate tag.
  # setsar=1 fixes non-square (anamorphic) pixels; scale caps width at 1080p.
  ffmpeg -y -hide_banner -loglevel error -stats -i $File `
    -vf "scale='min(1920,iw)':-2,setsar=1" `
    -c:v libx264 -pix_fmt yuv420p -preset fast -crf 20 `
    -c:a aac -b:a 160k -movflags +faststart $tmp
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $tmp)) {
    if ($tmp) { Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue }
    throw "ffmpeg normalise failed (exit $LASTEXITCODE)."
  }
  $uploadFrom = $tmp
}

Write-Host "2/4  Uploading $name -> ${Remote}:${Bucket}/${key}" -ForegroundColor Cyan
rclone copyto --progress $uploadFrom $dest    # copyto: lands at the exact key
$rc = $LASTEXITCODE
if ($tmp) { Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue }
if ($rc -ne 0) { throw "rclone copyto failed (exit $rc)." }

$tokenMode = $MediaBase -and $Secret
if ($tokenMode) {
  Write-Host "3/4  Signing a private token (valid $ExpireDays days)" -ForegroundColor Cyan
  $exp = [int][DateTimeOffset]::UtcNow.ToUnixTimeSeconds() + ($ExpireDays * 86400)
  $sig = New-SignedToken $Secret "$key`n$exp"     # HMAC over "<key>\n<exp>"
  $base = $MediaBase.TrimEnd('/')
  $mediaUrl = "$base/$(EncodeKey $key)?e=$exp&t=$(Encode $sig)"
  $validNote = "$ExpireDays days"
  Write-Host "4/4  Building the short private viewer link" -ForegroundColor Cyan
  $viewer = "$ViewerBase`?k=$(EncodeKey $key)&e=$exp&t=$(Encode $sig)"
} else {
  Write-Host "3/4  No Worker configured -> presigned link (max 7 days)" -ForegroundColor DarkYellow
  $hours = [Math]::Min($ExpireDays * 24, 168)
  $presigned = (rclone link "${Remote}:${Bucket}/${key}" --expire "${hours}h").Trim()
  if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($presigned)) { throw "rclone link failed." }
  $mediaUrl = $presigned
  $validNote = "$([Math]::Round($hours/24,1)) days (presigned limit)"
  Write-Host "4/4  Building the viewer link" -ForegroundColor Cyan
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
