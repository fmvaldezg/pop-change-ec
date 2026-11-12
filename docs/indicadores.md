# Indicator tables (Phase 3)

The code is in [`scripts/05_indicadores.py`](../scripts/05_indicadores.py). It takes about 12 seconds, reading `build/personas_*.parquet` and `build/xwalk/sec2010_sec2022.parquet`. The outputs are in `build/indicadores/`, one set per level: `sector`, `parroquia`, `canton`, `provincia`, `pais`.

All values are on **census-2022 geography**. 2010 counts are interpolated (see [crosswalk.md](crosswalk.md)), so they are fractional at every level below the country. Round them only when displaying.

## Files

### `{nivel}_categorias.parquet`: one row per unit × variable × category

| Column | Meaning |
|---|---|
| `n_2010`, `n_2022` | persons in the category |
| `cambio_abs` | `n_2022 − n_2010` |
| `cambio_pct` | `100 × (n_2022 / n_2010 − 1)`; null when `n_2010 = 0` |
| `base_2010`, `base_2022` | universe of the variable with unknowns excluded: total population (etnia, grupo_edad), 12+ (estado_civil, seguridad_social) or 25+ (educacion) |
| `pct_2010`, `pct_2022` | `100 × n / base`; null for `ignorado` |
| `cambio_pp` | `pct_2022 − pct_2010`: **the default map metric** |
| `pequena` | `min(base_2010, base_2022) < 50` |

Every unit has every category; missing categories are 0. The `ignorado` rows (seguridad_social, educacion) carry counts only.

### `{nivel}_resumen.parquet`: one row per unit × summary indicator

| `indicador` | Definition | Base |
|---|---|---|
| `poblacion` | total persons; `cambio_pct` = growth | population |
| `edad_mediana` | median age, linearly interpolated within single years (so 25.0 / 29.2, not the integer 25 / 29) | population |
| `razon_dependencia` | 100 × (0–14 + 65+) / 15–64 | population |
| `indice_envejecimiento` | 100 × 65+ / 0–14 | population |
| `pct_aporta` | % of persons 12+ contributing to IESS (general, voluntario, campesino) or ISSFA/ISSPOL; jubilados and "no aporta" don't count | 12+ known |
| `pct_superior` | % of persons 25+ with superior or posgrado | 25+ known |
| `escolaridad_media` | mean years of schooling, 25+ | 25+ with known years |

`cambio` = `v_2022 − v_2010`. `pequena` uses the indicator's own base.

### `{nivel}_piramide.parquet`

Persons by `sexo` (1 hombre, 2 mujer) × 5-year `grupo` (`00` … `85`, where 85 = 85+), for both years.

## Small units

`pequena = true` marks a unit/variable whose base is under **50 persons** in either year. These percentages are too unstable to read as real change. The web map will show these units hatched or grey and leave them out of the color scale.

| Level | Units | Units with population < 50 |
|---|---|---|
| sector | 53,530 | 2,609 (4.9%) |
| parroquia | 1,042 | 0 |
| cantón | 221 | 0 |
| provincia | 24 | 0 |

The sector total includes 579 census sectors that have no polygon (counted, but not drawn), and 2010-only sectors (polygons with 2010 people but nobody in 2022). The 1,544 people from 2010 sectors with no polygon only exist from parroquia level up, which is why the sector-level 2010 total is 14,481,955.

## QA (enforced by the script)

- National counts per category equal `docs/audit/national_by_category.csv` in both years.
- Summed over parroquias, cantones or provincias, every category equals the national total.
- The 2022 total of every parroquia equals a direct count of the microdata.

## National summary

| Indicator | 2010 | 2022 | Change |
|---|---|---|---|
| Population | 14,483,499 | 16,938,986 | +16.95% |
| Median age | 25.0 | 29.2 | +4.2 |
| Dependency ratio | 60.7 | 52.5 | −8.2 |
| Ageing index | 20.8 | 35.3 | +14.5 |
| % que aporta (12+) | 21.3 | 26.4 | +5.1 pp |
| % superior + posgrado (25+) | 21.3 | 29.2 | +7.9 pp |
| Mean years of schooling (25+) | 9.5 | 11.3 | +1.8 |

**Plausibility checks at cantón level:**
- **Largest growth:** Daule (+82%, Guayaquil's suburban expansion), Palora (+71%), Jaramijó (+61%).
- **Largest decline:** Colta (−31%, with median age +8.4 years), Jama (−28%), Sevilla de Oro (−22%).
- **Highest shares in 2022:** Indígena in Guamote (97.7%), Taisha and Arajuno; Afro in San Lorenzo (83.9%), Eloy Alfaro and Rioverde.

Some change reflects differences in census coverage between the two years, not only real demographic change. The methodology note in the app should say so.
