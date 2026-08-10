# Hoe eo Swim in elkaar zit

Plain-language uitleg van het hele systeem: wat de onderdelen zijn, waar ze
staan, en hoe een filmpje van jouw PC bij een eindgebruiker terechtkomt.

## Het grote plaatje in één zin

**De app (viewer) staat gratis op GitHub Pages, de video's staan privé in
Cloudflare R2 achter een klein poortwachtertje (Worker), en jouw PC maakt met één
commando een korte deellink.**

```
   jouw PC                         GitHub                        Cloudflare
 ┌──────────┐   git push        ┌─────────────┐             ┌──────────────────┐
 │ render   │ ────────────────► │ Pages       │             │ R2 bucket        │
 │ video    │                   │ = de apps   │             │ media-private    │
 │          │   rclone upload   │ (viewer,    │             │  (video-bytes)   │
 │ publish- │ ────────────────────────────────────────────►│                  │
 │ to-r2.ps1│                   │  edit,      │             └────────┬─────────┘
 └────┬─────┘                   │  frames)    │                      │ leest uit
      │ maakt een korte link    └──────┬──────┘                      │
      │                                │ serveert                    │
      ▼                                ▼                    ┌────────┴─────────┐
 eindgebruiker  ───────────────►  viewer.html  ───────────►│ Worker           │
 opent de link                    (?k=...&t=token)         │ eoswim-media     │
                                                           │ checkt token,    │
                                                           │ streamt de video │
                                                           └──────────────────┘
```

Kernidee: **de repo is de index, R2 is de opslag.** De pagina's + kleine
tekstbestanden (annotaties) staan op GitHub; de zware video-bytes staan in R2.

## De onderdelen

### 1. De apps — `docs/` (op GitHub Pages)
Statische webpagina's, geen server nodig. GitHub Pages zet ze online op
`https://ryanifa.github.io/eoSwimming/...`.

| Bestand | Wat het doet |
|---|---|
| `docs/viewer.html` | Video bekijken + annotaties (pen/pijl/notitie/memo) tonen; in `?edit=1` zelf annoteren |
| `docs/edit.html` | Video knippen, roteren, inzoomen (in de browser) |
| `docs/frames.html` | Video omzetten naar losse foto's (ZIP) |
| `docs/index.html` | Hub met de sensor-overlay/splits |
| `docs/annotations/*.json` | De annotaties (klein, blijven op GitHub) |

De viewer kan een video op drie manieren laden:
- `?k=<key>` — de **nieuwe, goede manier**: privé via de Worker (kort + blijvend).
- `?v=<url>` — elke directe video-URL (bijv. een presigned R2-link).
- `?r=<tag>` — de **oude manier**: een GitHub-release (wordt uitgefaseerd).

Bovenin `viewer.html` staat `MEDIA_BASE` — dat is de URL van jouw Worker, zodat
`?k=`-links weten waar de video's staan.

### 2. De opslag — Cloudflare R2 (bucket `media-private`)
Een privé "emmer" voor bestanden, zoals een map in de cloud. Goedkoop, geen
kosten voor terugkijken (geen egress-kosten). De video's liggen hier onder keys
als `swim/2026/test.mp4`. De bucket is **privé**: zonder de Worker komt niemand
erbij.

### 3. De poortwachter — de Worker — `worker/`
Een piepklein programmaatje dat bij Cloudflare draait, vóór de bucket. Elke
kijk-link bevat een **token** (een digitale handtekening). De Worker rekent na of
dat token klopt en niet verlopen is; pas dan streamt hij de video (met
"scrubben" en de juiste bestandstype-info). Zo blijft de bucket privé zonder dat
de kijker hoeft in te loggen.

- `worker/src/index.js` — de code
- `worker/wrangler.toml` — de instellingen (welke bucket, welke naam)
- `worker/README.md` — hoe je 'm deployt

### 4. Het gemak — de scripts — `scripts/` (draaien op jouw PC)
| Script | Wat het doet |
|---|---|
| `publish-to-r2.ps1` | Eén video uploaden naar R2 + korte privé-link op je klembord |
| `migrate-releases-to-r2.ps1` | Alle oude release-video's in één keer naar R2 tillen |

## De dagelijkse flow

1. Render je video **lokaal** (op je PC — scheelt kosten en is sneller).
2. Draai:
   ```powershell
   .\publish-to-r2.ps1 C:\media\jouwvideo.mp4
   ```
3. Er staat nu een korte, privé viewer-link op je klembord. Die stuur je naar de
   eindgebruiker. Klaar.

## De twee "sleutels" die moeten matchen

Het hele privé-mechanisme rust op **één geheime string die op twee plekken staat
en identiek moet zijn**:

| Waar | Naam | Rol |
|---|---|---|
| Cloudflare Worker | `SIGNING_SECRET` (via `wrangler secret put`) | controleert de handtekening |
| Jouw PC | `EOSWIM_R2_TOKEN_SECRET` (env-var via `setx`) | maakt de handtekening |

Plus `EOSWIM_MEDIA_BASE` op je PC en `MEDIA_BASE` in de viewer: allebei de
Worker-URL (`https://eoswim-media.swimanalyses.workers.dev`).

Verschillen de twee secrets? Dan wijst de Worker elke link af met **403**.

## Wat privé/niet-privé is

- **Privé**: de video-bytes in R2 (alleen via een geldig token te bereiken).
- **Openbaar**: de apps in `docs/` en de annotatie-JSON (dat is code + wat tekst,
  geen gevoelige data). Ook je Worker-URL is niet geheim — het **token** is de
  beveiliging, niet de URL.

## Legacy (oude manier — wordt uitgefaseerd)

Deze bestaan nog maar zijn op weg naar buiten. Je kunt ze houden tot je backlog
gemigreerd is; verwijder ze pas als geen enkele link meer `?r=` gebruikt.

| Onderdeel | Status |
|---|---|
| GitHub-releases met `composite.mp4` | Vervangen door R2. Verwijder ná migratie. |
| `.github/workflows/composite-video.yml` | Maakt de sensor-overlay + release. Kan later naar R2. |
| `.github/workflows/publish-plain-video.yml` | Zet een kale video als release. Grotendeels overbodig. |
| `.github/workflows/edit-video.yml` | Cloud-render van een EDL. Alleen nodig als je niet lokaal rendert. |
| `pages.yml` mirror-stap | **Verwijderd** — video's staan niet meer op Pages. |
| `cleanup-releases.yml` | **Verwijderd** — geen release-video's meer om op te ruimen. |

## Snelle probleemoplossing

| Symptoom | Waarschijnlijke oorzaak |
|---|---|
| Media-URL geeft **403** | De twee secrets verschillen → `setx EOSWIM_R2_TOKEN_SECRET` opnieuw met exact de Worker-string |
| Media-URL geeft **401** | Geen `?e=&t=` in de link (of handmatig weggehaald) |
| Media-URL geeft **410** | Link verlopen → nieuwe maken met het script |
| `?k=`-link laadt niet, `?v=` wel | `MEDIA_BASE` in `viewer.html` staat leeg/fout, of Pages-deploy nog bezig |
| iPhone speelt niet inline af | Content-Type in R2 niet `video/mp4` |
| `edit.html` kan R2-video niet laden | CORS: de Worker stuurt CORS-headers, dus dit hoort te werken — check de foutmelding |
