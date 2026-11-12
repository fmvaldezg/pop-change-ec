"""Phase 3 — indicator tables for every unit at every level, on census-2022 geography.

1. Count persons per 2010 / 2022 sector for every harmonized category, single-year age,
   sex x 5-year age group (pyramid) and years of schooling (25+).
2. Move 2010 counts onto 2022 sectors with the dasymetric crosswalk (fractional counts).
3. Aggregate to sector, parroquia, canton, provincia and pais.
4. Derive shares, changes and summary indicators; flag small bases (< MIN_BASE).

Outputs (build/indicadores/):
  {nivel}_categorias.parquet  unidad, variable, categoria, n_2010, n_2022, cambio_abs, cambio_pct,
                              base_2010, base_2022, pct_2010, pct_2022, cambio_pp, pequena
  {nivel}_resumen.parquet     unidad, indicador, v_2010, v_2022, cambio, cambio_pct, base_2010,
                              base_2022, pequena
  {nivel}_piramide.parquet    unidad, sexo, grupo, n_2010, n_2022
  docs/audit/indicadores_qa.csv

    conda run -n geo python scripts/05_indicadores.py
"""
import time

import duckdb
import numpy as np
import pandas as pd

from config import BUILD, DOCS
from harmonize import UNKNOWN, VARIABLES, YEARS

MIN_BASE = 50  # a unit/variable is "pequena" when its 2010 or 2022 base is below this
OUT = BUILD / "indicadores"
OUT.mkdir(exist_ok=True)
LEVELS = {  # level -> SQL key over the `cells` table
    "sector": "sector",
    "parroquia": "parroquia",
    "canton": "substr(parroquia, 1, 4)",
    "provincia": "substr(parroquia, 1, 2)",
    "pais": "'EC'",
}
APORTA = ["iess_general", "iess_voluntario", "iess_campesino", "issfa_isspol"]
T0 = time.time()


def log(msg):
    print(f"[{time.time() - T0:5.0f}s] {msg}", flush=True)


con = duckdb.connect()
con.sql("SET threads = 8")
for y in YEARS:
    con.sql(f"CREATE VIEW p{y} AS SELECT * FROM '{BUILD / f'personas_{y}.parquet'}'")
con.sql(f"CREATE VIEW xw AS SELECT * FROM '{BUILD / 'xwalk' / 'sec2010_sec2022.parquet'}'")

# --- 1. counts per census sector ----------------------------------------------------
cat_cols = ", ".join(VARIABLES)
for y in YEARS:
    con.sql(f"""
        CREATE TABLE raw{y} AS
        WITH u AS (
          UNPIVOT (
            SELECT sector, {cat_cols},
                   lpad(CAST(least(edad, 100) AS VARCHAR), 3, '0') AS edad_simple,
                   sexo || '_' || lpad(CAST(least(edad // 5 * 5, 85) AS VARCHAR), 2, '0') AS piramide
            FROM p{y})
          ON {cat_cols}, edad_simple, piramide
          INTO NAME var VALUE cat)
        SELECT sector, var, cat, count(*)::DOUBLE AS n FROM u GROUP BY ALL
        UNION ALL
        SELECT sector, 'escolaridad_25', 'suma', sum(escolaridad)::DOUBLE FROM p{y} WHERE edad >= 25 GROUP BY 1
        UNION ALL
        SELECT sector, 'escolaridad_25', 'n', count(escolaridad)::DOUBLE FROM p{y} WHERE edad >= 25 GROUP BY 1""")
log("sector counts")

# --- 2. 2010 -> 2022 sectors ------------------------------------------------------
con.sql("""
    CREATE TABLE cells AS
    SELECT 2022 AS anio, sector, substr(sector, 1, 6) AS parroquia, var, cat, n FROM raw2022
    UNION ALL
    SELECT 2010, x.sector_2022, x.parroquia_2022, r.var, r.cat, sum(r.n * x.peso)
    FROM raw2010 r JOIN xw x ON x.sector_2010 = r.sector
    GROUP BY ALL""")
unmapped = con.sql("SELECT count(*) FROM raw2010 WHERE sector NOT IN (SELECT sector_2010 FROM xw)").fetchone()[0]
assert unmapped == 0, f"{unmapped} 2010 count rows have no crosswalk entry"
log("2010 counts interpolated onto 2022 sectors")

# category grid (every unit gets every category, missing = 0)
grid = pd.DataFrame([(var, cat, i) for var, v in VARIABLES.items()
                     for i, cat in enumerate(list(v["categories"]) + ([UNKNOWN] if var in
                                                                     ("seguridad_social", "educacion") else []))],
                    columns=["var", "cat", "ord"])
