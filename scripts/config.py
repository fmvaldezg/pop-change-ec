"""Paths used by every pipeline script. Run scripts with the `geo` conda env:

    conda run -n geo python scripts/<script>.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
BUILD = ROOT / "build"
DOCS = ROOT / "docs"
ASSETS = ROOT / "assets"  # published web assets (PMTiles + JSON)

# Census microdata (person tables)
CSV_2010 = DATA / "CPV2010S_CSV_Nacional" / "CPV2010S_CSV_Poblacion_1.csv"
CSV_2022 = DATA / "1.2 BDD_CPV_2022_SECTOR_CSV" / "CPV_2022_Poblacion_Sector.csv"

# Cartography (both EPSG:32717 = WGS 84 / UTM 17S, the working CRS)
# BNCPV22 = census-2022 cartographic base (Marco Geoestadístico 2023): sec_a.sec matches the
# census sector id; edif_p.man / .loc carry the census block / locality code.
GPKG_2022 = DATA / "MARCO_GEOESTADISTICO_2023" / "BNCPV22.gpkg"
GDB_2010 = DATA / "Geodatabase 2014 Ajustada Versión3" / "GEODATABASE2014.gdb"
# GEO_SEC2014 = urban sectors, GEO_SECDIS2014 = rural dispersed sectors, GEO_MAN2014 = blocks
DPA_2022 = DATA / "CLASIFICADOR GEOGRAFICO_2022" / "CODIFICACIÓN_2022.xlsx"  # sheet CODIGOS
CRS = "EPSG:32717"

# Official national totals (INEC) used as hard checks
OFFICIAL_TOTAL = {2010: 14_483_499, 2022: 16_938_986}

for d in (BUILD, DOCS, ASSETS):
    d.mkdir(exist_ok=True)
