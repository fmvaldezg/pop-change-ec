"""Phase 1 — validate the harmonized microdata and write national reference tables.

Hard checks (raise on failure):
  * national totals equal INEC official totals
  * every person inside a variable's universe has a category; nobody outside does
  * sector ids are 12-digit codes
Outputs:
  docs/audit/national_by_category.csv   counts + shares per year, change in pp
  docs/audit/national_summary.csv       median age, mean schooling, unknown rates

    conda run -n geo python scripts/02_audit.py
"""
import duckdb

from config import BUILD, DOCS, OFFICIAL_TOTAL
from harmonize import UNKNOWN, VARIABLES, YEARS

out_dir = DOCS / "audit"
out_dir.mkdir(exist_ok=True)
con = duckdb.connect()
for y in YEARS:
    con.sql(f"CREATE VIEW p{y} AS SELECT * FROM '{BUILD / f'personas_{y}.parquet'}'")

problems = []

# --- totals and ids -------------------------------------------------------
for y in YEARS:
    n, bad_ids, bad_age = con.sql(f"""
        SELECT count(*),
               count(*) FILTER (WHERE NOT regexp_full_match(sector, '[0-9]{{12}}')),
               count(*) FILTER (WHERE edad IS NULL)
        FROM p{y}""").fetchone()
    print(f"{y}: total={n:,} official={OFFICIAL_TOTAL[y]:,} bad_sector_ids={bad_ids} null_age={bad_age}")
    if n != OFFICIAL_TOTAL[y]:
        problems.append(f"{y} total {n} != official {OFFICIAL_TOTAL[y]}")
    if bad_ids or bad_age:
        problems.append(f"{y}: {bad_ids} bad sector ids, {bad_age} null ages")

# --- universes --------------------------------------------------------------
for var, v in VARIABLES.items():
    for y in YEARS:
        inside_null, outside_set = con.sql(f"""
            SELECT count(*) FILTER (WHERE edad >= {v['min_age']} AND {var} IS NULL),
                   count(*) FILTER (WHERE edad <  {v['min_age']} AND {var} IS NOT NULL)
            FROM p{y}""").fetchone()
        if inside_null or outside_set:
            problems.append(f"{var} {y}: {inside_null} null inside universe, {outside_set} set outside")

# --- national distributions ----------------------------------------------
rows = []
for var, v in VARIABLES.items():
    order = list(v["categories"]) + [UNKNOWN]
    for y in YEARS:
        for cat, n in con.sql(f"SELECT {var}, count(*) FROM p{y} WHERE {var} IS NOT NULL GROUP BY 1").fetchall():
            if cat not in order:
                problems.append(f"{var} {y}: unexpected category {cat!r}")
            rows.append((var, cat, y, n))
con.sql("CREATE TABLE d(variable VARCHAR, categoria VARCHAR, anio INT, n BIGINT)")
con.executemany("INSERT INTO d VALUES (?, ?, ?, ?)", rows)
order_sql = " ".join(
    f"WHEN variable='{var}' AND categoria='{c}' THEN {100 * k + i}"
    for k, (var, v) in enumerate(VARIABLES.items())
    for i, c in enumerate(list(v["categories"]) + [UNKNOWN])
)
table = con.sql(f"""
    WITH s AS (
      SELECT *, n / sum(n) FILTER (WHERE categoria <> '{UNKNOWN}') OVER (PARTITION BY variable, anio) AS share
      FROM d)
    SELECT variable, categoria,
           sum(n) FILTER (WHERE anio=2010) AS n_2010,
           sum(n) FILTER (WHERE anio=2022) AS n_2022,
           round(100 * (n_2022 / n_2010 - 1), 1) AS cambio_pct,
           round(100 * max(share) FILTER (WHERE anio=2010 AND categoria <> '{UNKNOWN}'), 2) AS pct_2010,
           round(100 * max(share) FILTER (WHERE anio=2022 AND categoria <> '{UNKNOWN}'), 2) AS pct_2022,
           round(pct_2022 - pct_2010, 2) AS cambio_pp
    FROM s GROUP BY variable, categoria
    ORDER BY CASE {order_sql} END""")
table.write_csv(str(out_dir / "national_by_category.csv"))
print(table.df().to_string(index=False))

# --- summary indicators -----------------------------------------------------
summary = con.sql(f"""
    SELECT 2010 AS anio, median(edad) AS edad_mediana,
           round(avg(escolaridad) FILTER (WHERE edad >= 25), 2) AS escolaridad_media_25,
           round(100 * avg((escolaridad IS NULL)::INT) FILTER (WHERE edad >= 25), 2) AS pct_escolaridad_ignorada_25,
           round(100 * avg((educacion = '{UNKNOWN}')::INT) FILTER (WHERE edad >= 25), 2) AS pct_educacion_ignorada_25,
           round(100 * avg((seguridad_social = '{UNKNOWN}')::INT) FILTER (WHERE edad >= 12), 2) AS pct_ss_ignorada_12
    FROM p2010
    UNION ALL
    SELECT 2022, median(edad),
           round(avg(escolaridad) FILTER (WHERE edad >= 25), 2),
           round(100 * avg((escolaridad IS NULL)::INT) FILTER (WHERE edad >= 25), 2),
           round(100 * avg((educacion = '{UNKNOWN}')::INT) FILTER (WHERE edad >= 25), 2),
           round(100 * avg((seguridad_social = '{UNKNOWN}')::INT) FILTER (WHERE edad >= 12), 2)
    FROM p2022""")
summary.write_csv(str(out_dir / "national_summary.csv"))
print(summary.df().to_string(index=False))

if problems:
    raise SystemExit("AUDIT FAILED:\n  " + "\n  ".join(problems))
print("\nAll checks passed.")