con.register("grid", grid)

qa = []
for nivel, key in LEVELS.items():
    con.sql(f"""CREATE OR REPLACE TABLE L AS
                SELECT {key} AS unidad, anio, var, cat, sum(n) AS n FROM cells
                WHERE {key} IS NOT NULL GROUP BY ALL""")

    # --- 3. categorical shares and change ----------------------------------------
    cat = con.sql(f"""
        WITH units AS (SELECT DISTINCT unidad FROM L),
        g AS (SELECT u.unidad, grid.var, grid.cat, grid.ord FROM units u CROSS JOIN grid),
        v AS (
          SELECT g.unidad, g.var AS variable, g.cat AS categoria, g.ord,
                 coalesce(sum(L.n) FILTER (WHERE L.anio = 2010), 0) AS n_2010,
                 coalesce(sum(L.n) FILTER (WHERE L.anio = 2022), 0) AS n_2022
          FROM g LEFT JOIN L ON L.unidad = g.unidad AND L.var = g.var AND L.cat = g.cat
          GROUP BY ALL),
        b AS (
          SELECT *,
                 sum(CASE WHEN categoria <> '{UNKNOWN}' THEN n_2010 ELSE 0 END)
                     OVER (PARTITION BY unidad, variable) AS base_2010,
                 sum(CASE WHEN categoria <> '{UNKNOWN}' THEN n_2022 ELSE 0 END)
                     OVER (PARTITION BY unidad, variable) AS base_2022
          FROM v)
        SELECT unidad, variable, categoria, n_2010, n_2022,
               n_2022 - n_2010 AS cambio_abs,
               CASE WHEN n_2010 > 0 THEN 100 * (n_2022 / n_2010 - 1) END AS cambio_pct,
               base_2010, base_2022,
               CASE WHEN categoria <> '{UNKNOWN}' AND base_2010 > 0 THEN 100 * n_2010 / base_2010 END AS pct_2010,
               CASE WHEN categoria <> '{UNKNOWN}' AND base_2022 > 0 THEN 100 * n_2022 / base_2022 END AS pct_2022,
               pct_2022 - pct_2010 AS cambio_pp,
               least(base_2010, base_2022) < {MIN_BASE} AS pequena
        FROM b ORDER BY unidad, variable, ord""").df()
    cat.to_parquet(OUT / f"{nivel}_categorias.parquet", index=False)

    # --- pyramid -------------------------------------------------------------------
    pyr = con.sql("""
        SELECT unidad, split_part(cat, '_', 1) AS sexo, split_part(cat, '_', 2) AS grupo,
               coalesce(sum(n) FILTER (WHERE anio = 2010), 0) AS n_2010,
               coalesce(sum(n) FILTER (WHERE anio = 2022), 0) AS n_2022
        FROM L WHERE var = 'piramide' GROUP BY ALL ORDER BY unidad, sexo, grupo""").df()
    pyr.to_parquet(OUT / f"{nivel}_piramide.parquet", index=False)

    # --- 4. summary indicators -------------------------------------------------------
    med = con.sql("""
        WITH a AS (SELECT unidad, anio, CAST(cat AS INTEGER) AS edad, n FROM L WHERE var = 'edad_simple'),
        c AS (SELECT *, sum(n) OVER (PARTITION BY unidad, anio ORDER BY edad ROWS UNBOUNDED PRECEDING) AS cum,
                        sum(n) OVER (PARTITION BY unidad, anio) AS tot FROM a)
        SELECT unidad, anio,
               arg_min(edad + (tot / 2 - (cum - n)) / n, edad) FILTER (WHERE cum >= tot / 2 AND n > 0) AS mediana
        FROM c GROUP BY ALL""").df().pivot(index="unidad", columns="anio", values="mediana")
    esc = con.sql("""SELECT unidad, anio, cat, n FROM L WHERE var = 'escolaridad_25'""").df() \
             .pivot_table(index="unidad", columns=["anio", "cat"], values="n", aggfunc="sum")

    rows = []
    wide = {y: cat.pivot_table(index="unidad", columns=["variable", "categoria"], values=f"n_{y}",
                               aggfunc="sum") for y in YEARS}
    for y in YEARS:
        w = wide[y]
        e = w["grupo_edad"]
        ss = w["seguridad_social"].drop(columns=UNKNOWN)
        ed = w["educacion"].drop(columns=UNKNOWN)
        pob = e.sum(axis=1)
        n_esc = esc.get((y, "n"), pd.Series(dtype=float)).reindex(w.index)
        ind = {
            "poblacion": (pob, pob),
            "edad_mediana": (med[y].reindex(w.index), pob),
            "razon_dependencia": (100 * (e["0_14"] + e["65_mas"]) / e["15_64"].replace(0, np.nan), pob),
            "indice_envejecimiento": (100 * e["65_mas"] / e["0_14"].replace(0, np.nan), pob),
            "pct_aporta": (100 * ss[APORTA].sum(axis=1) / ss.sum(axis=1).replace(0, np.nan), ss.sum(axis=1)),
            "pct_superior": (100 * ed[["superior", "posgrado"]].sum(axis=1) / ed.sum(axis=1).replace(0, np.nan),
                             ed.sum(axis=1)),
            "escolaridad_media": (esc.get((y, "suma"), pd.Series(dtype=float)).reindex(w.index)
                                  / n_esc.replace(0, np.nan), n_esc),
        }
        for k, (val, base) in ind.items():
            rows.append(pd.DataFrame({"unidad": w.index, "indicador": k, "anio": y,
                                      "v": val.values, "base": base.fillna(0).values}))
    res = pd.concat(rows).pivot_table(index=["unidad", "indicador"], columns="anio",
                                      values=["v", "base"], dropna=False).reset_index()
    res.columns = ["unidad", "indicador"] + [f"{a}_{y}" for a, y in res.columns[2:]]
    res = res.rename(columns={"v_2010": "v_2010", "v_2022": "v_2022"})
    res["cambio"] = res.v_2022 - res.v_2010
    res["cambio_pct"] = np.where(res.indicador == "poblacion",
                                 100 * (res.v_2022 / res.v_2010.replace(0, np.nan) - 1), np.nan)
    res["pequena"] = res[["base_2010", "base_2022"]].min(axis=1) < MIN_BASE
    order = {k: i for i, k in enumerate(ind)}
    res = res.sort_values(["unidad", "indicador"], key=lambda s: s.map(order) if s.name == "indicador" else s)
    res = res[["unidad", "indicador", "v_2010", "v_2022", "cambio", "cambio_pct",
               "base_2010", "base_2022", "pequena"]]
    res.to_parquet(OUT / f"{nivel}_resumen.parquet", index=False)

    n_units = cat.unidad.nunique()
    small = res[res.indicador == "poblacion"].pequena.sum()
    qa.append({"nivel": nivel, "unidades": n_units, "pequenas_poblacion": int(small),
               "pob_2010": cat[cat.variable == "grupo_edad"].n_2010.sum(),
               "pob_2022": cat[cat.variable == "grupo_edad"].n_2022.sum()})
    log(f"{nivel}: {n_units:,} units, {small:,} with population base < {MIN_BASE}")

