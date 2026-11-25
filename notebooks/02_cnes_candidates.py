import marimo

__generated_with = "0.25.2"
app = marimo.App(width="full")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # TELESURGERY CANDIDATE MUNICIPALITIES · CNES
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **Brazil · June 2026 (202606) · ST, LT and SR for all 27 federative units.**

    This notebook combines data acquisition, screening, municipal aggregation and maps.
    """)
    return


@app.cell
def _():
    import os
    import sys
    import json

    from pathlib import Path

    import pandas as pd
    import marimo as mo


    root = Path(__file__).resolve().parents[1]

    os.environ.setdefault("MPLCONFIGDIR", str(root / ".cache" / "matplotlib"))
    os.environ.setdefault("MPLBACKEND"  , "Agg"                              )

    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from src.cnes_pipeline import run_screen
    from src.visualization import (
        build_candidate_maps        ,
        export_candidate_maps       ,
        load_geographic_meshes      ,
        validate_geographic_coverage,
    )

    timeout_seconds = 90
    return (
        build_candidate_maps,
        export_candidate_maps,
        json,
        load_geographic_meshes,
        mo,
        pd,
        root,
        run_screen,
        timeout_seconds,
        validate_geographic_coverage,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## DATA ACQUISITION AND SCREENING CRITERIA
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    The workflow verifies coverage of all **81 official files** before processing. Each file is checked for `COMPETEN=202606` before that column is removed.

    | Candidate set | Definition |
    |:--|:--|
    | Broad | Legacy `TP_UNID` types 05 (General hospital) and 07 (Specialized hospital). |
    | Standard | Broad set with registered high-complexity hospital care: `GESPRG6E=1` or `GESPRG6M=1`. |
    | Restricted | Standard set meeting all observable criteria in the funnel below. |

    The restricted set requires hospital care and beds, a surgical center, operating and recovery rooms, surgical beds and adult ICU beds (LT 61/74/75/76), as well as diagnostic imaging (SR 121), clinical laboratory (145) and hemotherapy (128) services explicitly linked to hospital care (`HOSP_NSUS=1` or `HOSP_SUS=1`).
    """)
    return


@app.cell
def _(root, run_screen, timeout_seconds):
    screen, metadata = run_screen(root, timeout=timeout_seconds)
    return metadata, screen


@app.cell(hide_code=True)
def _(json, metadata, mo, pd, root):
    _manifest = root / ".cache" / "cnes" / metadata["competence"] / "enriched_manifest.json"

    _files = pd.DataFrame(
        json.loads(
            _manifest.read_text(encoding="utf-8")
        )["files"]
    )

    _coverage = _files.groupby(
        "group",

        as_index=False,
    ).agg(
        files           =("file"                , "count"  ),
        federative_units=("state"               , "nunique"),
        reference_period=("validated_competence", "first"  ),
        records         =("rows"                , "sum"    ),
    )

    mo.vstack([
        mo.md  ("### SOURCE COVERAGE"),

        mo.Html(_coverage.to_html(index=False, border=0)),
    ])
    return


@app.cell(hide_code=True)
def _(metadata, mo, pd):
    _counts = pd.DataFrame.from_dict(
        metadata["counts"],

        orient="index",
    ).rename(
        index={
            "base"       : "All establishments",
            "broad"      : "Broad"             ,
            "candidates" : "Standard"          ,
            "restricted" : "Restricted"        ,
        }
    ).rename_axis("candidate_set").reset_index()

    mo.vstack([
        mo.md  ("## ESTABLISHMENTS AND MUNICIPALITIES"),

        mo.Html(_counts.to_html(index=False, border=0)),
    ])
    return


@app.cell(hide_code=True)
def _(mo, screen):
    mo.vstack([
        mo.md  ("### COMPLETE LEGACY TYPE REVIEW"),

        mo.Html(
            screen.type_review.to_html(index=False, border=0, max_rows=None, max_cols=None, escape=True)
        ),
    ])
    return


@app.cell
def _(mo, screen):
    mo.vstack([
        mo.md  ("### SELECTION FUNNEL"),

        mo.Html(screen.funnel.to_html(index=False, border=0)),
    ])
    return


@app.cell(hide_code=True)
def _(mo, screen):
    mo.vstack([
        mo.md  ("## QUALITY CHECKS"),

        mo.Html(screen.quality_checks.to_html(index=False, border=0)),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## MUNICIPAL PRESENCE OF CANDIDATES
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Each point indicates at least one candidate in the municipality. All three maps use the same extent and a fixed marker size; marker size does not represent capacity. Points are municipal centroids calculated in **EPSG:5880**, rather than establishment addresses. Boundaries are supplied by IBGE; their reference date is independent of the CNES reference period.
    """)
    return


@app.cell
def _(
    build_candidate_maps,
    export_candidate_maps,
    load_geographic_meshes,
    root,
    screen,
    timeout_seconds,
    validate_geographic_coverage,
):
    boundaries, states, _geography_provenance = load_geographic_meshes(root, timeout_seconds)

    geographic_checks = validate_geographic_coverage(boundaries           , screen.municipalities)
    figures           = build_candidate_maps        (screen.municipalities, boundaries, states   )

    export_candidate_maps(figures, root / "docs")
    return figures, geographic_checks


@app.cell(hide_code=True)
def _(geographic_checks, mo):
    mo.Html(geographic_checks.to_html(index=False, border=0))
    return


@app.cell(hide_code=True)
def _(figures):
    figures["broad"]
    return


@app.cell(hide_code=True)
def _(figures):
    figures["candidates"]
    return


@app.cell(hide_code=True)
def _(figures):
    figures["restricted"]
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## OUTPUTS AND REPRODUCTION
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    The six final CSV files are saved in `data/`: three establishment candidate lists and three municipal aggregates. The complete enriched base is saved exclusively at `.cache/cnes/202606/cnes_establishments_brazil_202606.csv`, which Git ignores.

    The reference period appears in filenames and in `metadata/cnes_candidates_202606.json`, which contains the source, criteria, column dictionary, descriptions of types 05 and 07, counts and final output paths. The three maps are saved exclusively as PDFs in `docs/`, with embedded TrueType fonts and tight bounding boxes.
    """)
    return


if __name__ == "__main__":
    app.run()
