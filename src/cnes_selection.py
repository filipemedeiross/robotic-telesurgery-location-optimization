"""CNES ST/LT/SR screening and CSV contracts, without acquisition or plotting"""

from pathlib     import Path
from dataclasses import dataclass

import pandas as pd


COMPETENCE = "202606"

STATE_BY_PREFIX = {
    "11": "RO",
    "12": "AC",
    "13": "AM",
    "14": "RR",
    "15": "PA",
    "16": "AP",
    "17": "TO",
    "21": "MA",
    "22": "PI",
    "23": "CE",
    "24": "RN",
    "25": "PB",
    "26": "PE",
    "27": "AL",
    "28": "SE",
    "29": "BA",
    "31": "MG",
    "32": "ES",
    "33": "RJ",
    "35": "SP",
    "41": "PR",
    "42": "SC",
    "43": "RS",
    "50": "MS",
    "51": "MT",
    "52": "GO",
    "53": "DF",
}
STATES = tuple(sorted(STATE_BY_PREFIX.values()))

LEGACY_TYPE_LABELS = {
    "01": "Posto de Saúde"                                                    ,
    "02": "Centro de Saúde/Unidade Básica"                                    ,
    "04": "Policlínica"                                                       ,
    "05": "Hospital Geral"                                                    ,
    "07": "Hospital Especializado"                                            ,
    "09": "Pronto Socorro de Hospital Geral (antigo)"                         ,
    "12": "Pronto Socorro Traumato-Ortopédico (antigo)"                       ,
    "15": "Unidade Mista"                                                     ,
    "20": "Pronto Socorro Geral"                                              ,
    "21": "Pronto Socorro Especializado"                                      ,
    "22": "Consultório Isolado"                                               ,
    "32": "Unidade Móvel Fluvial"                                             ,
    "36": "Clínica/Centro de Especialidade"                                   ,
    "39": "Unidade de Apoio Diagnose e Terapia (SADT Isolado)"                ,
    "40": "Unidade Móvel Terrestre"                                           ,
    "42": "Unidade Móvel de Nível Pré-Hospitalar na Área de Urgência"         ,
    "43": "Farmácia"                                                          ,
    "45": "Unidade de Saúde da Família"                                       ,
    "50": "Unidade de Vigilância em Saúde"                                    ,
    "60": "Cooperativa ou Empresa de Cessão de Trabalhadores na Saúde"        ,
    "61": "Centro de Parto Normal - Isolado"                                  ,
    "62": "Hospital/Dia - Isolado"                                            ,
    "63": "Unidade Autorizadora"                                              ,
    "64": "Central de Regulação de Serviços de Saúde"                         ,
    "65": "Unidade de Vigilância Epidemiológica (antigo)"                     ,
    "66": "Unidade de Vigilância Sanitária (antigo)"                          ,
    "67": "Laboratório Central de Saúde Pública (LACEN)"                      ,
    "68": "Central de Gestão em Saúde"                                        ,
    "69": "Centro de Atenção Hemoterápica e/ou Hematológica"                  ,
    "70": "Centro de Atenção Psicossocial"                                    ,
    "71": "Centro de Apoio à Saúde da Família"                                ,
    "72": "Unidade de Atenção à Saúde Indígena"                               ,
    "73": "Pronto Atendimento"                                                ,
    "74": "Polo Academia da Saúde"                                            ,
    "75": "Telessaúde"                                                        ,
    "76": "Central de Regulação Médica das Urgências"                         ,
    "77": "Serviço de Atenção Domiciliar Isolado (Home Care)"                 ,
    "78": "Unidade de Atenção em Regime Residencial"                          ,
    "79": "Oficina Ortopédica"                                                ,
    "80": "Laboratório de Saúde Pública"                                      ,
    "81": "Central de Regulação do Acesso"                                    ,
    "82": "Central de Notificação, Captação e Distribuição de Órgãos Estadual",
    "83": "Polo de Prevenção de Doenças e Agravos e Promoção da Saúde"        ,
    "84": "Central de Abastecimento"                                          ,
    "85": "Centro de Imunização"                                              ,
}
LEGACY_HOSPITAL_TYPE_CODES = frozenset({"05", "07"            })
ADULT_ICU_BED_CODES        = frozenset({"61", "74", "75", "76"})

