<#
.SYNOPSIS
  One-shot: copy the videos out of your GitHub releases into Cloudflare R2 and
  build a private ?k= viewer link for each. Writes a table of what moved.

.DESCRIPTION
  For each release in the repo:
    * a `composite.mp4` asset (the finished overlay video) -> r2:.../<Dest>/<tag>.mp4
    * with -IncludeRaw, every OTHER video asset (raw source) -> r2:.../<RawDest>/<tag>/<name>
  Each upload is `rclone copy` (never sync). A private viewer link is built for
  every uploaded file. NOTHING is deleted from GitHub — you remove the releases
  yourself once you've checked the new links work.

  Run with -DryRun first to see what it *would* do.

  Requires (same as publish-to-r2.ps1):
    - rclone remote "r2" -> the private media-private bucket
    - env EOSWIM_MEDIA_BASE and EOSWIM_R2_TOKEN_SECRET (for the links)

.PARAMETER Dest         Key prefix for composite videos. Default: swim/2026
.PARAMETER RawDest      Key prefix for raw source videos. Default: raw
.PARAMETER IncludeRaw   Also migrate non-composite video assets (raw sources).
.PARAMETER ExpireDays   Link validity in days. Default 365.
.PARAMETER Out          Where to write the table. Default: migration-links.md
.PARAMETER DryRun       List what would happen; download/upload nothing.

.EXAMPLE
  .\migrate-releases-to-r2.ps1 -DryRun
  .\migrate-releases-to-r2.ps1 -IncludeRaw
#>

[CmdletBinding()]
param(
  [string] $Dest = "swim/2026",
  [string] $RawDest = "raw",
  [switch] $IncludeRaw,
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
$destTrim = $Dest.Trim('/')
$rawTrim  = $RawDest.Trim('/')

function Encode([string]$s) { [System.Uri]::EscapeDataString($s) }
function EncodeKey([string]$k) { (($k -split '/') | ForEach-Object { Encode $_ }) -join '/' }
function IsVideo([string]$name) { $name -match '\.(mp4|mov|m4v|webm)$' }
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

  # build the list of files to migrate for this release
  $jobs = @()
  $composite = $rel.assets | Where-Object { $_.name -eq 'composite.mp4' } | Select-Object -First 1
  if ($composite) {
    $jobs += @{ Url = $composite.browser_download_url; Folder = $destTrim; Local = "$tag.mp4"; Key = "$destTrim/$tag.mp4"; Kind = 'composite'; Size = $composite.size }
  }
  if ($IncludeRaw) {
    foreach ($a in $rel.assets) {
      if ($a.name -eq 'composite.mp4') { continue }
      if (-not (IsVideo $a.name)) { continue }
      $jobs += @{ Url = $a.browser_download_url; Folder = "$rawTrim/$tag"; Local = $a.name; Key = "$rawTrim/$tag/$($a.name)"; Kind = 'raw'; Size = $a.size }
    }
  }

  if ($jobs.Count -eq 0) {
    $vids = @($rel.assets | Where-Object { IsVideo $_.name })
    if ($vids.Count -gt 0) { Write-Host "skip  $tag  (has raw video — run with -IncludeRaw to migrate it)" -ForegroundColor DarkYellow }
    else { Write-Host "skip  $tag  (no video assets)" -ForegroundColor DarkGray }
    continue
  }

  foreach ($j in $jobs) {
    $mb = [math]::Round($j.Size / 1MB, 1)
    if ($DryRun) {
      Write-Host "would migrate  $tag  [$($j.Kind)]  ($mb MB)  ->  $Bucket/$($j.Key)" -ForegroundColor Yellow
      continue
    }
    Write-Host "migrate  $tag  [$($j.Kind)]  ($mb MB)" -ForegroundColor Cyan
    $tmp = Join-Path $env:TEMP $j.Local
    curl.exe -L --fail -o "$tmp" $j.Url
    if ($LASTEXITCODE -ne 0) { Write-Host "  download failed — skipping" -ForegroundColor Red; continue }
    rclone copy "$tmp" "${Remote}:${Bucket}/$($j.Folder)/"
    $ok = ($LASTEXITCODE -eq 0)
    Remove-Item $tmp -ErrorAction SilentlyContinue
    if (-not $ok) { Write-Host "  rclone copy failed — skipping" -ForegroundColor Red; continue }

    $link = if ($tokenMode) { New-ViewerLink $j.Key } else { "(set env vars to build a link)" }
    $rows += [pscustomobject]@{ Tag = $tag; Kind = $j.Kind; Key = $j.Key; Link = $link }
    Write-Host "  ok -> $($j.Key)" -ForegroundColor Green
  }
}

if ($DryRun) { Write-Host "`nDry run only — nothing was downloaded or uploaded." -ForegroundColor Yellow; return }

# write the table
$md = @("# Migrated videos", "", "| Release tag | Kind | R2 key | Viewer link (valid $ExpireDays days) |", "|---|---|---|---|")
foreach ($r in $rows) { $md += "| $($r.Tag) | $($r.Kind) | ``$($r.Key)`` | $($r.Link) |" }
$md -join "`r`n" | Set-Content -Path $Out -Encoding UTF8

Write-Host "`nDone. Migrated $($rows.Count) file(s)." -ForegroundColor Green
Write-Host "Table written to: $Out" -ForegroundColor Green
Write-Host "Check a few links, then delete the old GitHub releases when you're happy." -ForegroundColor DarkGray
