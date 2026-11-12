"""Phase 4 — publishable web assets: vector tiles, indicator JSON, CSV downloads, metadata.

assets/tiles/{nivel}.pmtiles   geometry only, one layer named {nivel}, property `id` (unit code);
                               the app colors features via feature-state (promoteId: "id")
assets/data/meta.json          variables, categories, indicators, levels, labels (from harmonize.py)
assets/data/{nivel}/unidades.json   ids (+ names, parents, bbox for named levels); every other
                               file of the level is index-aligned to `ids`
assets/data/{nivel}/{variable}.json counts per category: n[anio][cat_index][unit_index]
assets/data/{nivel}/resumen.json    summary indicators: v[anio][ind_index][unit_index], pequena flags
assets/data/{nivel}/piramide.json   (not for sector) n[anio][sexo][grupo_index][unit_index]
assets/descargas/*.csv(.zip)   long-format tables with names for download

    conda run -n geo python scripts/06_assets.py [--skip-tiles]
"""
import json
import math
import subprocess
import sys
import time
import zipfile
from datetime import date

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from config import ASSETS, BUILD
from harmonize import UNKNOWN, VARIABLES, YEARS

IND = BUILD / "indicadores"
GEO = BUILD / "geo"
TILES, DATA, DOWN = ASSETS / "tiles", ASSETS / "data", ASSETS / "descargas"
for d in (TILES, DATA, DOWN):
    d.mkdir(parents=True, exist_ok=True)
MAX_FILE_MB = 50
MIN_BASE = 50

# level -> (geometry file, code column, coverage-simplify tolerance m, tippecanoe min/max zoom)
LEVELS = {
    "provincia": ("provincias_2022", "provincia", 60, 0, 9),
    "canton": ("cantones_2022", "canton", 25, 0, 10),
    "parroquia": ("parroquias_2022", "parroquia", 10, 3, 12),
    "sector": ("sectores_2022", "sector", 3, 8, 13),  # z14 = 74 MB, z13 = 45 MB; app overzooms
}
INDICADORES = {  # key: (label, unit, decimals)
    "poblacion": ("Población total", "personas", 0),
    "edad_mediana": ("Edad mediana", "años", 1),
    "razon_dependencia": ("Razón de dependencia", "por cada 100 personas de 15 a 64 años", 1),
    "indice_envejecimiento": ("Índice de envejecimiento", "personas de 65+ por cada 100 de 0 a 14", 1),
    "pct_aporta": ("Aporta a la seguridad social (12 años y más)", "%", 1),
    "pct_superior": ("Educación superior o posgrado (25 años y más)", "%", 1),
    "escolaridad_media": ("Años promedio de escolaridad (25 años y más)", "años", 1),
}
NIVEL_LABEL = {"provincia": "Provincia", "canton": "Cantón", "parroquia": "Parroquia", "sector": "Sector censal",
               "pais": "Ecuador"}
T0 = time.time()


def log(msg):
    print(f"[{time.time() - T0:5.0f}s] {msg}", flush=True)


def clean_num(a, nd):
    """Round to nd decimals; NaN -> None; ints when nd == 0 (compact JSON)."""
    out = []
    for x in a:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            out.append(None)
        elif nd == 0:
            out.append(int(round(x)))
        else:
            out.append(round(float(x), nd))
    return out