SUPPORT_SERVICE_CODES = {
    "diagnostic_imaging"  : "121",
    "hemotherapy"         : "128",
    "clinical_laboratory" : "145",
    "urology"             : "169",
    "videolaparoscopy"    : "146",
}

SOURCE_COLUMNS = {
    "ST" : (
        "CNES"    ,
        "CODUFMUN",
        "TP_UNID" ,
        "COMPETEN",
        "VINC_SUS",
        "GESPRG6E",
        "GESPRG6M",
        "LEITHOSP",
        "QTLEITP1",
        "ATENDHOS",
        "CENTRCIR",
        "QTINST31",
        "QTINST32",
    ),
    "LT" : ("CNES", "CODLEITO", "QT_EXIST" , "COMPETEN"            ),
    "SR" : ("CNES", "SERV_ESP", "HOSP_NSUS", "HOSP_SUS", "COMPETEN"),
}

ELIGIBILITY_CHECKS = (
    ("Tipo legado Hospital Geral ou Hospital Especializado", "is_legacy_hospital_type"                 ),
    ("Alta complexidade hospitalar registrada"             , "has_hospital_high_complexity"            ),
    ("Atendimento hospitalar registrado"                   , "has_hospital_care"                       ),
    ("Leitos hospitalares registrados"                     , "has_hospital_beds"                       ),
    ("Centro cirúrgico registrado"                         , "has_surgical_center"                     ),
    ("Pelo menos uma sala cirúrgica"                       , "has_operating_room"                      ),
    ("Pelo menos uma sala de recuperação"                  , "has_recovery_room"                       ),
    ("Pelo menos um leito cirúrgico"                       , "has_surgical_beds"                       ),
    ("Pelo menos um leito de UTI adulto"                   , "has_adult_icu"                           ),
    ("Diagnóstico por imagem vinculado ao hospital"        , "has_hospital_diagnostic_imaging_service" ),
    ("Laboratório clínico vinculado ao hospital"           , "has_hospital_clinical_laboratory_service"),
    ("Hemoterapia vinculada ao hospital"                   , "has_hospital_hemotherapy_service"        ),
)
LIST_DEFINITIONS = {
    "broad"      : "Tipos legados CNES TP_UNID 05 e 07; sem exigência de infraestrutura."       ,
    "candidates" : "Conjunto amplo com GESPRG6E=1 ou GESPRG6M=1 (alta complexidade hospitalar).",
    "restricted" : "Conjunto padrão que satisfaz todos os critérios observáveis ST/LT/SR."      ,
}

REMOVED_COLUMNS = frozenset({
    "datasus_municipality_code"     ,
    "competence"                    ,
    "competencia"                   ,
    "COMPETEN"                      ,
    "legacy_establishment_type"     ,
    "registration_update_competence",
    "candidate_list"                ,
    "eligibility_status"            ,
    "eligibility_basis"             ,
    "requires_site_validation"      ,
})
COUNT_COLUMNS = (
    "surgical_beds"  ,
    "operating_rooms",
    "recovery_rooms" ,
    "adult_icu_beds" ,
)
MUNICIPAL_COUNT_COLUMNS = (
    "candidate_establishments" ,
    "sus_linked_establishments",
    "operating_rooms"          ,
    "adult_icu_beds"           ,
)
BOOLEAN_COLUMNS = (
    "is_sus_linked"               ,
    "has_hospital_high_complexity",
    "has_hospital_beds"           ,
    "has_hospital_care"           ,
    "has_surgical_center"         ,

    *(
        f"has_hospital_{name}_service"
        for name in SUPPORT_SERVICE_CODES
    ),

    "is_legacy_hospital_type"            ,
    "has_surgical_beds"                  ,
    "has_operating_room"                 ,
    "has_recovery_room"                  ,
    "has_adult_icu"                      ,
    "passes_cnes_telesurgery_host_screen",
)

