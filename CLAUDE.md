# CLAUDE.md — Cambio poblacional Ecuador 2010–2022

> Project context for Claude Code. Read this before touching any file.
> Update whenever data, services, or design decisions change.


---

## 1. Project Identity

**Name:** Population change in Ecuador
**Repo:** `https://github.com/fmvaldezg/pop-change-ec`  
**Live map:** `https://felipevaldez.com/pop-change-ec.html`  
**Purpose:** Interactive map of population change between the 2010 and 2022 censuses (CPV, INEC) in ethnic self-identification, age, marital status, educational attainment and social security, at provincia, cantón, parroquia and sector level.  
**Audience:** GIS technicians, university students, urban planners, public institutions in Ecuador. Mostly desktop use; some mobile.  
**Language:** Spanish (es) for all UI labels, tooltips, and popup text.  
**Tone:** Clean, institutional, technical-but-accessible. This is a utility tool — clarity and speed matter more than decoration.


---

## 2. Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Map library | `maplibre-gl` **v4** (latest v4.x) | Loaded via `cdn.jsdelivr.net` — never use Mapbox GL JS |
| Vector tiles | **PMTiles** (`pmtiles` JS protocol, pinned version via `cdn.jsdelivr.net`) | One `.pmtiles` per level or one multi-layer archive in `assets/tiles/`; read by HTTP range requests |
| Indicator data | Static **JSON** in `assets/data/`, joined to tiles by unit id (`feature-state`) | Geometry and numbers are kept separate so tiles stay small |
| Basemap | **OpenFreeMap Positron** | `https://tiles.openfreemap.org/styles/positron` — free, no token |
| Build tool | **None** for the web app | `pop-change-ec.html` + `assets/`; no bundler |
| Hosting | **GitHub Pages** — static only | `index.html` redirects to `pop-change-ec.html` via meta-refresh |
| Data pipeline | Python (`geo` conda env: DuckDB 1.4 + spatial, GeoPandas) + GDAL CLI + `tippecanoe` 2.79 | Runs offline from `scripts/`; writes to `build/` (ignored) and `assets/` (published) |
| Analytics | Google Analytics (GA4) `G-RC52W8J799` | Keep the gtag snippet — do not remove |

> ⚠️ **GitHub Pages constraints:** No server, no `.env`, no Node at runtime. Everything must be static files. GitHub rejects files > 100 MB, so keep each `.pmtiles` and JSON file under that (aim for < 50 MB). The single-file / embedded-GeoJSON rule was dropped (2026-11-10) because the 52,968 sectors don't fit in it.


---

## 2b. Data & pipeline

**Raw data (`data/`, ~18 GB, git-ignored):**
- 2010 census, person table: `data/CPV2010S_CSV_Nacional/CPV2010S_CSV_Poblacion_1.csv`
- 2022 census, person table: `data/1.2 BDD_CPV_2022_SECTOR_CSV/CPV_2022_Poblacion_Sector.csv`
- 2022 cartography: `data/MARCO_GEOESTADISTICO_2023/BNCPV22.gpkg` (the census-2022 cartographic base), EPSG:32717.
  - Layer `sec_a`, field **`sec`**, is the census sector id. Field `sector` is a different, older code: don't use it.
  - Parroquia, cantón and provincia polygons are built by dissolving these sectors.
  - Every `edif_p` building point has a census block (`man`) or locality (`loc`) code whose first 12 digits are the sector.
- 2022 names: `data/CLASIFICADOR GEOGRAFICO_2022/CODIFICACIÓN_2022.xlsx`, sheet `CODIGOS` (1,042 parroquias, 221 cantones, 24 provincias; matches the census exactly).
- 2010 sectors: `data/Geodatabase 2014 Ajustada Versión3/GEODATABASE2014.gdb`, EPSG:32717.
  - Sector layers: `GEO_SEC2014` (urban) + `GEO_SECDIS2014` (rural dispersed).
  - Blocks: `GEO_MAN2014`.