# --- QA ---------------------------------------------------------------------------
qa = pd.DataFrame(qa)
print(qa.to_string(index=False))
problems = []
nat = pd.read_parquet(OUT / "pais_categorias.parquet")
ref = pd.read_csv(DOCS / "audit" / "national_by_category.csv", dtype={"categoria": str})
chk = nat.merge(ref, on=["variable", "categoria"], suffixes=("", "_ref"))
for y in YEARS:
    bad = chk[(chk[f"n_{y}"] - chk[f"n_{y}_ref"].fillna(0)).abs() > 0.5]
    if len(bad):
        problems.append(f"national {y} counts differ from 02_audit:\n{bad}")
for nivel in ["parroquia", "canton", "provincia"]:
    d = pd.read_parquet(OUT / f"{nivel}_categorias.parquet")
    s = d.groupby(["variable", "categoria"])[["n_2010", "n_2022"]].sum()
    n = nat.set_index(["variable", "categoria"])[["n_2010", "n_2022"]]
    diff = (s - n).abs().max().max()
    if diff > 0.5:
        problems.append(f"{nivel}: sum over units differs from national by {diff}")
# 2022 parroquia totals must equal the microdata exactly
direct = con.sql("SELECT substr(sector, 1, 6) AS unidad, count(*) AS pop FROM p2022 GROUP BY 1").df()
par = pd.read_parquet(OUT / "parroquia_resumen.parquet").query("indicador == 'poblacion'")
m = direct.merge(par, on="unidad", how="outer")
if (m["pop"] - m.v_2022).abs().max() > 0 or m.isna()[["pop", "v_2022"]].any().any():
    problems.append("2022 parroquia totals differ from microdata")
qa.to_csv(DOCS / "audit" / "indicadores_qa.csv", index=False)

print(pd.read_parquet(OUT / "pais_resumen.parquet").round(2).to_string(index=False))
if problems:
    raise SystemExit("QA FAILED:\n  " + "\n  ".join(problems))
log("All checks passed.")
