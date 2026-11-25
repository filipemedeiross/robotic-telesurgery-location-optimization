"""Run the fixed CNES workflow and publish validated CSV/JSON products"""

from __future__ import annotations

import json

import pandas as pd

from pathlib    import Path
from contextlib import ExitStack
from datetime   import datetime, timezone

from .utils            import staged_path
from .cnes_acquisition import (
    COMPETENCE,
    STATES    ,

    acquire_groups       ,
    load_municipalities  ,
    sha256               ,
    validate_source_proof,
)
from .cnes_selection import (
    COLUMN_DICTIONARY  ,
    ELIGIBILITY_CHECKS ,
    LEGACY_TYPE_LABELS ,
    LIST_DEFINITIONS   ,
    MUNICIPAL_SCENARIOS,

    Screen,

    build_establishments                ,
    consolidate_candidate_establishments,
    consolidate_candidate_municipalities,
    read_candidate_establishments_csv   ,
    read_candidate_municipalities_csv   ,
    read_establishments_csv             ,
    screen_candidates                   ,

    validate_candidate_establishments,
    validate_candidate_municipalities,
    validate_products                ,
    _validate_product_relations      ,
)


SCHEMA_VERSION      = 2
BASE_SCHEMA_VERSION = 1

REFERENCES = {
    "type_labels"          : "https://tabnet.datasus.gov.br/cgi/cnes/tipo_estabelecimento.htm"                             ,
    "official_type_domain" : "ftp://ftp.datasus.gov.br/dissemin/publicos/CNES/200508_/Auxiliar/TAB_CNES.zip (TP_ESTAB.CNV)",
}


def product_paths(root: Path) -> dict:
    paths = {
        "establishments" : root / "data" / f"cnes_telesurgery_host_candidates_brazil_{COMPETENCE}.csv"         ,
        "municipalities" : root / "data" / f"cnes_telesurgery_candidate_municipalities_brazil_{COMPETENCE}.csv",
    }

    paths["base"    ] = root / ".cache"   / "cnes" / COMPETENCE / f"cnes_establishments_brazil_{COMPETENCE}.csv"
    paths["metadata"] = root / "metadata" / "cnes_candidates.json"

    return paths


def _selection_digest() -> str:
    return sha256(Path(__file__).with_name("cnes_selection.py"))


def load_base(root: Path, timeout: float = 90) -> tuple[pd.DataFrame, dict]:
    """Use enriched CSV only with matching schema, digest and 81-source proof"""

    paths = product_paths(root)

    manifest_path = paths["base"].parent / "enriched_manifest.json"

    if paths["base"].exists() and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        if (
            manifest.get("schema_version"  ) == BASE_SCHEMA_VERSION   and
            manifest.get("competence"      ) == COMPETENCE            and
            manifest.get("selection_sha256") == _selection_digest()   and
            manifest.get("base_sha256"     ) == sha256(paths["base"])
        ):
            validate_source_proof(manifest["files"])

            base = read_establishments_csv(paths["base"])

            if set(base["state"]) != set(STATES):
                raise ValueError("Enriched cache does not cover the 27 UFs")

            print("Reusing validated enriched CNES 202606 CSV cache.", flush=True)

            return base, manifest

        print("Incompatible enriched cache; rebuilding from checked CNES 202606 sources.", flush=True)

    groups        , manifest         = acquire_groups     (root, timeout)
    municipalities, municipal_source = load_municipalities(root, timeout)

    base = build_establishments(
        groups["ST"]  ,
        groups["LT"]  ,
        groups["SR"]  ,
        municipalities,
    )

    if set(base["state"]) != set(STATES):
        raise ValueError("CNES establishment base does not cover the 27 UFs")

    manifest.update(
        schema_version        =BASE_SCHEMA_VERSION,
        competence            =COMPETENCE         ,
        selection_sha256      =_selection_digest(),
        municipality_reference=municipal_source   ,
    )

    return base, manifest