- **Not used:** `data/MGN26_sirgas 2.gpkg`, the 2026 cartography. It includes parroquias and a cantón created after the census, with recoded sectors, so it doesn't match the 2022 microdata. Also not used: `data/SHP/` (2010 DPA, superseded).
- `data/DICCIONARIO_BDD_MANLOC.xlsx` is the 2022 manzana-level dictionary. It does **not** document `P11R`, `P1108` or `P12`.

**Decisions (approved 2026-11-10):**
- Everything is shown on **2022 boundaries**.
- 2010 sector counts are interpolated onto 2022 sectors, weighted by buildings/blocks (dasymetric). Sector codes match across years but the polygons do not.
- Harmonization rules live in `scripts/harmonize.py` (single source of truth) and are explained in `docs/harmonization.md`.

**Run with:** `conda run -n geo python scripts/<NN>_<step>.py`, in numeric order.

| Script | Output |
|---|---|
| `01_personas.py` | `build/personas_{2010,2022}.parquet`: one harmonized row per person |
| `02_audit.py` | `docs/audit/*.csv`; fails if national totals ≠ INEC or a universe is wrong |
| `03_geografia.py` | `build/geo/*.parquet`: 2022 sectors and dissolved parroquias/cantones/provincias with official names; 2010 sectors and blocks |
| `04_crosswalk.py` | `build/xwalk/sec2010_sec2022.parquet` (2010 sector → 2022 sector weights) + `docs/audit/crosswalk_*.csv`. The first run takes about 8 minutes; the 2010 spatial join is cached in `build/xwalk/_edif_2010_cache.npz` |
| `05_indicadores.py` | `build/indicadores/{nivel}_{categorias,resumen,piramide}.parquet` for sector/parroquia/canton/provincia/pais. Units with a base under 50 people are flagged `pequena`. See `docs/indicadores.md` |
| `06_assets.py` | `assets/` (published): PMTiles, JSON, CSV downloads. Takes about 2.5 minutes; use `--skip-tiles` to rebuild only the data |

## 2d. Web data contract (`assets/`)

**Tiles.** `assets/tiles/{nivel}.pmtiles`, where `nivel` = `provincia` | `canton` | `parroquia` | `sector`.
- One source layer per file, named like the file.
- Each feature has a single property, `id`: the DPA 2022 code (2, 4, 6 or 12 digits). Use `promoteId: "id"` and color with `feature-state`.
- Zoom ranges: provincia z0–9, cantón z0–10, parroquia z3–12, sector z8–13. MapLibre overzooms past each maxzoom.
- The sector maxzoom is 13 because z14 made the file 74 MB.
- Geometry is coverage-simplified (3 / 10 / 25 / 60 m), so neighbouring units have no gaps or overlaps.

**Data.** All JSON is **columnar and index-aligned** to `assets/data/{nivel}/unidades.json → ids` (`nivel` also includes `pais`).

| File | Contents |
|---|---|
| `unidades.json` | `ids`; plus `nombres` and `bbox` [w,s,e,n] for named levels. Sector has `sin_geometria`: ids with data but no polygon |
| `{variable}.json` | `categorias` (keys, order as in `meta.json`) and `n["2010"\|"2022"][cat_idx][unit_idx]` (2010 counts have 1 decimal; 2022 counts are integers). Variables: `etnia`, `grupo_edad`, `estado_civil`, `seguridad_social`, `educacion` |
| `resumen.json` | `indicadores`, `v[anio][ind_idx][unit_idx]`, `pequena[ind][unit_idx]` (0/1) |
| `piramide.json` | not for sector: `n[anio][sexo "1"\|"2"][grupo_idx][unit_idx]`, 18 five-year groups |
| `meta.json` | Spanish labels for variables, categories, indicators and levels; `min_base` (50); sources |

