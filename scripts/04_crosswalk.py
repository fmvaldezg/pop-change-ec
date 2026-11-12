"""Phase 2b — dasymetric crosswalk from 2010 census sectors to 2022 census sectors.

The 2010 public microdata is identified only down to sector. Each 2010 sector's
population is split across the 2022 sectors it overlaps, in proportion to
2022 building points (BNCPV22 `edif_p`) that fall in each overlap piece:

  method 'edif_manz2010'  urban (amanzanado) 2010 sector: count only buildings inside
                          2010 blocks, so neighbourhoods built after 2010 get no 2010 people
  method 'edif'           rural 2010 sector, or urban sector with no buildings inside its blocks
  method 'area'           no building points at all -> share of overlapping area
  method 'parroquia'      2010 sector with no geometry -> assigned to a 2022 parroquia only

Pieces with weight < MIN_W are dropped (boundary-digitizing slivers) and weights renormalized.

Outputs:
  build/xwalk/sec2010_sec2022.parquet  sector_2010, sector_2022, parroquia_2022, peso, metodo
  docs/audit/crosswalk_*.csv            QA tables

    conda run -n geo python scripts/04_crosswalk.py
"""
import time

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely

from config import BUILD, DOCS, GPKG_2022

MIN_W = 0.01
GEO, XW, AUDIT = BUILD / "geo", BUILD / "xwalk", DOCS / "audit"
XW.mkdir(exist_ok=True)
T0 = time.time()


def log(msg):
    print(f"[{time.time() - T0:6.0f}s] {msg}", flush=True)


def point_in(points, polys):
    """Index of the polygon containing each point (-1 if none; first match if overlapping)."""
    shapely.prepare(polys)
    tree = shapely.STRtree(polys)
    ip, ig = tree.query(points, predicate="within")
    out = np.full(len(points), -1, dtype=np.int64)
    first = np.unique(ip, return_index=True)[1]
    out[ip[first]] = ig[first]
    return out


s22 = gpd.read_parquet(GEO / "sectores_2022.parquet")
s10 = gpd.read_parquet(GEO / "sectores_2010.parquet")
m10 = gpd.read_parquet(GEO / "manzanas_2010.parquet")

# --- building points -> 2010 sector, 2022 sector, inside-2010-block flag -------------
e = pyogrio.read_dataframe(GPKG_2022, layer="edif_p", columns=["man", "loc"], use_arrow=True).to_crs(s22.crs)
pts = shapely.get_geometry(e.geometry.values, 0)  # MultiPoint -> Point
log(f"edif_p: {len(pts):,} building points")

# 2022 sector: from the point's own census block/locality code (first 12 digits);
# spatial lookup only where that code is missing or not a known sector.
row_of = pd.Series(np.arange(len(s22)), index=s22.sector.values)
i22 = e["man"].fillna(e["loc"]).str[:12].map(row_of).fillna(-1).astype(np.int64).values
need = i22 < 0
i22[need] = point_in(pts[need], s22.geometry.values)
log(f"points -> 2022 sectors ({need.sum():,} by spatial lookup)")

# 2010 sector + inside-2010-block flag: slow spatial joins, cached
cache = XW / "_edif_2010_cache.npz"
if cache.exists() and np.load(cache)["i10"].shape[0] == len(pts):
    z = np.load(cache)
    i10, inblk = z["i10"], z["inblk"]
    log("points -> 2010 sectors/blocks (cached)")
else:
    i10 = point_in(pts, s10.geometry.values)
    log("points -> 2010 sectors")
    inblk = point_in(pts, m10.geometry.values) >= 0
    np.savez(cache, i10=i10, inblk=inblk)
    log(f"points -> 2010 blocks ({inblk.mean():.1%} inside a 2010 block)")

p = pd.DataFrame({"i10": i10, "i22": i22, "blk": inblk})
p = p[(p.i10 >= 0) & (p.i22 >= 0)]
counts = (p.groupby(["i10", "i22"])
          .agg(n_all=("blk", "size"), n_blk=("blk", "sum")).reset_index())
counts["sector_2010"] = s10.sector.values[counts.i10]
counts["sector_2022"] = s22.sector.values[counts.i22]
counts["tipo"] = s10.tipo.values[counts.i10]

# QA: do building counts track population? (2022 sector level)
con = duckdb.connect()
pop22 = con.sql(f"SELECT sector, count(*) AS pop FROM '{BUILD / 'personas_2022.parquet'}' GROUP BY 1").df()
b22 = counts.groupby("sector_2022").n_all.sum().rename("edificios").reset_index()
chk = pop22.merge(b22, left_on="sector", right_on="sector_2022")
log(f"QA 2022 sectors: Spearman(buildings, population) = "
    f"{chk.edificios.corr(chk['pop'], method='spearman'):.3f}")

# --- choose weights per 2010 sector --------------------------------------------------
tot = counts.groupby("sector_2010")[["n_all", "n_blk"]].transform("sum")
use_blk = (counts.tipo == "amanzanado") & (tot.n_blk > 0)
counts["w"] = np.where(use_blk, counts.n_blk, counts.n_all).astype(float)
counts["metodo"] = np.where(use_blk, "edif_manz2010", "edif")
pts_x = counts[["sector_2010", "sector_2022", "w", "metodo"]]

