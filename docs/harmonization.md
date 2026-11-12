# Harmonization spec: CPV 2010 ↔ CPV 2022

The code lives in [`scripts/harmonize.py`](../scripts/harmonize.py). This document explains it. If the two ever disagree, the code wins: update this file whenever the code changes.

## Sources

| | 2010 | 2022 |
|---|---|---|
| Person table | `CPV2010S_CSV_Poblacion_1.csv` (`,`), 14,483,499 rows | `CPV_2022_Poblacion_Sector.csv` (`;`), 16,938,986 rows |
| Code list | INEC 2010 questionnaire + empirical checks | `DICCIONARIO_BDD_MANLOC.xlsx`, sheet "5. Población" |
| Sector geometry | `GEODATABASE2014.gdb`: `GEO_SEC2014` (urban) + `GEO_SECDIS2014` (rural dispersed), EPSG:32717 | `MGN26_sirgas 2.gpkg`: `sec_a`, EPSG:31992 |

**Sector id:** `I01‖I02‖I03‖I04‖I05`, 12 digits (province 2, canton 2, parroquia 2, zona 3, sector 3), with zona `999` for rural dispersed sectors. The format is the same in both censuses. The same code does **not** mean the same polygon across years: sectors were redrawn, which is why 2010 data is interpolated onto 2022 sectors (Phase 2).

**Geometry match:** 40,630 of 40,640 sectors in the 2010 census are found in the 2014 geodatabase, covering 14,481,955 of 14,483,499 people (99.99%). The unmatched 1,544 people sit in special `…777777` codes plus one rural sector (`170350999013`). They are assigned at parroquia level only.

## Variables

Category keys are stable ids used in the data files and the web app. Labels are the Spanish UI text. **`ignorado`** (unknown) is counted and reported but left out of share denominators. 2022 has no unknowns because INEC imputed them, while 2010 does, so excluding unknowns keeps the shares comparable.

### Etnia: autoidentificación étnica (all ages)

| Key | Label | 2010 `ETNIA` | 2022 `P11R` |
|---|---|---|---|
| indigena | Indígena | 1 | 1 |
| afro | Afroecuatoriana/o | 2 | 2 |
| montubio | Montubia/o | 3 | 3 |
| mestizo | Mestiza/o | 4 | 4 |
| blanco | Blanca/o | 5 | 5 |
| otro | Otra | 6 | 6 |

- 2010 `ETNIA` is INEC's recode of `P16`: its afro group = afroecuatoriano (2) + negro (3) + mulato (4). The counts confirm this exactly.
- 2022 `P11R` is **not in the dictionary** we have. Its codes were confirmed from the data:
  - The national shares match INEC's published 2022 results (Mestizo 77.5%, Montubio 7.7%, Indígena 7.7%, Afro 4.8%, Blanco 2.2%).
  - Code 1 peaks in Napo (65%) and Chimborazo (38%), so it is Indígena.
  - Code 2 peaks in Esmeraldas (54%), so it is Afro.
  - Code 3 peaks in Los Ríos (35%) and Manabí (34%), so it is Montubio.

### Grupo de edad (all ages, from `P03` single years)

- 0–14, 15–64, 65+.
- Five-year groups (0–4 … 80–84, 85+) are kept for population pyramids and for computing a median age from grouped data.

### Estado conyugal (12+)

The two censuses use the same categories in a different order.

| Key | 2010 `P34` | 2022 `P31` |
|---|---|---|
| casado | 1 | 5 |
| unido | 2 | 1 |
| separado | 3 | 2 |
| divorciado | 4 | 3 |
| viudo | 5 | 4 |
| soltero | 6 | 6 |

The universe is ages 12+ in both censuses. This was checked in the data: no one under 12 has a value, and no one 12+ is missing one. The mean age per code (viudo ≈ 67–70, soltero ≈ 24–27, unido younger than casado) confirms the labels.

