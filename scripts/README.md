# scripts

Helper scripts you run **on your own PC** (not in CI).

## publish-to-r2.ps1

Upload a locally rendered video to Cloudflare R2 and get a ready-to-share
viewer link in one command — no hand-encoding of URLs.

**Prerequisites** (already set up): rclone configured with a remote named `r2`,
pointing at the private `media-private` bucket.

**Usage** (PowerShell):

```powershell
# simplest: upload to swim/2026 and copy a viewer link to the clipboard
.\publish-to-r2.ps1 C:\media\test.mp4

# open straight into annotate mode, different folder
.\publish-to-r2.ps1 C:\media\jeroen.mp4 -Dest swim/2026 -Edit

# attach an existing annotation id
.\publish-to-r2.ps1 C:\media\test.mp4 -Annot ar4knmu
```

What it does: `rclone copy` → `rclone link --expire 168h` (presigned, max 7 days)
→ URL-encodes → builds `viewer.html?v=…` → copies the link to your clipboard.

**Limitation:** presigned links are valid at most 7 days. For permanent
shareable links, use the (future) Cloudflare Worker path.
