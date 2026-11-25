"""Official IBGE meshes and comparable CNES municipal presence maps"""

from __future__ import annotations

import gzip
import json
import hashlib

from pathlib        import Path
from urllib.error   import URLError
from urllib.request import Request , urlopen
from datetime       import datetime, timezone
from tempfile       import NamedTemporaryFile

import pandas            as pd
import geopandas         as gpd
import matplotlib.pyplot as plt


COMPETENCE = "202606"
MAP_CRS    = "EPSG:5880"

STATE_CODES = frozenset(
    "11 12 13 14 15 16 17 21 22 23 24 25 26 27 28 29 31 32 33 35 41 42 43 50 51 52 53".split()
)

LEVELS = {
    "broad"      : ("Broad"     , "Legacy types 05 and 07"                                              , "#0072B2"),
    "candidates" : ("Standard"  , "Legacy types 05 and 07 with registered high-complexity hospital care", "#D55E00"),
    "restricted" : ("Restricted", "Standard set meeting all observable criteria"                        , "#087f5b"),
}

STYLE = {
    "font.family"    : "DejaVu Sans",
    "font.size"      : 9 ,
    "pdf.fonttype"   : 42,
    "axes.titlesize" : 10,

    "text.color" : "#172534",

    "figure.facecolor"  : "white",
    "axes.facecolor"    : "white",
    "savefig.facecolor" : "white",
}

MESHES = {
    "municipio" : ("malha_municipios_brasil_minima.geojson", 7),
    "UF"        : ("malha_estados_brasil_minima.geojson"   , 2),
}


def _mesh_url(level: str) -> str:
    return (
        "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR"
        "?formato=application/vnd.geo%2Bjson&qualidade=minima"
        f"&intrarregiao={level}"
    )


def _parse_mesh(raw: bytes, level: str) -> gpd.GeoDataFrame:
    """Validate codes, nationwide coverage and geometry before cache publication"""

    if raw.startswith(b"\x1f\x8b"):
        raw = gzip.decompress(raw)

    payload = json.loads(raw.decode("utf-8-sig"))

    if payload.get("type") != "FeatureCollection" or not payload.get("features"):
        raise ValueError("IBGE mesh must be a nonempty FeatureCollection.")

    mesh = gpd.GeoDataFrame.from_features(payload["features"], crs="EPSG:4674")

    if "codarea" not in mesh:
        raise ValueError("IBGE mesh has no codarea identifiers.")

    mesh["codarea"] = mesh["codarea"].astype("string").str.strip()

    digits = MESHES[level][1]
    if not mesh["codarea"].str.fullmatch(rf"[0-9]{{{digits}}}", na=False).all():
        raise ValueError("IBGE mesh contains malformed territorial codes.")

    mesh = mesh.set_index("codarea", verify_integrity=True)

    if set(mesh.index.str[:2]) != STATE_CODES:
        raise ValueError("IBGE mesh does not cover the 27 federative units.")

    if level == "municipio" and len(mesh) < 5_500:
        raise ValueError("IBGE municipal mesh has incomplete national coverage.")

    if mesh.geometry.isna().any() or mesh.geometry.is_empty.any():
        raise ValueError("IBGE mesh contains missing or empty geometries.")

    invalid        = ~mesh.geometry      .is_valid
    repaired_codes =  mesh.index[invalid].tolist()

    mesh.loc[invalid, "geometry"] = mesh.loc[invalid, "geometry"].make_valid()

    if not mesh.geometry.is_valid.all() or mesh.geometry.is_empty.any():
        raise ValueError("IBGE geometry remains invalid after make_valid.")

    mesh = mesh.to_crs(MAP_CRS).sort_index()

    mesh.attrs["repaired_geometry_codes"] = repaired_codes

    return mesh


def load_geographic_meshes(root: Path, timeout: float = 120) -> tuple:
    """Reuse validated project cache or retrieve IBGE GeoJSON with a timeout"""

    cache = Path(root) / ".cache" / "ibge"

    cache.mkdir(parents=True, exist_ok=True)

    meshes, provenance = {}, {}
    for level, (filename, _) in MESHES.items():
        path   = cache / filename
        source = "cache" if path.exists() else "IBGE download"

        if path.exists():
            raw  = path.read_bytes()
            mesh = _parse_mesh    (raw, level)
        else:
            url = _mesh_url(level)

            request = Request(
                url,

                headers={
                    "User-Agent" : "cnes-candidates/202606",
                }
            )

            try:
                with urlopen(request, timeout=timeout) as response:
                    raw = response.read()
            except (URLError, TimeoutError, OSError) as error:
                raise RuntimeError(f"Could not retrieve IBGE {level} mesh: {url}: {error}") from error

            mesh = _parse_mesh(raw, level)

            with NamedTemporaryFile(
                dir   =cache          ,
                prefix=f".{filename}.",
                delete=False          ,
            ) as temporary:
                staged = Path(temporary.name)

                temporary.write  (raw )
            try:
                staged   .replace(path)
            finally:
                staged.unlink(missing_ok=True)

        meshes    [level] = mesh
        provenance[level] = {
            "url" : _mesh_url(level),

            "cache_path" : path   .relative_to(root).as_posix (),
            "sha256"     : hashlib.sha256     (raw ).hexdigest(),

            "bytes"       : len(raw ),
            "features"    : len(mesh),
            "loaded_from" : source,

            "cache_file_modified_at_utc" : datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            "loaded_at_utc"              : datetime.now          (timezone.utc                      ).isoformat(),

            "input_crs"       : "EPSG:4674",
            "map_crs"         : MAP_CRS    ,
            "marker_location" : "Municipal geometry centroid computed in EPSG:5880"                     ,
            "geometry_repair" : "GeoPandas make_valid on invalid features only; original bytes retained",

            "repaired_geometry_codes" : mesh.attrs["repaired_geometry_codes"],
        }

    return meshes["municipio"], meshes["UF"], provenance


