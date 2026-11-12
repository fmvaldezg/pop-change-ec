"""Phase 2a — clean 2022 and 2010 sector geometry and build 2022 admin boundaries.

2022 geometry is the census cartographic base BNCPV22, whose sector code (`sec`) is the
census sector id, so parroquia/cantón/provincia polygons dissolved from it are exactly the
census-2022 DPA. Names come from INEC's Clasificador Geográfico Estadístico 2022.

Outputs (GeoParquet, EPSG:32717 = WGS 84 / UTM 17S):
  build/geo/sectores_2022.parquet    sector, parroquia, canton, provincia
  build/geo/parroquias_2022.parquet   parroquia, canton, provincia, nombre
  build/geo/cantones_2022.parquet     canton, provincia, nombre
  build/geo/provincias_2022.parquet   provincia, nombre
  build/geo/sectores_2010.parquet    sector, tipo ('amanzanado' | 'disperso')
  build/geo/manzanas_2010.parquet    2010 (2014-adjusted) blocks — dasymetric mask
  build/dpa_2022.csv                 official codes + names (provincia, cantón, parroquia)

    conda run -n geo python scripts/03_geografia.py
"""
import time

import duckdb
import geopandas as gpd
import pandas as pd
import pyogrio
import shapely

from config import BUILD, CRS, DPA_2022, GDB_2010, GPKG_2022

GEO = BUILD / "geo"
GEO.mkdir(exist_ok=True)
T0 = time.time()


def log(msg):
    print(f"[{time.time() - T0:6.0f}s] {msg}", flush=True)


def clean(gdf):
    """Valid polygonal geometry only (make_valid can emit lines/points on bad rings)."""
    parts, idx = shapely.get_parts(shapely.make_valid(gdf.geometry.values), return_index=True)
    keep = shapely.get_type_id(parts) >= 3  # 3 polygon, 6 multipolygon
    return gpd.GeoDataFrame(
        gdf.drop(columns=gdf.geometry.name).iloc[idx[keep]].reset_index(drop=True),
        geometry=parts[keep], crs=gdf.crs)


def dissolve(gdf, by):
    out = gdf.dissolve(by=by, as_index=False)
    out["geometry"] = shapely.make_valid(out.geometry.values)
    return out


# --- official 2022 codes and names --------------------------------------------------
con = duckdb.connect()
con.sql("INSTALL excel; LOAD excel")
dpa = con.sql(f"""
    SELECT DPA_PROVIN provincia, trim(DPA_DESPRO) nom_provincia,
           DPA_CANTON canton, trim(DPA_DESCAN) nom_canton,
           DPA_PARROQ parroquia, trim(DPA_DESPAR) nom_parroquia
    FROM read_xlsx('{DPA_2022}', sheet='CODIGOS', header=true, all_varchar=true, range='B2:G5000')
    WHERE DPA_PARROQ IS NOT NULL""").df()
dpa.to_csv(BUILD / "dpa_2022.csv", index=False)
log(f"DPA 2022: {dpa.parroquia.nunique()} parroquias, {dpa.canton.nunique()} cantones, "
    f"{dpa.provincia.nunique()} provincias")

# --- 2022 sectors ---------------------------------------------------------------------
s22 = pyogrio.read_dataframe(GPKG_2022, layer="sec_a", columns=["sec"], use_arrow=True)
log(f"2022 sec_a: {len(s22):,} features ({s22.crs.to_string()})")
s22 = clean(s22.rename(columns={"sec": "sector"})).to_crs(CRS)
s22 = dissolve(s22, "sector")
s22["parroquia"] = s22.sector.str[:6]
s22["canton"] = s22.sector.str[:4]
s22["provincia"] = s22.sector.str[:2]
s22 = s22[["sector", "parroquia", "canton", "provincia", "geometry"]]
s22.to_parquet(GEO / "sectores_2022.parquet")
unknown = sorted(set(s22.parroquia) - set(dpa.parroquia))
log(f"sectores_2022: {len(s22):,} sectors; parroquia codes not in DPA 2022: {unknown}")

# --- 2022 admin units (dissolved from sectors) + official names ------------------------
for lvl, key, extra in [("parroquias", "parroquia", ["canton", "provincia"]),
                        ("cantones", "canton", ["provincia"]),
                        ("provincias", "provincia", [])]:
    g = dissolve(s22[[key] + extra + ["geometry"]], key)
    names = dpa.drop_duplicates(key).set_index(key)[f"nom_{key}"]
    g["nombre"] = g[key].map(names)
    g.to_parquet(GEO / f"{lvl}_2022.parquet")
    log(f"{lvl}_2022: {len(g):,} units; without name: {g[g.nombre.isna()][key].tolist()}")

# --- 2010 sectors (urban + rural dispersed layers) --------------------------------------
u = pyogrio.read_dataframe(GDB_2010, layer="GEO_SEC2014", columns=["DPA_SECTOR"], use_arrow=True)
r = pyogrio.read_dataframe(GDB_2010, layer="GEO_SECDIS2014", columns=["DPA_SECDIS"], use_arrow=True)
u = u.rename(columns={"DPA_SECTOR": "sector"}).assign(tipo="amanzanado")
r = r.rename(columns={"DPA_SECDIS": "sector"}).assign(tipo="disperso")
s10 = gpd.GeoDataFrame(pd.concat([u, r], ignore_index=True), geometry="geometry", crs=u.crs)
s10 = dissolve(clean(s10).to_crs(CRS), ["sector", "tipo"])
s10.to_parquet(GEO / "sectores_2010.parquet")
log(f"sectores_2010: {len(s10):,} sectors ({(s10.tipo == 'amanzanado').sum():,} amanzanados), "
    f"{s10.sector.duplicated(keep=False).sum()} codes present in both layers")

# --- 2010 blocks (mask for where people lived in 2010) ----------------------------------
m10 = pyogrio.read_dataframe(GDB_2010, layer="GEO_MAN2014", columns=["DPA_MANZAN"], use_arrow=True)
m10 = clean(m10.rename(columns={"DPA_MANZAN": "manzana"})).to_crs(CRS)
m10.to_parquet(GEO / "manzanas_2010.parquet")
log(f"manzanas_2010: {len(m10):,} block parts")
log("done")
