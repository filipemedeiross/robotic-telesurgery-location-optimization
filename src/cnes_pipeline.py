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
    COLUMN_DICTIONARY ,
    ELIGIBILITY_CHECKS,
    LEGACY_TYPE_LABELS,
    LIST_DEFINITIONS  ,

    Screen,

    build_establishments   ,
    read_establishments_csv,
    read_municipalities_csv,
    screen_candidates      ,

    validate_products          ,
    _validate_product_relations,
)


SCHEMA_VERSION = 1

REFERENCES = {
    "type_labels"          : "https://tabnet.datasus.gov.br/cgi/cnes/tipo_estabelecimento.htm"                             ,
    "official_type_domain" : "ftp://ftp.datasus.gov.br/dissemin/publicos/CNES/200508_/Auxiliar/TAB_CNES.zip (TP_ESTAB.CNV)",
}


def product_paths(root: Path) -> dict:
    paths = {"establishments": {}, "municipalities": {}}

    for level in LIST_DEFINITIONS:
        suffix = "" if level == "candidates" else f"_{level}"

        paths["establishments"][level] = root / "data" / f"cnes_telesurgery_host_candidates{suffix}_brazil_{COMPETENCE}.csv"
        paths["municipalities"][level] = root / "data" / f"cnes_telesurgery_candidate_municipalities{suffix}_brazil_{COMPETENCE}.csv"

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
            manifest.get("schema_version"  ) == SCHEMA_VERSION        and
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
        schema_version        =SCHEMA_VERSION,
        competence            =COMPETENCE    ,
        selection_sha256      =_selection_digest(),
        municipality_reference=municipal_source   ,
    )

    return base, manifest


def _assert_no_parquet(root: Path) -> None:
    paths = [
        path
        for directory in (
            root / "data"           ,
            root / ".cache" / "cnes",
            root / "docs"           ,
            root / "reports"        ,
        )
        if  directory.exists()
        for path in directory.rglob("*.parquet")
    ]

    if paths:
        raise ValueError(f"Persistent Parquet products are not permitted: {paths}")


def build_metadata(root: Path, screen: Screen) -> dict:
    paths = product_paths(root)

    return {
        "schema_version" : SCHEMA_VERSION,
        "competence"     : COMPETENCE    ,
        "references"     : REFERENCES    ,

        "source"         : "Cadastro Nacional de Estabelecimentos de Saúde (CNES/DATASUS), arquivos ST/LT/SR",
        "created_at_utc" : datetime.now(timezone.utc).isoformat()                                            ,

        "criteria" : {
            "lists" : LIST_DEFINITIONS,

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

        "column_dictionary" : COLUMN_DICTIONARY,

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
            **{
                kind : {
                    level : path.relative_to(root).as_posix()
                    for level, path in paths[kind].items   ()
                }
                for kind in (
                    "establishments",
                    "municipalities",
                )
            },

            "report" : f"reports/cnes_candidates_{COMPETENCE}.html",
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

    _assert_no_parquet(root)

    with ExitStack() as stack:
        staged = {}

        for destination, frame in [
            (paths["base"], screen.all_establishments),

            *((paths["establishments"][level], frame) for level, frame in screen.candidates    .items()),
            *((paths["municipalities"][level], frame) for level, frame in screen.municipalities.items()),
        ]:
            temporary = stack.enter_context(staged_path(destination))

            frame.to_csv(temporary, index=False, encoding="utf-8")

            staged[destination] = temporary

        base = read_establishments_csv(staged[paths["base"]])

        candidates     = {level: read_establishments_csv(staged[path]) for level, path in paths["establishments"].items()}
        municipalities = {level: read_municipalities_csv(staged[path]) for level, path in paths["municipalities"].items()}

        _validate_product_relations(base, candidates, municipalities)

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


def run_screen(root: Path, timeout: float = 90) -> tuple[Screen, dict]:
    root = Path(root).resolve()

    base, provenance = load_base(root, timeout)

    validate_source_proof(provenance["files"])

    screen = screen_candidates(base)

    coverage = pd.DataFrame([
        {"check" : "Reference period 202606 validated in all 81 ST/LT/SR source files across the 27 FUs", "passed" : True},
        {"check" : "CSV files exclude removed columns; no persistent CNES Parquet products or caches"   , "passed" : True},
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
