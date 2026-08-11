<#
.SYNOPSIS
  Delete the GitHub releases whose videos are already safely in R2. Dry-run by
  default; only deletes a release once every one of its videos is confirmed in R2.

.DESCRIPTION
  Safety-first cleanup after migrate-releases-to-r2.ps1:
    * For each release it works out the expected R2 key(s) (same rules as the
      migration): composite.mp4 -> swim/2026/<tag>.mp4, and with -IncludeRaw the
      raw videos -> raw/<tag>/<name>.
    * It checks those keys actually EXIST in R2 (via rclone).
    * A release is "safe to delete" only when ALL its videos are present in R2.
  Without -Execute it just reports (dry run). With -Execute it deletes the safe
  releases AND their tags via the GitHub CLI (`gh`).

  Requires:
    - rclone remote "r2" -> media-private   (to verify)
    - GitHub CLI `gh`, logged in (`gh auth login`)   (only for -Execute)

.PARAMETER Execute      Actually delete. Omit for a dry run (safe, default).
.PARAMETER IncludeRaw   Also require the raw videos to be in R2 before deleting.
.PARAMETER Dest         Composite key prefix. Default: swim/2026
.PARAMETER RawDest      Raw key prefix. Default: raw
.PARAMETER Only         Only consider these tags (space/comma separated).

.EXAMPLE
  .\delete-migrated-releases.ps1 -IncludeRaw            # dry run: what is safe to delete
  .\delete-migrated-releases.ps1 -IncludeRaw -Execute  # really delete the safe ones
#>

[CmdletBinding()]
param(
  [switch] $Execute,
  [switch] $IncludeRaw,
  [string] $Dest = "swim/2026",
  [string] $RawDest = "raw",
  [string[]] $Only
)

# ---- config (no secrets here) ----
$Owner  = "ryanifa"
$Repo   = "eoSwimming"
$Remote = "r2"
$Bucket = "media-private"
# ----------------------------------

$ErrorActionPreference = "Stop"
$destTrim = $Dest.Trim('/')
$rawTrim  = $RawDest.Trim('/')

function IsVideo([string]$name) { $name -match '\.(mp4|mov|m4v|webm)$' }
function R2Exists([string]$key) {
  $i = $key.LastIndexOf('/')
  $dir = $key.Substring(0, $i); $file = $key.Substring($i + 1)
  $list = & rclone lsf "${Remote}:${Bucket}/${dir}/" 2>$null
  if ($LASTEXITCODE -ne 0) { return $false }
  return ($list -contains $file)
}

if (-not (Get-Command rclone -ErrorAction SilentlyContinue)) { throw "rclone not found on PATH." }
if ($Execute -and -not (Get-Command gh -ErrorAction SilentlyContinue)) {
  throw "gh (GitHub CLI) not found — needed to delete. Install it and run 'gh auth login', or delete the listed releases via the website."
}

Write-Host "Fetching releases for $Owner/$Repo ..." -ForegroundColor Cyan
$api = "https://api.github.com/repos/$Owner/$Repo/releases?per_page=100"
$rels = Invoke-RestMethod -Uri $api -Headers @{ 'User-Agent' = 'eoswim-cleanup'; 'Accept' = 'application/vnd.github+json' }

$safe = @()
foreach ($rel in $rels) {
  $tag = $rel.tag_name
  if ($Only -and ($Only -notcontains $tag)) { continue }

  # expected R2 keys for this release (same rules as the migration)
  $expected = @()
  if ($rel.assets | Where-Object { $_.name -eq 'composite.mp4' }) { $expected += "$destTrim/$tag.mp4" }
  if ($IncludeRaw) {
    foreach ($a in $rel.assets) {
      if ($a.name -eq 'composite.mp4') { continue }
      if (IsVideo $a.name) { $expected += "$rawTrim/$tag/$($a.name)" }
    }
  }

  if ($expected.Count -eq 0) {
    Write-Host "keep    $tag  (no videos to check — decide by hand)" -ForegroundColor DarkGray
    continue
  }

  $missing = @($expected | Where-Object { -not (R2Exists $_) })
  if ($missing.Count -eq 0) {
    Write-Host "SAFE    $tag  ($($expected.Count) video(s) confirmed in R2)" -ForegroundColor Green
    $safe += $tag
  } else {
    Write-Host "keep    $tag  (NOT in R2 yet: $($missing -join ', '))" -ForegroundColor Yellow
  }
}

Write-Host ""
if ($safe.Count -eq 0) { Write-Host "Nothing is safe to delete." -ForegroundColor Yellow; return }

if (-not $Execute) {
  Write-Host "DRY RUN — would delete $($safe.Count) release(s): $($safe -join ', ')" -ForegroundColor Yellow
  Write-Host "Re-run with -Execute to actually delete them (and their tags)." -ForegroundColor DarkGray
  return
}

Write-Host "Deleting $($safe.Count) migrated release(s)..." -ForegroundColor Cyan
foreach ($tag in $safe) {
  Write-Host "  delete $tag" -ForegroundColor Red
  gh release delete "$tag" --repo "$Owner/$Repo" --yes --cleanup-tag
  if ($LASTEXITCODE -ne 0) { Write-Host "    failed for $tag" -ForegroundColor Red }
}
Write-Host "Done." -ForegroundColor Green
