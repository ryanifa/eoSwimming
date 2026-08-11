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
.\publish-to-r2.ps1 C:\media\test.mp4 -Annot ar4knmu -ExpireDays 90
```

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