### Seguridad social: aporte o afiliación (12+)

| Key | 2010 `P35` | 2022 `P30` |
|---|---|---|
| iess_general | 3 | 1 |
| iess_voluntario | 4 | 2 |
| iess_campesino | 5 | 3 |
| issfa_isspol | 1, 2 | 4, 5 |
| jubilado | 6 | 6 |
| no_aporta | 7 | 7 |
| ignorado | 9 | 9 |

- **ISSFA and ISSPOL are merged.** Their counts are small, and their code order is reversed between the two censuses.
- The universe is 12+ in both censuses (checked in the data).
- Headline indicator: **% que aporta** = (iess_general + iess_voluntario + iess_campesino + issfa_isspol) ÷ known.

### Nivel de instrucción (25+)

The school system changed between the censuses:
- 2010: primaria (6 years) + secundaria (6 years).
- 2022: EGB (10 years) + bachillerato (3 years).

Years of schooling (2010 `GRAESC`, 2022 `ESCOLA`) are on the **same EGB-equivalent scale** in both censuses: primaria complete = 7, EGB complete = 10, bachillerato complete = 13. The 2010 code 99 means unknown. So within the primary and secondary levels, people are split by years of schooling:

| Key | 2010 `P23` | 2022 `P17R` |
|---|---|---|
| sin_instruccion | 01 ninguno, 02 alfabetización/EBA, 03 preescolar | 1 ninguno, 2 CDI, 3 inicial, 4 alfabetización |
| basica | 04–07 with years ≤ 10 | 5–6 with `ESCOLA` ≤ 10 |
| bachillerato | 04–07 with years 11–13 | 5–6 with `ESCOLA` 11–13 |
| superior | 08 postbachillerato, 09 superior | 7 postbachillerato, 8 técnica/tecnológica, 9 universitaria |
| posgrado | 10 | 10 maestría, 11 PhD |
| ignorado | 99, or years = 99 | — |

- Measured on **ages 25+**, the standard for completed attainment. 2010 asked this from age 5 and 2022 from age 0.
- Companion indicator: **años promedio de escolaridad, 25+** (mean years of schooling, with unknowns excluded).
- Known limitation: 2010 "postbachillerato" and 2022 "ciclo postbachillerato (no superior)" are both grouped under *superior*. They are small groups (≈86k and ≈47k people aged 25+).

## National check (output of `scripts/02_audit.py`)

Full table: [`docs/audit/national_by_category.csv`](audit/national_by_category.csv).

| Indicator | 2010 | 2022 | Change |
|---|---|---|---|
| Population | 14,483,499 | 16,938,986 | +17.0% |
| Median age | 25 | 29 | +4 years |
| % 65+ | 6.50 | 8.98 | +2.48 pp |
| % Indígena | 7.03 | 7.69 | +0.66 pp |
| % Afroecuatoriana/o | 7.19 | 4.81 | −2.38 pp |
| % Blanca/o | 6.09 | 2.21 | −3.88 pp |
| % Soltera/o (12+) | 36.54 | 43.51 | +6.97 pp |
| % Casada/o (12+) | 32.49 | 27.21 | −5.28 pp |
| % que aporta (12+) | 21.27 | 26.38 | +5.11 pp |
| % Superior + posgrado (25+) | 21.28 | 29.15 | +7.87 pp |
| Mean years of schooling (25+) | 9.52 | 11.28 | +1.76 |
| Unknown education (25+) | 3.37% | 0% (imputed) | |
| Unknown social security (12+) | 5.57% | 3.47% | |

## Metrics produced per unit (Phase 3)

For each unit, variable and category:
- counts for 2010 and 2022 and absolute change;
- % change in the count;
- share in 2010 and 2022, and **change in share (percentage points)**, which is the default map metric.

Units whose universe is smaller than a minimum size (proposed: 50 people) are flagged, so that percentages based on very few people are not shown as real change.
