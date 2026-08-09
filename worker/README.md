# eoswim-media Worker

Private, signed access to the R2 `media-private` bucket. It streams a video only
when the request carries a valid signed token, so the bucket stays private and
your share links stay short and (as long as you like) non-expiring — no 7-day
presigned limit, no login for the viewer.

```
viewer link → https://eoswim-media.<you>.workers.dev/<key>?e=<expiry>&t=<token>
                     │ Worker verifies HMAC token + expiry
                     ▼ streams from R2 (Range + Content-Type)
              R2 bucket media-private  (stays private)
```

## One-time deploy

You need Node.js and the Cloudflare CLI (`wrangler`).

```bash
npm install -g wrangler      # or: npm i -D wrangler and use npx
cd worker
wrangler login               # opens the browser, authorise your Cloudflare account
```

1. **Pick a signing secret** — any long random string. This exact value must be
   shared with the PC script (env var `EOSWIM_R2_TOKEN_SECRET`). Set it on the Worker:

   ```bash
   wrangler secret put SIGNING_SECRET
   # paste the same random string when prompted
   ```

2. **Deploy:**

   ```bash
   wrangler deploy
   ```

   Wrangler prints the Worker URL, e.g. `https://eoswim-media.<you>.workers.dev`.
   That is your **media base**.

3. **Tell the two apps about the media base:**
   - PC script: set env vars (PowerShell, persist with `setx` for new shells):
     ```powershell
     setx EOSWIM_MEDIA_BASE   "https://eoswim-media.<you>.workers.dev"
     setx EOSWIM_R2_TOKEN_SECRET "<the same random string>"
     ```
   - Viewer: set `MEDIA_BASE` near the top of `docs/viewer.html` to the same URL
     and push (so `?k=` links resolve to your Worker).

## Test it

```bash
# sign a token by hand to sanity-check (bash example):
KEY="swim/2026/test.mp4"; E=$(( $(date +%s) + 3600 ))
SIG=$(printf '%s\n%s' "$KEY" "$E" | openssl dgst -sha256 -hmac "<secret>" -binary | base64 | tr '+/' '-_' | tr -d '=')
echo "https://eoswim-media.<you>.workers.dev/$KEY?e=$E&t=$SIG"
```

Opening that URL should stream the video; tampering with the token or letting
`e` pass gives 403 / 410.

## Custom domain (optional, later)

In the Cloudflare dashboard → Workers → this Worker → *Triggers* → *Custom
Domains*, add e.g. `media.yourbrand.nl`. Then update `MEDIA_BASE` and
`EOSWIM_MEDIA_BASE` to that domain. Nothing else changes.

## Notes

- Tokens are stateless: rotating `SIGNING_SECRET` invalidates every old link at
  once. For per-link revocation later, back it with Workers KV.
- Only GET/HEAD are served; everything else is refused.