# area fallback for 2010 sectors without any building point
no_pts = s10[~s10.sector.isin(pts_x.sector_2010)]
ov = gpd.overlay(no_pts[["sector", "geometry"]].rename(columns={"sector": "sector_2010"}),
                 s22[["sector", "geometry"]].rename(columns={"sector": "sector_2022"}),
                 how="intersection", keep_geom_type=True)
area_x = ov.assign(w=ov.area, metodo="area")[["sector_2010", "sector_2022", "w", "metodo"]]
log(f"area fallback: {len(no_pts):,} 2010 sectors without buildings, {len(area_x):,} pieces")

xw = pd.concat([pts_x, area_x], ignore_index=True)
xw["peso"] = xw.w / xw.groupby("sector_2010").w.transform("sum")
xw = xw[xw.peso >= MIN_W].copy()
xw["peso"] = xw.peso / xw.groupby("sector_2010").peso.transform("sum")
xw["parroquia_2022"] = xw.sector_2022.str[:6]

# --- 2010 census sectors that have no geometry -> parroquia only --------------------
pop10 = con.sql(f"SELECT sector, count(*) AS pop FROM '{BUILD / 'personas_2010.parquet'}' GROUP BY 1").df()
orphan = pop10[~pop10.sector.isin(xw.sector_2010)].copy()
parr22 = set(s22.parroquia)
orphan["parroquia_2022"] = orphan.sector.str[:6].where(orphan.sector.str[:6].isin(parr22))
log(f"2010 sectors without geometry: {len(orphan)} ({orphan['pop'].sum():,} people); "
    f"unresolved parroquia: {orphan.parroquia_2022.isna().sum()}")
orphan_x = pd.DataFrame({"sector_2010": orphan.sector, "sector_2022": None,
                         "parroquia_2022": orphan.parroquia_2022, "peso": 1.0, "metodo": "parroquia"})

xw = pd.concat([xw[["sector_2010", "sector_2022", "parroquia_2022", "peso", "metodo"]], orphan_x],
               ignore_index=True)
xw.to_parquet(XW / "sec2010_sec2022.parquet", index=False)
log(f"crosswalk: {len(xw):,} rows for {xw.sector_2010.nunique():,} 2010 sectors")

# --- QA tables ----------------------------------------------------------------------
con.register("xw", xw)
con.register("pop10", pop10)
con.register("pop22", pop22)
alloc = con.sql("""
    SELECT x.*, p.pop * x.peso AS pop_alloc
    FROM xw x JOIN pop10 p ON p.sector = x.sector_2010""")
con.sql("CREATE TABLE alloc AS SELECT * FROM alloc")

summary = con.sql("""
    WITH s AS (SELECT sector_2010, any_value(metodo) metodo, count(*) n_dest, sum(pop_alloc) pop
               FROM alloc GROUP BY 1)
    SELECT metodo, count(*) sectores_2010, round(sum(pop)) pob_2010,
           round(100 * sum(pop) / sum(sum(pop)) OVER (), 2) pct_pob,
           round(100 * avg((n_dest = 1)::INT), 1) pct_un_destino
    FROM s GROUP BY 1 ORDER BY pob_2010 DESC""")
summary.write_csv(str(AUDIT / "crosswalk_metodos.csv"))
print(summary.df().to_string(index=False))

total = con.sql("SELECT round(sum(pop_alloc)) FROM alloc").fetchone()[0]
log(f"QA: allocated 2010 population = {total:,.0f}")

# Province and parroquia: direct 2010 totals (2010 codes) vs interpolated (2022 codes)
for lvl, n in [("provincia", 2), ("parroquia", 6)]:
    q = con.sql(f"""
        WITH d AS (SELECT substr(sector, 1, {n}) cod, sum(pop) directo FROM pop10 GROUP BY 1),
             i AS (SELECT substr(parroquia_2022, 1, {n}) cod, sum(pop_alloc) interpolado FROM alloc GROUP BY 1),
             c AS (SELECT substr(sector, 1, {n}) cod, sum(pop) pob_2022 FROM pop22 GROUP BY 1)
        SELECT cod, directo, round(interpolado) interpolado,
               round(100 * (interpolado / directo - 1), 2) dif_pct, pob_2022
        FROM d FULL JOIN i USING (cod) FULL JOIN c USING (cod)
        ORDER BY abs(coalesce(interpolado, 0) - coalesce(directo, 0)) DESC""")
    q.write_csv(str(AUDIT / f"crosswalk_{lvl}.csv"))
    df = q.df()
    if lvl == "provincia":
        print(df.to_string(index=False))
    else:
        both = df.dropna(subset=["directo", "interpolado"])
        print(f"parroquias with code in both years: {len(both)}; |dif| < 1%: "
              f"{(both.dif_pct.abs() < 1).mean():.1%}; |dif| < 5%: {(both.dif_pct.abs() < 5).mean():.1%}")
        print(df.head(15).to_string(index=False))
log("done")
