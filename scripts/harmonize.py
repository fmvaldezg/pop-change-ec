"""Single source of truth for harmonizing CPV 2010 and CPV 2022 person variables.

Every later step (aggregation, interpolation, web labels) imports from here.
Code lists were verified against:
  * 2022: DICCIONARIO_BDD_MANLOC.xlsx (sheet "5. Población") — except P11R,
    which is not in that dictionary and was verified empirically (see docs/harmonization.md).
  * 2010: INEC CPV 2010 questionnaire (boleta censal) + empirical cross-tabs.
"""
from config import CSV_2010, CSV_2022

YEARS = (2010, 2022)
UNKNOWN = "ignorado"  # reported, but excluded from share denominators

# ---------------------------------------------------------------------------
# Raw sources
# ---------------------------------------------------------------------------
SOURCES = {
    2010: {"path": CSV_2010, "delim": ","},
    2022: {"path": CSV_2022, "delim": ";"},
}

# 12-digit sector id: prov(2) + canton(2) + parroquia(2) + zona(3) + sector(3).
# Rural dispersed sectors use zona = '999' in both censuses.
SECTOR_ID = {y: "trim(I01)||trim(I02)||trim(I03)||trim(I04)||trim(I05)" for y in YEARS}
AGE = {y: "TRY_CAST(trim(P03) AS INTEGER)" for y in YEARS}
SEX = {  # 1 hombre, 2 mujer
    2010: "trim(P01)",
    2022: "trim(P02)",
}
# Years of schooling on the EGB-equivalent scale (primaria completa = 7,
# EGB completa = 10, bachillerato completo = 13). 2010 code 99 = unknown.
SCHOOLING = {
    2010: "CASE WHEN trim(GRAESC) IN ('', '99') THEN NULL ELSE CAST(trim(GRAESC) AS INTEGER) END",
    2022: "TRY_CAST(trim(ESCOLA) AS INTEGER)",
}

