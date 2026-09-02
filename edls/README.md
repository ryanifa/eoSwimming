# EDL-archief (render-opdrachten)

Bewaarde **render-opdrachten (EDL's)** per video, zodat een bewerking altijd
opnieuw gerenderd kan worden zonder hem in `edit.html` over te doen. Elk
`.json`-bestand bevat exact wat je in het `edl`-veld van de workflow
**Edit video (trim & rotate/zoom) → R2** plakt.

> **Vanaf nu automatisch:** elke Edit-run schrijft de gebruikte EDL zelf weg
> naast de video in R2 als `<folder>/<tag>.edl.json` (én als artifact bij de
> run). Deze map is voor het handmatige archief / oudere edits; nieuwe hoef je
> hier niet meer bij te zetten. Een EDL uit R2 halen:
> `rclone cat r2:media-private/swim/demo/sjoerd2.edl.json`.

## Zo render je er één opnieuw

1. Open de JSON, kopieer de **hele inhoud** (de `{"regions":[…]}`-regel).
2. Start de workflow **Edit video (trim & rotate/zoom) → R2** met de gegevens
   uit de tabel hieronder (kolommen `r2_key`, `tag`, `folder`) en de
   gekopieerde EDL in het `edl`-veld.
3. Gebruik altijd een **verse "Run workflow"** (niet "Re-run"), zodat de
   nieuwste `edit_video.py` (incl. de rotatie-fix) wordt gebruikt.

> `r2_key` invullen **zonder** aanhalingstekens en **zonder** een `/` ervoor —
> de workflow strippt die inmiddels wel weg, maar netjes invullen voorkomt
> verwarring. Spaties in de map-/bestandsnaam zijn prima.

## Overzicht

| EDL | tag | folder | r2_key (bron in R2) | herkomst |
|---|---|---|---|---|
| `sjoerd2.json` | `sjoerd2` | `swim/demo` | `raw/Upload/sjoerd 01 sept/sjoerd2.mp4` | herleid uit geslaagde run #14 (attempt 1) |
| `sjoerd3.json` | `sjoerd3` | `swim/demo` | `raw/Upload/sjoerd 01 sept/sjoerd3.mp4` | uit editor (7 regio's) |

## Let op

- **sjoerd2** is herleid uit het job-log van de geslaagde render (de exacte
  in/uit-tijden en de 90°-tegen-de-klok rotatie), tot op ~0,04 s nauwkeurig —
  reproduceert een identiek resultaat. sjoerd2 en sjoerd3 zijn echt
  verschillende bewerkingen.
- Controleer de `r2_key` per video: dat is de bronvideo in R2, niet de
  gerenderde output. Klopt het pad niet, pas het dan hier aan.
