# Geography and the 2010 → 2022 crosswalk

The code is in [`scripts/03_geografia.py`](../scripts/03_geografia.py) and [`scripts/04_crosswalk.py`](../scripts/04_crosswalk.py). The QA tables are in [`docs/audit/`](audit/).

## Reporting geography: census-2022 boundaries

| Level | Units | Source |
|---|---|---|
| Sector | 52,960 | `BNCPV22.gpkg` → `sec_a`, field `sec` (the census sector id) |
| Parroquia | 1,042 | sectors dissolved by the first 6 digits of the code |
| Cantón | 221 | first 4 digits |
| Provincia | 24 | first 2 digits |

- Names come from `CODIFICACIÓN_2022.xlsx` (INEC Clasificador Geográfico Estadístico 2022). Its codes match the census codes exactly.
- 52,891 of 53,470 census sectors have a polygon, covering 99.93% of the 2022 population. The remaining 579 sectors (11,631 people, mostly special codes `…999888`) count from parroquia level up, but are not drawn.
- 69 polygons have no 2022 population.
- **Why not MGN26** (`MGN26_sirgas 2.gpkg`): it is the 2026 edition. It includes parroquias and a cantón created after the census, such as `141350` / cantón `1413` split from `140157`, and their sectors are recoded. Its codes don't match the 2022 microdata.

## Interpolating 2010 data onto 2022 sectors

Sector codes repeat across censuses, but the polygons were redrawn. Matching by code gives a sector-level correlation of only 0.46 between 2010 and 2022 population, and a median ratio of 0.87 when the country grew by 17%. The 2010 public microdata only goes down to sector: `I09` is a building number, not a block. So the unit being split is the **2010 sector**.

Each 2010 sector is split across the 2022 sectors it overlaps, weighted by **2022 building points** (`BNCPV22 edif_p`, 5.6 M points; each carries its census sector code, so assigning it to a 2022 sector needs no spatial lookup).

| Method | When | 2010 sectors | 2010 population |
|---|---|---|---|
| `edif_manz2010` | Urban 2010 sector: only buildings that fall **inside 2010 blocks** (`GEO_MAN2014`) count, so neighbourhoods built after 2010 receive no 2010 population | 24,692 | 74.32% |
| `edif` | Rural dispersed 2010 sector, or an urban one with no buildings inside its blocks | 15,921 | 25.64% |
| `area` | No building points: share of overlapping area | 17 | 0.03% |
| `parroquia` | 2010 sector with no polygon (special `…777777` codes): assigned to the 2022 parroquia only | 10 | 0.01% |

- Overlap pieces with less than 1% of a sector's weight are dropped, and the remaining weights are renormalized. This removes slivers caused by the two cartographies being digitized differently.
- Weights sum to 1 for every 2010 sector, and the allocated total is exactly 14,483,499.
- Every category of a 2010 sector (ethnicity, age, …) is split with the same weight. This assumes uniform composition within a 2010 sector, the standard assumption of areal interpolation.

## QA

**Sector level** (`audit/crosswalk_sector_pob.csv`):

| | Code match (naive) | Interpolated |
|---|---|---|
| Correlation, 2010 vs 2022 population | 0.46 | **0.67** |
| Median 2022 ÷ 2010 (national growth 1.17) | 0.87 | **1.11** |
| Sectors with >3× growth or <⅓ | 4.5% | 5.1% |

- 1,596 of the 2022 sectors have an interpolated 2010 base under 50 people. These are flagged in Phase 3.
- 25 sectors are new, with no 2010 population.
- The remaining extreme sectors are mostly genuine fast urbanization or depopulation, which no building-based weight can predict.

**Provincia level** (`audit/crosswalk_provincia.csv`): differences between direct 2010 totals and interpolated totals are all explained by real DPA changes:
- **La Concordia** moved from Esmeraldas (08, −8.6%) to Santo Domingo (23, +11.8%).
- The 2010 **zonas no delimitadas** (province 90, 32,384 people) were absorbed into neighbouring provinces. For example, Manga del Cura went to Manabí (+1.5%), and Las Golondrinas to Imbabura (+1.5%).
- Every other province is within ±1%.

**Parroquia level** (`audit/crosswalk_parroquia.csv`):
- 97.9% of 2010 residents stay in a parroquia with the same code.
- 0.8% move to parroquias created between 2010 and 2022.
- 1.3% move between existing parroquias. These are mostly redrawn urban limits (cabecera cantonal ↔ adjacent rural parroquia), not slivers: pieces under 5% of a sector's weight add up to only about 6.8k people.
