<#
.SYNOPSIS
  One-shot: copy every GitHub-release composite.mp4 into Cloudflare R2 and build a
  private ?k= viewer link for each. Writes a table of tag -> link to a file.

.DESCRIPTION
  For each release in the repo that has a `composite.mp4` asset:
    1. download it from the release
    2. rclone copy it to  r2:media-private/<Dest>/<tag>.mp4   (copy, never sync)
    3. build a private viewer link (token mode; needs the two env vars)
  Nothing is deleted from GitHub — you remove the releases yourself once you've
  checked the new links work.

  Run with -DryRun first to see what it *would* do.

  Requires (same as publish-to-r2.ps1):
    - rclone remote "r2" -> the private media-private bucket
    - env EOSWIM_MEDIA_BASE and EOSWIM_R2_TOKEN_SECRET (for the links)

.PARAMETER Dest         Key prefix in the bucket. Default: swim/2026
.PARAMETER ExpireDays   Link validity in days. Default 365.
.PARAMETER Out          Where to write the tag->link table. Default: migration-links.md
.PARAMETER DryRun       List what would happen; download/upload nothing.

.EXAMPLE
  .\migrate-releases-to-r2.ps1 -DryRun
  .\migrate-releases-to-r2.ps1 -Dest swim/2026
#>

[CmdletBinding()]
param(
  [string] $Dest = "swim/2026",
  [int] $ExpireDays = 365,
  [string] $Out = "migration-links.md",
  [switch] $DryRun
)

# ---- config (no secrets here) ----
$Owner      = "ryanifa"
$Repo       = "eoSwimming"
$Remote     = "r2"
$Bucket     = "media-private"
$ViewerBase = "https://ryanifa.github.io/eoSwimming/viewer.html"
$MediaBase  = $env:EOSWIM_MEDIA_BASE
$Secret     = $env:EOSWIM_R2_TOKEN_SECRET
# ----------------------------------

$ErrorActionPreference = "Stop"

function Encode([string]$s) { [System.Uri]::EscapeDataString($s) }
function EncodeKey([string]$k) { (($k -split '/') | ForEach-Object { Encode $_ }) -join '/' }
function New-SignedToken([string]$secret, [string]$message) {
  $h = [System.Security.Cryptography.HMACSHA256]::new([Text.Encoding]::UTF8.GetBytes($secret))
  try { $bytes = $h.ComputeHash([Text.Encoding]::UTF8.GetBytes($message)) } finally { $h.Dispose() }
  [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}
function New-ViewerLink([string]$key) {
  $exp = [int][DateTimeOffset]::UtcNow.ToUnixTimeSeconds() + ($ExpireDays * 86400)
  $sig = New-SignedToken $Secret "$key`n$exp"
  "$ViewerBase`?k=$(EncodeKey $key)&e=$exp&t=$(Encode $sig)"
}

if (-not (Get-Command rclone -ErrorAction SilentlyContinue)) { throw "rclone not found on PATH." }
$tokenMode = $MediaBase -and $Secret
if (-not $tokenMode -and -not $DryRun) {
  Write-Host "WARNING: EOSWIM_MEDIA_BASE / EOSWIM_R2_TOKEN_SECRET not set — will upload but cannot build ?k= links." -ForegroundColor DarkYellow
}

Write-Host "Fetching releases for $Owner/$Repo ..." -ForegroundColor Cyan
$api = "https://api.github.com/repos/$Owner/$Repo/releases?per_page=100"
$rels = Invoke-RestMethod -Uri $api -Headers @{ 'User-Agent' = 'eoswim-migrate'; 'Accept' = 'application/vnd.github+json' }
if ($rels.Count -ge 100) { Write-Host "Note: 100 releases returned — there may be more (pagination not handled)." -ForegroundColor DarkYellow }

$rows = @()
foreach ($rel in $rels) {
  $tag = $rel.tag_name
  $asset = $rel.assets | Where-Object { $_.name -eq 'composite.mp4' } | Select-Object -First 1
  if (-not $asset) { Write-Host "skip  $tag  (no composite.mp4)" -ForegroundColor DarkGray; continue }

  $key = "$($Dest.Trim('/'))/$tag.mp4"
  if ($DryRun) {
    Write-Host "would migrate  $tag  ($([math]::Round($asset.size/1MB,1)) MB)  ->  $Bucket/$key" -ForegroundColor Yellow
    continue
  }

  $tmp = Join-Path $env:TEMP "$tag.mp4"
  Write-Host "migrate  $tag  ($([math]::Round($asset.size/1MB,1)) MB)" -ForegroundColor Cyan
  curl.exe -L --fail -o "$tmp" $asset.browser_download_url
  if ($LASTEXITCODE -ne 0) { Write-Host "  download failed — skipping" -ForegroundColor Red; continue }

  rclone copy "$tmp" "${Remote}:${Bucket}/$($Dest.Trim('/'))/"
  if ($LASTEXITCODE -ne 0) { Write-Host "  rclone copy failed — skipping" -ForegroundColor Red; Remove-Item $tmp -ErrorAction SilentlyContinue; continue }
  Remove-Item $tmp -ErrorAction SilentlyContinue

  $link = if ($tokenMode) { New-ViewerLink $key } else { "(set env vars to build a link)" }
  $rows += [pscustomobject]@{ Tag = $tag; Key = $key; Link = $link }
  Write-Host "  ok -> $key" -ForegroundColor Green
}

if ($DryRun) { Write-Host "`nDry run only — nothing was downloaded or uploaded." -ForegroundColor Yellow; return }

# write the tag -> link table
$md = @("# Migrated videos", "", "| Release tag | R2 key | Viewer link (valid $ExpireDays days) |", "|---|---|---|")
foreach ($r in $rows) { $md += "| $($r.Tag) | ``$($r.Key)`` | $($r.Link) |" }
$md -join "`r`n" | Set-Content -Path $Out -Encoding UTF8

Write-Host "`nDone. Migrated $($rows.Count) video(s)." -ForegroundColor Green
Write-Host "Link table written to: $Out" -ForegroundColor Green
Write-Host "Check a few links, then delete the old GitHub releases when you're happy." -ForegroundColor DarkGray