def validate_geographic_coverage(
    boundaries              : gpd.GeoDataFrame       ,
    municipalities_by_level : dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Require one valid municipal key and a geometry for every exported row"""

    if not boundaries.index.is_unique or boundaries.crs != MAP_CRS:
        raise ValueError("Municipal mesh needs unique codes and EPSG:5880.")

    rows = []
    for level, frame in municipalities_by_level.items():
        if level not in LEVELS:
            raise ValueError(f"Unknown candidate level: {level}")

        codes = frame["ibge_municipality_code"]

        if not all(isinstance(value, str) for value in codes):
            raise ValueError("Municipal map identifiers must remain text.")

        if not codes.str.fullmatch(r"[0-9]{7}", na=False).all() or not codes.is_unique:
            raise ValueError(f"Invalid or repeated municipal map identifiers: {level}.")

        missing = sorted(set(codes) - set(boundaries.index))
        if missing:
            raise ValueError(f"{level}: municipalities without IBGE geometry: {missing}")

        rows.append(
            {
                "list"           : level     ,
                "municipalities" : len(codes),
                "with_geometry"  : len(codes),
                "passed"         : True      ,
            }
        )

    return pd.DataFrame(rows)


def build_candidate_maps(
    municipalities_by_level : dict[str, pd.DataFrame],
    boundaries              : gpd.GeoDataFrame,
    states                  : gpd.GeoDataFrame,
) -> dict:
    """Create three equal-scale maps, each with one fixed-size point per municipality"""

    if set(municipalities_by_level) != set(LEVELS):
        raise ValueError("Maps require broad, candidates and restricted municipal tables.")

    validate_geographic_coverage(boundaries, municipalities_by_level)

    if states.crs != MAP_CRS:
        raise ValueError("State mesh must use EPSG:5880.")

    xmin, ymin, xmax, ymax = states.total_bounds

    margin = 0.025 * max(xmax - xmin, ymax - ymin)

    figures = {}

    with plt.rc_context(STYLE):
        for level, (label, description, color) in LEVELS.items():
            municipalities = municipalities_by_level[level]

            points = boundaries.loc[municipalities["ibge_municipality_code"]].geometry.centroid

            figure, ax = plt.subplots(figsize=(7.5, 7.2))

            figure.subplots_adjust(
                left  =0.05,
                right =0.97,
                bottom=0.16,
                top   =0.84,
            )

            states.plot(
                ax=ax,

                linewidth=0.45,
                facecolor="#F4F6F8",
                edgecolor="#B0B9C1",
            )

            ax.scatter(
                points.x,
                points.y,

                s         =14   ,
                zorder    =3    ,
                alpha     =0.8  ,
                linewidths=0.25 ,
                color     =color,
                edgecolors="white"                               ,
                label     ="At least one candidate establishment",
            )

            ax.set(
                xlim=(xmin - margin, xmax + margin),
                ylim=(ymin - margin, ymax + margin),

                aspect="equal",
            )

            ax.set_axis_off()

            figure.suptitle(
                f"Telesurgery candidate municipalities · {label}",

                x         =0.06  ,
                y         =0.975 ,
                fontsize  =13    ,
                fontweight="bold",
                ha        ="left",
            )

            figure.text(
                0.06 ,
                0.925,

                f"{description}\n{len(municipalities):,} municipalities · Brazil · June 2026",

                fontsize=9    ,
                va      ="top",
                color   ="#526170",
            )

            figure.legend(loc="lower left", bbox_to_anchor=(0.055, 0.075), frameon=False, fontsize=8)

            figure.text(
                0.06 ,
                0.025,

                "Sources: CNES/DATASUS · Reference period: June 2026 (202606) · Boundaries: IBGE.\n"
                "Municipal centroids in EPSG:5880; fixed marker size. Site assessment required.",

                fontsize=7,
                color   ="#526170",
            )

            figures[level] = figure

    return figures


def export_candidate_maps(figures: dict, docs_dir: Path) -> dict[str, Path]:
    """Atomically export only PDF figures, preserving the original product stems"""

    docs_dir = Path(docs_dir)

    docs_dir.mkdir(parents=True, exist_ok=True)

    paths = {}

    with plt.rc_context(STYLE):
        for level, figure in figures.items():
            if level not in LEVELS:
                raise ValueError(f"Unknown candidate level: {level}")

            suffix = "" if level == "candidates" else f"_{level}"
            path   = docs_dir / f"cnes_telesurgery_candidate_municipalities{suffix}_brazil_{COMPETENCE}_map.pdf"

            with NamedTemporaryFile(dir=docs_dir, prefix=f".{path.stem}.", suffix=".tmp", delete=False) as temporary:
                staged = Path(temporary.name)
            try:
                figure.savefig(
                    staged,

                    format     ="pdf"  ,
                    bbox_inches="tight",

                    metadata={
                        "CreationDate" : None,
                        "ModDate"      : None,
                    }
                )

                if not staged.read_bytes().startswith(b"%PDF-"):
                    raise ValueError(f"Invalid PDF export: {path}")

                staged.replace(path)
            finally:
                staged.unlink (missing_ok=True)

            plt.close(figure)

            paths[level] = path

    return paths
