# scripts

Helper scripts you run **on your own PC** (not in CI).

## publish-to-r2.ps1

Upload a locally rendered video to Cloudflare R2 and get a ready-to-share viewer
link in one command — no hand-encoding of URLs. The link is copied to your
clipboard.

**Prerequisite:** rclone configured with a remote named `r2` → the private
`media-private` bucket.

The script has **two modes**, chosen automatically:

| Mode | When | Link it builds |
|---|---|---|
| **Token** (preferred) | env vars `EOSWIM_MEDIA_BASE` + `EOSWIM_R2_TOKEN_SECRET` are set | short, private, long-lived `viewer.html?k=…&t=…` via the media Worker |
| **Presigned** (fallback) | those env vars are not set | `viewer.html?v=<presigned>` (max 7 days) |

Set up the token mode once (see `../worker/README.md`), then:

```powershell
setx EOSWIM_MEDIA_BASE      "https://eoswim-media.you.workers.dev"
setx EOSWIM_R2_TOKEN_SECRET "<the same secret you gave the Worker>"
```

(Open a new PowerShell after `setx` so the vars are picked up.)

**Usage:**

```powershell
.\publish-to-r2.ps1 C:\media\test.mp4                       # upload -> link on clipboard
.\publish-to-r2.ps1 C:\media\jeroen.mp4 -Dest swim/2026 -Edit   # open in annotate mode
.\publish-to-r2.ps1 C:\media\clean.mp4 -NoReencode          # skip normalise (already-clean MP4)
```

By default the video is first **normalised with ffmpeg** (rotation baked in,
square pixels, +faststart, max 1080p) so a raw camera file always fills the
viewer instead of showing up small/rotated. This needs `ffmpeg` on PATH; pass
`-NoReencode` to skip it (safe only for an already-clean, upright MP4 like a
workflow output).

First run may need: `powershell -ExecutionPolicy Bypass -File .\publish-to-r2.ps1 …`
(or `Unblock-File .\publish-to-r2.ps1` if you downloaded it).

## migrate-releases-to-r2.ps1

One-shot migration of the old GitHub-release videos into R2, building a `?k=`
link for each. Nothing is deleted from GitHub — you remove the releases yourself
once the new links check out.

```powershell
.\migrate-releases-to-r2.ps1 -DryRun               # preview (composite videos only)
.\migrate-releases-to-r2.ps1 -IncludeRaw -DryRun   # preview incl. raw source videos
.\migrate-releases-to-r2.ps1 -IncludeRaw           # do it; writes migration-links.md
```

- `composite.mp4` assets (finished overlay videos) → `swim/2026/<tag>.mp4`
- with `-IncludeRaw`, other video assets (raw sources) → `raw/<tag>/<name>`

Needs the same env vars as `publish-to-r2.ps1` to build the links.

## delete-migrated-releases.ps1

Clean up GitHub afterwards — safely. It only deletes a release once **all** of
its videos are confirmed present in R2 (it checks with rclone first). Dry-run by
default.

```powershell
.\delete-migrated-releases.ps1 -IncludeRaw            # dry run: what is safe to delete
.\delete-migrated-releases.ps1 -IncludeRaw -Execute  # really delete the safe ones
```

The `-Execute` delete uses the GitHub CLI, so you need `gh` installed and
`gh auth login` done once. (No `gh`? Delete the listed releases via the website.)
Use the same `-IncludeRaw` you used when migrating.