def dump(obj, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


# --- names --------------------------------------------------------------------------
dpa = pd.read_csv(BUILD / "dpa_2022.csv", dtype=str)
NAMES = {
    "provincia": dpa.drop_duplicates("provincia").set_index("provincia").nom_provincia,
    "canton": dpa.drop_duplicates("canton").set_index("canton").nom_canton,
    "parroquia": dpa.drop_duplicates("parroquia").set_index("parroquia").nom_parroquia,
}


def title(s):
    """'SANTO DOMINGO DE LOS TSÁCHILAS' -> 'Santo Domingo de los Tsáchilas'."""
    small = {"de", "del", "la", "las", "los", "y", "el", "en"}
    words = str(s).lower().split()
    return " ".join(w if (i and w in small) else w[:1].upper() + w[1:] for i, w in enumerate(words))


# --- 1. vector tiles --------------------------------------------------------------
if "--skip-tiles" not in sys.argv:
    src = BUILD / "tiles_src"
    src.mkdir(exist_ok=True)
    for nivel, (fname, col, tol, zmin, zmax) in LEVELS.items():
        g = gpd.read_parquet(GEO / f"{fname}.parquet")[[col, "geometry"]].rename(columns={col: "id"})
        raw, simp, fgb = src / f"{nivel}_utm.fgb", src / f"{nivel}_simp.fgb", src / f"{nivel}.fgb"
        for f in (raw, simp, fgb):  # FlatGeobuf can't be overwritten in place
            f.unlink(missing_ok=True)
        g.to_file(raw, driver="FlatGeobuf")
        # GEOS CoverageSimplifier via GDAL CLI (the geo env's GEOS 3.10 lacks it): simplifies
        # shared borders once, so neighbours stay gap- and overlap-free.
        subprocess.run(["gdal", "vector", "simplify-coverage", "--quiet", "--overwrite",
                        str(raw), str(simp), str(tol)], check=True)
        subprocess.run(["ogr2ogr", "-overwrite", "-t_srs", "EPSG:4326", "-makevalid",
                        "-nlt", "PROMOTE_TO_MULTI", str(fgb), str(simp)],
                       check=True)
        nv = shapely.get_num_coordinates(gpd.read_file(simp).geometry.values).sum()
        log(f"{nivel}: coverage-simplified at {tol} m -> {nv:,} vertices "
            f"(from {shapely.get_num_coordinates(g.geometry.values).sum():,})")
        out = TILES / f"{nivel}.pmtiles"
        cmd = ["tippecanoe", "-o", str(out), "--force", "-l", nivel, "-Z", str(zmin), "-z", str(zmax),
               "--detect-shared-borders", "--no-tiny-polygon-reduction", "--no-feature-limit",
               "--no-tile-size-limit", "--simplification=2", "-y", "id", "--quiet", str(fgb)]
        subprocess.run(cmd, check=True)
        log(f"{nivel}: {out.name} {out.stat().st_size / 1e6:.1f} MB")

# --- 2. metadata ------------------------------------------------------------------
meta = {
    "titulo": "Cambio poblacional en Ecuador, 2010–2022",
    "anios": list(YEARS),
    "min_base": MIN_BASE,
    "generado": date.today().isoformat(),
    "fuentes": [
        "INEC, Censo de Población y Vivienda 2010 (base anonimizada a nivel de sector)",
        "INEC, Censo de Población y Vivienda 2022 (base anonimizada a nivel de sector)",
        "INEC, Base cartográfica CPV 2022 (Marco Geoestadístico 2023)",
        "INEC, Geodatabase 2014 ajustada (sectores censales 2010)",
        "INEC, Clasificador Geográfico Estadístico 2022",
    ],
    "niveles": [{"id": n, "label": NIVEL_LABEL[n], "minzoom": LEVELS[n][3], "maxzoom": LEVELS[n][4]}
                for n in LEVELS],
    "variables": [
        {"id": var, "label": v["label"], "universo": v["universe"],
         "categorias": [{"id": k, "label": lab} for k, lab in v["categories"].items()]
         + ([{"id": UNKNOWN, "label": "Se ignora", "ignorado": True}]
            if var in ("seguridad_social", "educacion") else [])}
        for var, v in VARIABLES.items()],
    "indicadores": [{"id": k, "label": lab, "unidad": u, "decimales": d} for k, (lab, u, d) in INDICADORES.items()],
    "piramide": {"sexos": [{"id": "1", "label": "Hombres"}, {"id": "2", "label": "Mujeres"}],
                 "grupos": [f"{lo}–{lo + 4}" if lo < 85 else "85 y más" for lo in range(0, 90, 5)]},
}
dump(meta, DATA / "meta.json")

# --- 3. indicator JSON per level -------------------------------------------------
sizes = {}
for nivel in list(LEVELS) + ["pais"]:
    cat = pd.read_parquet(IND / f"{nivel}_categorias.parquet")
    res = pd.read_parquet(IND / f"{nivel}_resumen.parquet")
    ids = sorted(cat.unidad.unique())
    pos = pd.Series(np.arange(len(ids)), index=ids)

    unidades = {"nivel": nivel, "ids": ids}
    if nivel in NAMES:
        g = gpd.read_parquet(GEO / f"{LEVELS[nivel][0]}.parquet").set_index(LEVELS[nivel][1]).to_crs("EPSG:4326")
        b = g.bounds.reindex(ids)
        unidades["nombres"] = [title(NAMES[nivel].get(i, i)) for i in ids]
        unidades["bbox"] = [[round(r.minx, 4), round(r.miny, 4), round(r.maxx, 4), round(r.maxy, 4)]
                            for r in b.itertuples()]
    if nivel == "sector":
        geo_ids = set(pd.read_parquet(GEO / "sectores_2022.parquet", columns=["sector"]).sector)
        unidades["sin_geometria"] = [i for i in ids if i not in geo_ids]
    if nivel == "pais":
        unidades["nombres"] = ["Ecuador"]
    dump(unidades, DATA / nivel / "unidades.json")

    for var, v in VARIABLES.items():
        cats = list(v["categories"]) + ([UNKNOWN] if var in ("seguridad_social", "educacion") else [])
        d = cat[cat.variable == var]
        n = {}
        for y in YEARS:
            w = d.pivot(index="unidad", columns="categoria", values=f"n_{y}").reindex(index=ids, columns=cats)
            # 2022 counts are whole persons; 2010 counts are interpolated (1 decimal)
            n[str(y)] = [clean_num(w[c].values, 0 if y == 2022 else 1) for c in cats]
        dump({"variable": var, "categorias": cats, "n": n}, DATA / nivel / f"{var}.json")

    inds = list(INDICADORES)
    out = {"indicadores": inds, "v": {}, "pequena": {}}
    for y in YEARS:
        w = res.pivot(index="unidad", columns="indicador", values=f"v_{y}").reindex(index=ids, columns=inds)
        out["v"][str(y)] = [clean_num(w[k].values, 0 if k == "poblacion" else 2) for k in inds]
    pq = res.pivot(index="unidad", columns="indicador", values="pequena").reindex(index=ids, columns=inds)
    out["pequena"] = {k: [int(x) for x in pq[k].fillna(True).values] for k in inds}
    dump(out, DATA / nivel / "resumen.json")

    if nivel != "sector":
        pyr = pd.read_parquet(IND / f"{nivel}_piramide.parquet")
        grupos = [f"{lo:02d}" for lo in range(0, 90, 5)]
        pn = {}
        for y in YEARS:
            pn[str(y)] = {}
            for sx in ("1", "2"):
                w = pyr[pyr.sexo == sx].pivot(index="unidad", columns="grupo", values=f"n_{y}") \
                    .reindex(index=ids, columns=grupos).fillna(0)
                pn[str(y)][sx] = [clean_num(w[gc].values, 0) for gc in grupos]
        dump({"grupos": grupos, "n": pn}, DATA / nivel / "piramide.json")
    sizes[nivel] = sum(f.stat().st_size for f in (DATA / nivel).glob("*.json"))
    log(f"data/{nivel}: {len(ids):,} units, {sizes[nivel] / 1e6:.1f} MB")

# --- 4. CSV downloads --------------------------------------------------------------
def with_names(df, nivel):
    df = df.copy()
    if nivel == "pais":
        df.insert(1, "nombre", "Ecuador")
        return df
    code, at = df.unidad, df.columns.get_loc("unidad") + 1
    for lvl, n in [("provincia", 2), ("canton", 4), ("parroquia", 6)]:
        if n <= len(code.iloc[0]):
            df.insert(at, f"nom_{lvl}", code.str[:n].map(NAMES[lvl]))
            at += 1
    return df


LEEME = f"""Cambio poblacional en Ecuador 2010–2022 — tablas descargables
Generado: {date.today().isoformat()}. Geografía: división político-administrativa del Censo 2022.

Archivos: <nivel>_categorias.csv y <nivel>_resumen.csv (nivel = pais, provincia, canton, parroquia;
sector en .zip). Los valores 2010 por debajo del nivel nacional están interpolados a la geografía 2022
(ponderación por edificaciones), por eso pueden tener decimales.

<nivel>_categorias.csv
  unidad          código DPA 2022 (2, 4, 6 o 12 dígitos)
  variable        etnia | grupo_edad | estado_civil | seguridad_social | educacion
  categoria       código de la categoría; etiqueta: nombre en español
  n_2010, n_2022  personas
  cambio_abs      n_2022 - n_2010
  cambio_pct      variación porcentual de n (vacío si n_2010 = 0)
  base_2010/2022  universo sin "Se ignora": población total (etnia, edad), 12 años y más
                  (estado conyugal, seguridad social) o 25 años y más (nivel de instrucción)
  pct_2010/2022   porcentaje de la categoría sobre la base
  cambio_pp       pct_2022 - pct_2010 (puntos porcentuales)
  pequena         True si la base es menor a {MIN_BASE} personas en algún año: interpretar con cautela

<nivel>_resumen.csv
  indicador       poblacion, edad_mediana, razon_dependencia, indice_envejecimiento,
                  pct_aporta, pct_superior, escolaridad_media
  v_2010, v_2022  valor del indicador; cambio = v_2022 - v_2010 (cambio_pct solo para población)
  base_2010/2022, pequena  como arriba

Fuente: INEC, Censos de Población y Vivienda 2010 y 2022. Elaboración propia.
"""


cat_labels = {(var, k): lab for var, v in VARIABLES.items() for k, lab in v["categories"].items()}
for nivel in ["pais", "provincia", "canton", "parroquia", "sector"]:
    cat = pd.read_parquet(IND / f"{nivel}_categorias.parquet")
    cat.insert(3, "etiqueta", [cat_labels.get((a, b), "Se ignora") for a, b in zip(cat.variable, cat.categoria)])
    res = pd.read_parquet(IND / f"{nivel}_resumen.parquet")
    for name, df in [("categorias", cat), ("resumen", res)]:
        df = with_names(df, nivel).round(3)
        csv = DOWN / f"{nivel}_{name}.csv"
        df.to_csv(csv, index=False, encoding="utf-8")
        if nivel == "sector":
            with zipfile.ZipFile(csv.with_suffix(".csv.zip"), "w", zipfile.ZIP_DEFLATED) as z:
                z.write(csv, csv.name)
            csv.unlink()
(DOWN / "LEEME.txt").write_text(LEEME, encoding="utf-8")
log("downloads written")

# --- 5. size report ---------------------------------------------------------------
report, too_big = [], []
for f in sorted(ASSETS.rglob("*")):
    if f.is_file():
        mb = f.stat().st_size / 1e6
        report.append((str(f.relative_to(ASSETS)), round(mb, 2)))
        if mb > MAX_FILE_MB:
            too_big.append(f.name)
rep = pd.DataFrame(report, columns=["archivo", "MB"])
print(rep.to_string(index=False))
print(f"TOTAL assets: {rep.MB.sum():.1f} MB")
if too_big:
    raise SystemExit(f"Files over {MAX_FILE_MB} MB: {too_big}")
log("done")