COLUMN_DICTIONARY = {
    "cnes"                   : "Identificador textual do estabelecimento CNES, 7 dígitos."                                 ,
    "ibge_municipality_code" : "Código municipal IBGE textual, 7 dígitos, correspondido pelo prefixo DATASUS de 6 dígitos.",
    "municipality"           : "Nome municipal na referência IBGE utilizada."                                              ,
    "state"                  : "Sigla da unidade da federação, consistente com o prefixo IBGE."                            ,

    "legacy_establishment_type_code"      : "Tipo legado TP_UNID, texto com 2 dígitos; descrições no dicionário de tipos.",
    "is_sus_linked"                       : "VINC_SUS=1; informativo, não elimina candidatos."                            ,
    "has_hospital_high_complexity"        : "GESPRG6E=1 ou GESPRG6M=1; seleção do padrão e restrito."                     ,
    "has_hospital_beds"                   : "LEITHOSP=1; seleção do restrito."                                            ,
    "surgical_beds"                       : "QTLEITP1: quantidade de leitos cirúrgicos, inteiro não negativo."            ,
    "has_hospital_care"                   : "ATENDHOS=1; seleção do restrito."                                            ,
    "has_surgical_center"                 : "CENTRCIR=1; seleção do restrito."                                            ,
    "operating_rooms"                     : "QTINST31: salas cirúrgicas; soma por município nas agregações."              ,
    "recovery_rooms"                      : "QTINST32: salas de recuperação, inteiro não negativo."                       ,
    "adult_icu_beds"                      : "Soma QT_EXIST dos códigos LT 61,74,75,76; soma por município nas agregações.",
    "is_legacy_hospital_type"             : "TP_UNID em 05,07; seleção do amplo, padrão e restrito."                      ,
    "has_surgical_beds"                   : "surgical_beds > 0; seleção do restrito."                                     ,
    "has_operating_room"                  : "operating_rooms > 0; seleção do restrito."                                   ,
    "has_recovery_room"                   : "recovery_rooms > 0; seleção do restrito."                                    ,
    "has_adult_icu"                       : "adult_icu_beds > 0; seleção do restrito."                                    ,
    "passes_cnes_telesurgery_host_screen" : "Conjunção dos 12 critérios observáveis; não comprova aptidão operacional."   ,
    "candidate_establishments"            : "Quantidade de estabelecimentos distintos da respectiva lista no município."  ,
    "sus_linked_establishments"           : "Quantidade dos candidatos do município com VINC_SUS=1; informativo."         ,
}

for _name, _code in SUPPORT_SERVICE_CODES.items():
    COLUMN_DICTIONARY[f"has_hospital_{_name}_service"] = (
        f"SERV_ESP={_code} e (HOSP_NSUS=1 ou HOSP_SUS=1); " + (
            "informativo, não elimina candidatos."

            if   _name in {
                "urology"         ,
                "videolaparoscopy",
            }
            else "seleção do restrito."
        )
    )


@dataclass
class Screen:
    all_establishments: pd.DataFrame
    candidates        : dict[str, pd.DataFrame]
    municipalities    : dict[str, pd.DataFrame]
    type_review       : pd.DataFrame
    funnel            : pd.DataFrame
    quality_checks    : pd.DataFrame


def normalize_code(series: pd.Series, width: int, name: str) -> pd.Series:
    """Normalize identifiers without losing leading zeros or accepting fractions"""

    result = (
        series
        .astype ("string")
        .str
        .strip  ()
        .str
        .replace(r"\.0$", "", regex=True)
    )

    if not result.str.fullmatch(rf"[0-9]{{1,{width}}}", na=False).all():
        raise ValueError(f"Invalid {name}: expected up to {width} decimal digits")

    return result.str.zfill(width)


def nonnegative_integers(series: pd.Series, name: str) -> pd.Series:
    """Reject missing, negative and fractional counts instead of repairing them"""

    values = pd.to_numeric(series, errors="raise")

    if values.isna().any() or (values < 0).any() or (values % 1 != 0).any():
        raise ValueError(f"Invalid {name}: counts must be nonnegative integers")

    return values.astype("int64")


def validate_source_competence(
    frame      : pd.DataFrame    ,
    group      : str             ,
    competence : str = COMPETENCE,
) -> None:
    missing = set(SOURCE_COLUMNS[group]) - set(frame.columns)

    if missing:
        raise ValueError(f"Missing {group} columns: {sorted(missing)}")

    if not frame["COMPETEN"].astype("string").str.strip().eq(competence).fillna(False).all():
        raise ValueError(f"{group} source competence must be {competence}")