# ---------------------------------------------------------------------------
# Harmonized categorical variables
# ---------------------------------------------------------------------------
# For each variable:
#   min_age    universe (persons with age >= min_age); NULL category outside it
#   categories ordered {key: Spanish label}
#   source     raw column per year (when a plain code map is enough)
#   codes      raw code -> category key per year (anything unmapped -> UNKNOWN)
#   sql        explicit CASE expression per year (overrides source/codes)
VARIABLES = {
    "etnia": {
        "label": "Autoidentificación étnica",
        "universe": "Población total",
        "min_age": 0,
        "categories": {
            "indigena": "Indígena",
            "afro": "Afroecuatoriana/o",
            "montubio": "Montubia/o",
            "mestizo": "Mestiza/o",
            "blanco": "Blanca/o",
            "otro": "Otra",
        },
        # 2010 ETNIA is INEC's recode of P16 (afro = afroecuatoriano + negro + mulato),
        # identical in structure to 2022 P11R.
        "source": {2010: "ETNIA", 2022: "P11R"},
        "codes": {
            2010: {"1": "indigena", "2": "afro", "3": "montubio", "4": "mestizo", "5": "blanco", "6": "otro"},
            2022: {"1": "indigena", "2": "afro", "3": "montubio", "4": "mestizo", "5": "blanco", "6": "otro"},
        },
    },
    "grupo_edad": {
        "label": "Grandes grupos de edad",
        "universe": "Población total",
        "min_age": 0,
        "categories": {"0_14": "0 a 14 años", "15_64": "15 a 64 años", "65_mas": "65 años y más"},
        "sql": {
            y: f"CASE WHEN {AGE[y]} < 15 THEN '0_14' WHEN {AGE[y]} < 65 THEN '15_64' ELSE '65_mas' END"
            for y in YEARS
        },
    },
    "estado_civil": {
        "label": "Estado conyugal",
        "universe": "Población de 12 años y más",
        "min_age": 12,
        "categories": {
            "casado": "Casada/o",
            "unido": "Unida/o",
            "separado": "Separada/o",
            "divorciado": "Divorciada/o",
            "viudo": "Viuda/o",
            "soltero": "Soltera/o",
        },
        "source": {2010: "P34", 2022: "P31"},
        "codes": {
            2010: {"1": "casado", "2": "unido", "3": "separado", "4": "divorciado", "5": "viudo", "6": "soltero"},
            2022: {"1": "unido", "2": "separado", "3": "divorciado", "4": "viudo", "5": "casado", "6": "soltero"},
        },
    },
    "seguridad_social": {
        "label": "Aporte o afiliación a la seguridad social",
        "universe": "Población de 12 años y más",
        "min_age": 12,
        "categories": {
            "iess_general": "IESS Seguro general",
            "iess_voluntario": "IESS Seguro voluntario",
            "iess_campesino": "IESS Seguro campesino",
            "issfa_isspol": "ISSFA / ISSPOL",
            "jubilado": "Jubilada/o (no aporta)",
            "no_aporta": "No aporta",
        },
        # ISSFA and ISSPOL are merged: small counts and opposite code order between censuses.
        "source": {2010: "P35", 2022: "P30"},
        "codes": {
            2010: {"1": "issfa_isspol", "2": "issfa_isspol", "3": "iess_general", "4": "iess_voluntario",
                   "5": "iess_campesino", "6": "jubilado", "7": "no_aporta"},
            2022: {"1": "iess_general", "2": "iess_voluntario", "3": "iess_campesino", "4": "issfa_isspol",
                   "5": "issfa_isspol", "6": "jubilado", "7": "no_aporta"},
        },
    },
    "educacion": {
        "label": "Nivel de instrucción",
        "universe": "Población de 25 años y más",
        "min_age": 25,
        "categories": {
            "sin_instruccion": "Ninguno / alfabetización / preescolar",
            "basica": "Educación básica (hasta 10.º EGB o equivalente)",
            "bachillerato": "Bachillerato (11.º a 13.º año)",
            "superior": "Superior (técnica, tecnológica o universitaria)",
            "posgrado": "Posgrado",
        },
        # The 2010 system (primaria 6 + secundaria 6) and the 2022 system (EGB 10 + bachillerato 3)
        # are aligned through years of schooling, which share one scale in both censuses:
        # within primary/secondary levels, <= 10 years -> básica, 11-13 -> bachillerato.
        "sql": {
            2010: f"""CASE
                WHEN trim(P23) IN ('01','02','03') THEN 'sin_instruccion'
                WHEN trim(P23) IN ('04','05','06','07') AND {SCHOOLING[2010]} IS NOT NULL
                     THEN CASE WHEN {SCHOOLING[2010]} <= 10 THEN 'basica' ELSE 'bachillerato' END
                WHEN trim(P23) IN ('08','09') THEN 'superior'
                WHEN trim(P23) = '10' THEN 'posgrado'
                ELSE '{UNKNOWN}' END""",
            2022: f"""CASE
                WHEN trim(P17R) IN ('1','2','3','4') THEN 'sin_instruccion'
                WHEN trim(P17R) IN ('5','6')
                     THEN CASE WHEN {SCHOOLING[2022]} <= 10 THEN 'basica' ELSE 'bachillerato' END
                WHEN trim(P17R) IN ('7','8','9') THEN 'superior'
                WHEN trim(P17R) IN ('10','11') THEN 'posgrado'
                ELSE '{UNKNOWN}' END""",
        },
    },
}

# Five-year age groups for pyramids and grouped-median age (last group open: 85+).
AGE_GROUPS = [(lo, lo + 4) for lo in range(0, 85, 5)] + [(85, None)]


def category_sql(var: str, year: int) -> str:
    """SQL expression returning the harmonized category key (NULL outside the universe)."""
    v = VARIABLES[var]
    if "sql" in v:
        expr = v["sql"][year]
    else:
        col = f"trim({v['source'][year]})"
        whens = " ".join(f"WHEN '{raw}' THEN '{key}'" for raw, key in v["codes"][year].items())
        expr = f"CASE {col} {whens} ELSE '{UNKNOWN}' END"
    return f"CASE WHEN {AGE[year]} >= {v['min_age']} THEN ({expr}) END"


def persons_select(year: int) -> str:
    """SELECT that reads one census CSV and returns one harmonized row per person."""
    src = SOURCES[year]
    cats = ",\n       ".join(f"{category_sql(v, year)} AS {v}" for v in VARIABLES)
    return f"""
SELECT {SECTOR_ID[year]} AS sector,
       {AGE[year]} AS edad,
       {SEX[year]} AS sexo,
       {SCHOOLING[year]} AS escolaridad,
       {cats}
FROM read_csv('{src['path']}', delim='{src['delim']}', header=true, all_varchar=true)
"""