**Values the client derives:**
- `base` = sum of the non-`ignorado` categories.
- `pct = 100·n/base`.
- `cambio_pp = pct22 − pct10`.
- `cambio_pct = 100·(n22/n10 − 1)`.
- `pequena` = `min(base10, base22) < 50`.

**Size budget.** Each published file stays under 50 MB. The total is about 120 MB; the largest files are `sector.pmtiles` (45 MB) and `descargas/sector_categorias.csv.zip` (37 MB).

## 2e. Web app (`pop-change-ec.html`)

**Libraries.** `maplibre-gl@4.7.1` and `pmtiles@3.2.1` from jsdelivr, pinned. All other code is inline; there is no build step.

**State and URL.** The app state is `{nivel, tema, cat, med, sel}`. It is mirrored to the URL hash (`#n=&t=&c=&m=&z=&ll=&s=`), so any view can be shared by link.
- Defaults: parroquia · etnia · indígena · cambio pp.
- The level changes only through the selector. Sectors are drawn from z9; at lower zoom a hint asks the user to zoom in.

**Color.** Choropleths color by `feature-state` `c` (class index; −1 = sin datos, −2 = base < 50, shown hatched).
- Diverging metrics (cambio pp, var. %): 7 classes symmetric around 0, edges ±s/±2s/±4s, with s = nice(q90(|v|)/4).
  - Colors: red `#8c2828 #da5450 #f3ada7` · gray `#f0efec` · blue `#9ec5f4 #3987e5 #184f95`.
  - The red arm was derived to match the blue arm's OKLCH lightness.
- Sequential metrics (% 2010, % 2022, indicator levels): up to 6 quantile classes on the blue ramp, computed from both years pooled so 2010 and 2022 share one scale.

**Charts in the detail panel.** 2022 is drawn as filled blue bars (`#2a78d6`) and 2010 as a gray outline (`#52514e`), so the years differ by shape as well as color. The detail tables double as the accessible table view.

**Local testing.** PMTiles needs HTTP Range requests, so `python -m http.server` won't work. Use `npx http-server` or another server that supports ranges.
- Headless Chrome with `--virtual-time-budget` never finishes parsing tiles (the web workers don't run). Drive the browser through CDP in real time instead.

## 2c. Project structure

```
pop-change-ec.html      web app (Phase 5)
index.html              redirect → pop-change-ec.html
assets/tiles/           PMTiles (published)
assets/data/            indicator JSON + meta.json (published)
assets/descargas/       CSV downloads + LEEME.txt (published)
scripts/                offline pipeline (config.py, harmonize.py, NN_*.py)
docs/                   harmonization spec + audit tables
build/                  intermediate files (ignored)
data/                   raw INEC data (ignored)
```


## 3. Design System

The current design uses a **light, clean, institutional** aesthetic. Maintain this direction.

### CSS Variables (defined in `:root`)
```css
--bg:        rgb(254,254,254)  /* page background */
--surface:   #ffffff           /* cards, popups, header */
--sf2:       #f6f6f6           /* code blocks, hover backgrounds */
--border:    #e3e3e3           /* all dividers and borders */
--text:      #111111           /* primary text */
--muted:     #888888           /* secondary labels, metadata */
--accent:    #FF5A5F           /* brand red — use sparingly */
--shadow:    rgba(0,0,0,0.07) /* subtle elevation */
--teal:      #0d9488           /* CTA buttons (Copy URL) */
--r:         10px              /* standard border-radius */
--r-sm:      6px               /* small border-radius */
--header-h:  56px              /* fixed header height */
```

### Typography
- **Body font:** `-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif` (system stack, no Google Fonts needed)
- **Monospace:** `"SF Mono", "Fira Code", monospace` — used only in URL display boxes
- Header logo name: `14px, font-weight: 700`
- Legend labels: `12px`
- Popup section labels: `10px, uppercase, letter-spacing: 0.5px, color: var(--muted)`
- Popup title: `13px, font-weight: 600`
- Stats values in header: `15px, font-weight: 700`