def _derived_flags(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()

    result["is_legacy_hospital_type"] = result["legacy_establishment_type_code"].isin(LEGACY_HOSPITAL_TYPE_CODES)

    for count, flag in (
        ("surgical_beds"  , "has_surgical_beds" ),
        ("operating_rooms", "has_operating_room"),
        ("recovery_rooms" , "has_recovery_room" ),
        ("adult_icu_beds" , "has_adult_icu"     ),
    ):
        result[flag] = result[count].gt(0)

    result["passes_cnes_telesurgery_host_screen"] = result[
        [
            column
            for _, column in ELIGIBILITY_CHECKS
        ]
    ].all(axis=1)

    return result


def build_establishments(
    st             : pd.DataFrame,
    lt             : pd.DataFrame,
    sr             : pd.DataFrame,
    municipalities : pd.DataFrame,

    competence     : str = COMPETENCE,
) -> pd.DataFrame:
    """Join ST identity/capabilities, LT adult ICU and SR hospital services"""

    if competence != COMPETENCE:
        raise ValueError(f"This pipeline is fixed to {COMPETENCE}")

    for group, frame in (
        ("ST", st),
        ("LT", lt),
        ("SR", sr),
    ):
        validate_source_competence(frame, group, competence)

    data = st.loc[:, list(SOURCE_COLUMNS["ST"])].copy()
    if data.empty:
        raise ValueError("Empty ST establishment base")

    data["CNES"    ] = normalize_code(data["CNES"    ], 7, "ST.CNES"    )
    data["CODUFMUN"] = normalize_code(data["CODUFMUN"], 6, "ST.CODUFMUN")
    data["TP_UNID" ] = normalize_code(data["TP_UNID" ], 2, "ST.TP_UNID" )

    data = data.drop_duplicates()
    if not data["CNES"].is_unique:
        raise ValueError("Conflicting duplicate ST records for the same CNES")

    data = data.reset_index(drop=True)

    reference = municipalities[
        [
            "ibge_municipality_code",
            "municipality"          ,
            "state"                 ,
        ]
    ].copy()

    reference["ibge_municipality_code"] = normalize_code(reference["ibge_municipality_code"], 7, "IBGE municipality")
    reference["CODUFMUN"              ] = reference               ["ibge_municipality_code"].str[:6]

    if not reference["CODUFMUN"].is_unique:
        raise ValueError("Ambiguous DATASUS-to-IBGE municipality reference")

    if not reference["state"].eq(reference["ibge_municipality_code"].str[:2].map(STATE_BY_PREFIX)).fillna(False).all():
        raise ValueError("Municipal reference state disagrees with the IBGE code")

    result = pd.DataFrame(
        {
            "cnes"                           : data["CNES"    ],
            "CODUFMUN"                       : data["CODUFMUN"],
            "legacy_establishment_type_code" : data["TP_UNID" ],

            "is_sus_linked"                : data["VINC_SUS"].astype("string").str.strip().eq("1"),
            "has_hospital_high_complexity" : data[["GESPRG6E", "GESPRG6M"]].astype("string").apply(lambda s: s.str.strip()).eq("1").any(axis=1),
            "has_hospital_beds"            : data["LEITHOSP"].astype("string").str.strip().eq("1"),
            "has_hospital_care"            : data["ATENDHOS"].astype("string").str.strip().eq("1"),
            "has_surgical_center"          : data["CENTRCIR"].astype("string").str.strip().eq("1"),

            "surgical_beds"   : nonnegative_integers(data["QTLEITP1"], "ST.QTLEITP1"),
            "operating_rooms" : nonnegative_integers(data["QTINST31"], "ST.QTINST31"),
            "recovery_rooms"  : nonnegative_integers(data["QTINST32"], "ST.QTINST32"),
        }
    ).merge(
        reference,

        on      ="CODUFMUN"   ,
        how     ="left"       ,
        validate="many_to_one",
    )

    if result["ibge_municipality_code"].isna().any():
        missing = sorted(
            result.loc[result["ibge_municipality_code"].isna(), "CODUFMUN"].unique()
        )

        raise ValueError(f"DATASUS municipalities absent from IBGE reference: {missing}")

    result = result.drop(columns="CODUFMUN")
    beds   = lt    .copy()

    beds["cnes"] = normalize_code(beds["CNES"], 7, "LT.CNES")

    if not beds["cnes"].isin(result["cnes"]).all():
        raise ValueError("LT contains CNES identifiers absent from ST")

    beds["CODLEITO"] = normalize_code      (beds["CODLEITO"], 2, "LT.CODLEITO")
    beds["QT_EXIST"] = nonnegative_integers(beds["QT_EXIST"],    "LT.QT_EXIST")

    adult_beds = beds.loc[
        beds["CODLEITO"].isin(ADULT_ICU_BED_CODES)
    ].groupby("cnes")["QT_EXIST"].sum()

    result["adult_icu_beds"] = result["cnes"].map(adult_beds).fillna(0).astype("int64")

    services = sr.copy()

    services["cnes"] = normalize_code(services["CNES"], 7, "SR.CNES")
    if not services["cnes"].isin(result["cnes"]).all():
        raise ValueError("SR contains CNES identifiers absent from ST")

    services["SERV_ESP"] = normalize_code(services["SERV_ESP"], 3, "SR.SERV_ESP")

    hospital = (
        services[
            [
                "HOSP_NSUS",
                "HOSP_SUS" ,
            ]
        ]
        .astype("string"               )
        .apply (lambda s: s.str.strip())
        .eq    ("1"                    )
        .any   (axis=1                 )
    )

    for name, code in SUPPORT_SERVICE_CODES.items():
        present = services.loc[hospital & services["SERV_ESP"].eq(code), "cnes"]

        result[f"has_hospital_{name}_service"] = result["cnes"].isin(present)

    result = _derived_flags(result).sort_values(
        [
            "state"       ,
            "municipality",
            "cnes"        ,
        ]
    ).reset_index(drop=True)

    validate_establishments(result)

    return result


def validate_establishments(frame: pd.DataFrame) -> None:
    """Enforce exported identifiers, flags, counts and municipal consistency"""

    required = {
        "cnes"                          ,
        "ibge_municipality_code"        ,
        "municipality"                  ,
        "state"                         ,
        "legacy_establishment_type_code",

        *COUNT_COLUMNS  ,
        *BOOLEAN_COLUMNS,
    }
    if required - set(frame.columns):
        raise ValueError(f"Missing establishment columns: {sorted(required - set(frame.columns))}")

    forbidden = REMOVED_COLUMNS & set(frame.columns)
    if forbidden:
        raise ValueError(f"Removed columns cannot be exported: {sorted(forbidden)}")

    if not frame["cnes"].is_unique:
        raise ValueError("Duplicate CNES identifiers")

    for column, width in (
        ("cnes"                          , 7),
        ("ibge_municipality_code"        , 7),
        ("legacy_establishment_type_code", 2),
    ):
        if (
            not all(isinstance(value, str) for value in frame[column])            or
            not frame[column].str.fullmatch(rf"[0-9]{{{width}}}", na=False).all()
        ):
            raise ValueError(f"Invalid textual identifier: {column}")

    for column in COUNT_COLUMNS:
        if not pd.api.types.is_integer_dtype(frame[column]):
            raise ValueError(f"Count column must use an integer dtype: {column}")

        if frame[column].isna().any() or frame[column].lt(0).any():
            raise ValueError(f"Invalid {column}: counts must be nonnegative integers")

    for column in BOOLEAN_COLUMNS:
        if frame[column].isna().any() or not pd.api.types.is_bool_dtype(frame[column]):
            raise ValueError(f"Flag column must be boolean without missing values: {column}")

    if not frame["state"].eq(frame["ibge_municipality_code"].str[:2].map(STATE_BY_PREFIX)).fillna(False).all():
        raise ValueError("Establishment state disagrees with the IBGE code")

    if frame["municipality"].isna().any() or frame["municipality"].astype("string").str.strip().eq("").any():
        raise ValueError("Missing municipality labels")

    labels = frame.groupby("ibge_municipality_code")[["municipality", "state"]].nunique()
    if labels.gt(1).any(axis=None):
        raise ValueError("Municipality code maps to conflicting labels")

    derived = _derived_flags(frame)
    for column in (
        "is_legacy_hospital_type"            ,
        "has_surgical_beds"                  ,
        "has_operating_room"                 ,
        "has_recovery_room"                  ,
        "has_adult_icu"                      ,
        "passes_cnes_telesurgery_host_screen",
    ):
        if not frame[column].eq(derived[column]).all():
            raise ValueError(f"Derived flag disagrees with recorded attributes: {column}")


def aggregate_municipalities(candidates: pd.DataFrame) -> pd.DataFrame:
    """One row per municipality, preserving the original aggregate attributes"""

    validate_establishments(candidates)

    return _aggregate_municipalities(candidates)


def _aggregate_municipalities(candidates: pd.DataFrame) -> pd.DataFrame:
    """Aggregate candidates whose establishment contract has already been checked"""

    result = candidates.groupby(
        [
            "ibge_municipality_code",
            "municipality"          ,
            "state"                 ,
        ],

        as_index=False,
    ).agg(
        candidate_establishments =("cnes"           , "nunique"),
        sus_linked_establishments=("is_sus_linked"  , "sum"    ),
        operating_rooms          =("operating_rooms", "sum"    ),
        adult_icu_beds           =("adult_icu_beds" , "sum"    ),
    )

    result[list(MUNICIPAL_COUNT_COLUMNS)] = result[list(MUNICIPAL_COUNT_COLUMNS)].astype("int64")

    return result.sort_values(
        [
            "candidate_establishments",
            "state"                   ,
            "municipality"            ,
        ],

        ascending=[False, True, True],
    ).reset_index(drop=True)


def validate_municipalities(frame: pd.DataFrame) -> None:
    """Enforce the municipal CSV contract independently of candidate rows"""

    required = {
        "ibge_municipality_code",
        "municipality"          ,
        "state"                 ,

        *MUNICIPAL_COUNT_COLUMNS,
    }

    if required - set(frame.columns):
        raise ValueError(f"Missing municipal columns: {sorted(required - set(frame.columns))}")

    if REMOVED_COLUMNS & set(frame.columns):
        raise ValueError("Removed columns cannot be exported in municipal products")

    code = frame["ibge_municipality_code"]

    if not code.is_unique or not all(isinstance(value, str) for value in code) or not code.str.fullmatch(r"[0-9]{7}", na=False).all():
        raise ValueError("Invalid or duplicate textual IBGE municipality identifiers")

    if not frame["state"].eq(code.str[:2].map(STATE_BY_PREFIX)).fillna(False).all():
        raise ValueError("Municipal state disagrees with the IBGE code")

    if frame["municipality"].isna().any() or frame["municipality"].astype("string").str.strip().eq("").any():
        raise ValueError("Missing municipality labels")

    for column in MUNICIPAL_COUNT_COLUMNS:
        if not pd.api.types.is_integer_dtype(frame[column]):
            raise ValueError(f"Count column must use an integer dtype: {column}")

        if frame[column].isna().any() or frame[column].lt(0).any():
            raise ValueError(f"Invalid {column}: counts must be nonnegative integers")

    if frame["candidate_establishments"].eq(0).any():
        raise ValueError("Municipal products include only municipalities with candidates")

    if frame["sus_linked_establishments"].gt(frame["candidate_establishments"]).any():
        raise ValueError("SUS-linked establishments exceed candidate establishments")


def type_review(frame: pd.DataFrame) -> pd.DataFrame:
    counts = frame["legacy_establishment_type_code"].value_counts()

    return pd.DataFrame([
        {
            "legacy_type_code"  : code                                                         ,
            "legacy_type_label" : LEGACY_TYPE_LABELS.get(code, f"Tipo não catalogado ({code})"),

            "type_screening_decision" : (
                "candidato amplo"
                if   code in LEGACY_HOSPITAL_TYPE_CODES
                else "excluído"
            ),
            "rationale"               : (
                "Tipo hospitalar aceito; padrão exige alta complexidade e restrito exige todos os critérios observáveis."
                if   code in LEGACY_HOSPITAL_TYPE_CODES
                else "Tipo legado fora de 05/07; não atende à definição conservadora de hospital do conjunto amplo."
            ),

            "observed_establishments" : int(counts.get(code, 0)),
        }
        for code in sorted(set(LEGACY_TYPE_LABELS) | set(counts.index))
    ])


def validate_products(
    base          : pd.DataFrame,
    candidates    : dict[str, pd.DataFrame],
    municipalities: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Check exact screening membership, nested subsets and municipal totals"""

    validate_establishments(base)

    expected_masks = {
        "broad"      : base["is_legacy_hospital_type"            ],
        "candidates" : base["is_legacy_hospital_type"            ] & base["has_hospital_high_complexity"],
        "restricted" : base["passes_cnes_telesurgery_host_screen"],
    }

    if set(candidates) != set(expected_masks) or set(municipalities) != set(expected_masks):
        raise ValueError("Expected exactly broad, candidates and restricted products")

    rows = [
        {
            "check"  : "Base: identificadores, contagens, atributos e municípios consistentes",
            "passed" : True,
        }
    ]

    for level, mask in expected_masks.items():
        actual, municipal = candidates[level], municipalities[level]

        validate_establishments(actual   )
        validate_municipalities(municipal)

        expected = base.loc[mask].reset_index(drop=True)

        pd.testing.assert_frame_equal(
            actual.reset_index(drop=True),
            expected                     ,

            check_dtype=False,
        )

        pd.testing.assert_frame_equal(
            municipal                        ,
            _aggregate_municipalities(actual),

            check_dtype=False,
        )

        if int(municipal["candidate_establishments"].sum()) != len(actual):
            raise ValueError(f"Municipal counts do not reconcile: {level}")

        rows.append(
            {
                "check"  : f"{level}: CNES únicos, seleção exata, subconjunto e totais municipais reconciliados",
                "passed" : True,
            }
        )

    return pd.DataFrame(rows)


def screen_candidates(base: pd.DataFrame) -> Screen:
    """Recompute all derived flags, candidate lists, municipal totals and funnel"""

    base = _derived_flags(base).reset_index(drop=True)

    validate_establishments(base)

    masks = {
        "broad"      : base["is_legacy_hospital_type"            ],
        "candidates" : base["is_legacy_hospital_type"            ] & base["has_hospital_high_complexity"],
        "restricted" : base["passes_cnes_telesurgery_host_screen"],
    }

    candidates     = {level : base.loc[mask].reset_index(drop=True) for level, mask  in masks     .items()}
    municipalities = {level : _aggregate_municipalities (frame    ) for level, frame in candidates.items()}

    remaining = pd.Series(True, index=base.index)

    funnel = [
        {
            "step"                     : 0                          ,
            "criterion"                : "Todos os estabelecimentos",
            "remaining_establishments" : len(base)                  ,
        }
    ]

    for step, (label, column) in enumerate(ELIGIBILITY_CHECKS, start=1):
        remaining &= base[column]

        funnel.append(
            {
                "step"                     : step ,
                "criterion"                : label,
                "remaining_establishments" : int(remaining.sum()),
            }
        )

    return Screen(
        base          ,
        candidates    ,
        municipalities,

        type_review      (base  ),
        pd.DataFrame     (funnel),
        validate_products(base, candidates, municipalities),
    )


def read_establishments_csv(path: Path) -> pd.DataFrame:
    """Read processed CSV explicitly; reject malformed boolean/count values"""

    frame = pd.read_csv(path, dtype="string", keep_default_na=False)

    for column in BOOLEAN_COLUMNS:
        if column not in frame or not frame[column].isin(["True", "False"]).all():
            raise ValueError(f"Invalid or missing boolean column: {column}")

        frame[column] = frame[column].eq("True")

    for column in COUNT_COLUMNS:
        if column not in frame:
            raise ValueError(f"Missing count column: {column}")

        frame[column] = nonnegative_integers(frame[column], column)

    validate_establishments(frame)

    return frame


def read_municipalities_csv(path: Path) -> pd.DataFrame:
    """Read final municipal CSV using textual identifiers and integer counts"""

    frame = pd.read_csv(path, dtype="string", keep_default_na=False)

    for column in MUNICIPAL_COUNT_COLUMNS:
        if column not in frame:
            raise ValueError(f"Missing municipal count column: {column}")

        frame[column] = nonnegative_integers(frame[column], column)

    validate_municipalities(frame)

    return frame