def build_metadata(root: Path, screen: Screen) -> dict:
    paths = product_paths(root)

    published_columns = set(
        consolidate_candidate_establishments(screen.candidates    ).columns
    )
    published_columns.update(
        consolidate_candidate_municipalities(screen.municipalities).columns
    )

    return {
        "schema_version" : SCHEMA_VERSION,
        "competence"     : COMPETENCE    ,
        "references"     : REFERENCES    ,

        "source"         : "Cadastro Nacional de Estabelecimentos de Saúde (CNES/DATASUS), arquivos ST/LT/SR",
        "created_at_utc" : datetime.now(timezone.utc).isoformat()                                            ,

        "criteria" : {
            "lists" : LIST_DEFINITIONS,

            "establishment_scenarios" : {
                "broad"      : "Todas as linhas do arquivo único de estabelecimentos."            ,
                "candidates" : "is_standard_candidate=True; inclui os estabelecimentos restritos.",
                "restricted" : "is_restricted_candidate=True; implica is_standard_candidate=True.",
                "broad_only" : "is_standard_candidate=False e is_restricted_candidate=False."     ,
            },

            "municipality_scenarios" : {
                "column" : "scenario",
                "values" : {
                    scenario : LIST_DEFINITIONS[level]
                    for level, scenario in MUNICIPAL_SCENARIOS.items()
                },
                "rows" : "Uma linha por município e cenário com candidatos; combinações sem candidatos não são incluídas.",
            },

            "restricted_observable_checks" : [
                {
                    "description" : label ,
                    "column"      : column,
                }
                for label, column in ELIGIBILITY_CHECKS
            ],

            "adult_icu_bed_codes" : [
                "61", "74", "75", "76"
            ],

            "hospital_service_codes" : {
                "121" : "Diagnóstico por imagem",
                "145" : "Laboratório clínico"   ,
                "128" : "Hemoterapia"           ,
            },
            "hospital_service_link"  : "HOSP_NSUS=1 ou HOSP_SUS=1; registros apenas ambulatoriais não satisfazem o critério.",

            "informational_only" : [
                "is_sus_linked"                        ,
                "has_hospital_urology_service"         ,
                "has_hospital_videolaparoscopy_service",
            ],
        },

        "column_dictionary" : {
            column : description
            for column, description in COLUMN_DICTIONARY.items()
            if  column in published_columns
        },

        "legacy_establishment_type_labels" : {
            code : LEGACY_TYPE_LABELS[code]
            for code in ("05", "07")
        },

        "counts": {
            "base" : {
                "establishments" : len(screen.all_establishments)                                   ,
                "municipalities" :     screen.all_establishments["ibge_municipality_code"].nunique(),
            },

            **{
                level : {
                    "establishments" : len(frame                       ),
                    "municipalities" : len(screen.municipalities[level]),
                }
                for level, frame in screen.candidates.items()
            },
        },

        "outputs": {
            "establishments" : paths["establishments"].relative_to(root).as_posix(),
            "municipalities" : paths["municipalities"].relative_to(root).as_posix(),

            "report" : "reports/cnes_candidates.html",
        },
    }


def publish_products(root: Path, screen: Screen, provenance: dict, metadata: dict) -> None:
    """Validate external products and their staged CSV round trips before publishing"""

    validate_products (
        screen.all_establishments,
        screen.candidates        ,
        screen.municipalities    ,
    )

    _publish_products(root, screen, provenance, metadata)


def _publish_products(root: Path, screen: Screen, provenance: dict, metadata: dict) -> None:
    """Publish validated products after checking all staged CSV round trips"""

    paths         = product_paths(root)
    manifest_path = paths["base"].parent / "enriched_manifest.json"

    establishments = consolidate_candidate_establishments(screen.candidates    )
    municipalities = consolidate_candidate_municipalities(screen.municipalities)

    validate_candidate_establishments(establishments)
    validate_candidate_municipalities(municipalities)

    with ExitStack() as stack:
        staged = {}

        for destination, frame in [
            (paths["base"          ], screen.all_establishments),
            (paths["establishments"],            establishments),
            (paths["municipalities"],            municipalities),
        ]:
            temporary = stack.enter_context(staged_path(destination))

            frame.to_csv(temporary, index=False, encoding="utf-8")

            staged[destination] = temporary

        base     = read_establishments_csv          (staged[paths["base"          ]])
        exported = read_candidate_establishments_csv(staged[paths["establishments"]])

        exported_municipalities = read_candidate_municipalities_csv(staged[paths["municipalities"]])

        municipalities_by_level = {
            level : (
                exported_municipalities.loc[
                    exported_municipalities["scenario"].eq(scenario)
                ]
                .drop       (columns="scenario")
                .reset_index(drop   =True      )
            )
            for level, scenario in MUNICIPAL_SCENARIOS.items()
        }

        pd.testing.assert_frame_equal(exported               , establishments, check_dtype=False)
        pd.testing.assert_frame_equal(exported_municipalities, municipalities, check_dtype=False)

        _validate_product_relations(base, screen.candidates, municipalities_by_level)

        provenance = {
            **provenance,

            "base_sha256" : sha256(staged[paths["base"]]),
        }

        for destination, payload in (
            (manifest_path    , provenance),
            (paths["metadata"], metadata  ),
        ):
            temporary = stack.enter_context(staged_path(destination))

            temporary.write_text(
                json.dumps(
                    payload,

                    ensure_ascii=False,
                    indent      =2    ,
                ) + "\n",

                encoding="utf-8",
            )

            staged[destination] = temporary

        for destination, temporary in staged.items():
            temporary.replace(destination)

    for level in ("broad", "restricted"):
        for stem in ("host_candidates", "candidate_municipalities"):
            obsolete = (
                root / "data" / f"cnes_telesurgery_{stem}_{level}_brazil_{COMPETENCE}.csv"
            )

            obsolete.unlink(missing_ok=True)


def run_screen(root: Path, timeout: float = 90) -> tuple[Screen, dict]:
    root = Path(root).resolve()

    base, provenance = load_base(root, timeout)

    validate_source_proof(provenance["files"])

    screen = screen_candidates(base)

    coverage = pd.DataFrame([
        {"check" : "Reference period 202606 validated in all 81 ST/LT/SR source files across the 27 FUs", "passed" : True},
    ])

    screen.quality_checks = pd.concat(
        [
            screen.quality_checks,
            coverage             ,
        ],

        ignore_index=True,
    )

    metadata = build_metadata(root, screen)

    _publish_products(
        root      ,
        screen    ,
        provenance,
        metadata  ,
    )

    return screen, metadata
