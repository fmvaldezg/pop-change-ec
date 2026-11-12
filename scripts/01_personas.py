"""Phase 1 — read each census person table once and write harmonized microdata.

Output: build/personas_{2010,2022}.parquet — one row per person with
sector id, age, sex, years of schooling and one harmonized category per variable.

    conda run -n geo python scripts/01_personas.py
"""
import time

import duckdb

from config import BUILD
from harmonize import YEARS, persons_select

con = duckdb.connect()
con.sql("SET threads = 8")

for year in YEARS:
    t = time.time()
    out = BUILD / f"personas_{year}.parquet"
    con.sql(f"COPY ({persons_select(year)}) TO '{out}' (FORMAT parquet, COMPRESSION zstd)")
    n = con.sql(f"SELECT count(*) FROM '{out}'").fetchone()[0]
    print(f"{year}: {n:,} persons -> {out.name} ({out.stat().st_size / 1e6:.0f} MB, {time.time() - t:.0f}s)")
