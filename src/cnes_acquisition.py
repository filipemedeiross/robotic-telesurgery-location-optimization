"""Acquire exactly June 2026 CNES/ST, LT and SR with a checked DBC cache"""

from __future__ import annotations

import json
import hashlib

import pandas as pd

from pathlib        import Path
from contextlib     import contextmanager
from urllib.request import Request           , urlopen
from datetime       import datetime          , timezone
from ftplib         import FTP               , all_errors
from tempfile       import NamedTemporaryFile, TemporaryDirectory

from dbfread   import DBF
from pyreaddbc import dbc2dbf

from .cnes_selection import (
    COMPETENCE,
    STATES    ,

    STATE_BY_PREFIX as STATE_PREFIXES,
    SOURCE_COLUMNS  as GROUP_COLUMNS ,
)


FTP_HOST           = "ftp.datasus.gov.br"
FTP_DIRECTORY      = "/dissemin/publicos/CNES/200508_/Dados"
MUNICIPALITIES_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios?orderBy=id"


def sha256(path: Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@contextmanager
def staged_path(destination: Path):
    """Stage beside the destination to allow an atomic replacement"""

    destination = Path(destination)

    destination.parent.mkdir(parents=True, exist_ok=True)

    with NamedTemporaryFile(
        dir   =    destination.parent ,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        delete=False ,
    ) as stream:
        temporary = Path(stream.name)
    try:
        yield temporary
    finally:
        temporary.unlink(missing_ok=True)


def write_json(payload: dict, destination: Path) -> None:
    with staged_path(destination) as temporary:
        temporary.write_text(
            json.dumps(
                payload,

                ensure_ascii=False,
                indent      =2    ,
            ) + "\n",

            encoding="utf-8",
        )

        temporary.replace(destination)


def expected_files() -> dict[str, tuple[str, str]]:
    return {
        f"{group}{state}2606.dbc" : (group, state)
        for group in GROUP_COLUMNS
        for state in STATES
    }


def validate_source_coverage(sources: list[dict]) -> None:
    """Reject a missing, repeated, wrong-month or wrong-group/UF source"""

    expected = expected_files()

    if len(sources) != len(expected) or {row["file"] for row in sources} != set(expected):
        missing = sorted(set(expected) - {row["file"] for row in sources})

        raise ValueError(f"CNES 202606 requires exactly 81 files (ST/LT/SR x 27 UFs); missing: {missing}")

    for row in sources:
        if (row["group"], row["state"]) != expected[row["file"]] or row.get("competence") != COMPETENCE:
            raise ValueError(f"Wrong CNES source dimensions: {row}")

        if row.get("size_bytes", 0) <= 0:
            raise ValueError(f"Empty CNES source: {row['file']}")


def validate_source_frame(frame: pd.DataFrame, group: str, state: str) -> None:
    missing = set(GROUP_COLUMNS[group]) - set(frame.columns)

    if missing or frame.empty:
        raise ValueError(f"{group}/{state}: empty source or missing columns: {sorted(missing)}")

    found = set(frame["COMPETEN"].astype("string").str.strip())
    if found != {COMPETENCE}:
        raise ValueError(f"{group}/{state}: expected source COMPETEN=202606, found {found}")

    if group == "ST":
        states = (
            frame["CODUFMUN"]
            .astype("string")
            .str
            .strip ()
            .str
            .zfill (6)
            .str[:2]
            .map   (STATE_PREFIXES)
        )

        if not states.eq(state).all():
            raise ValueError(f"ST/{state}: municipality UF does not match the source file")


def read_dbc(path: Path, group: str, state: str) -> pd.DataFrame:
    """Convert to temporary DBF; preserve identifiers and check source competence"""

    with TemporaryDirectory(prefix="cnes-dbf-") as directory:
        dbf_path = Path(directory) / "source.dbf"

        dbc2dbf(str(path), str(dbf_path))

        table = DBF(
            str(dbf_path),

            encoding="latin-1",
            raw     =True     ,
        )

        missing = set(GROUP_COLUMNS[group]) - set(table.field_names)

        if missing:
            raise ValueError(f"{path.name}: missing source columns: {sorted(missing)}")

        rows = (
            {
                column : record[column].decode("latin-1").strip()
                for column in GROUP_COLUMNS[group]
            }
            for record in table
        )

        frame = pd.DataFrame(
            rows,

            columns=GROUP_COLUMNS[group],
            dtype  ="string"            ,
        )

    validate_source_frame(frame, group, state)

    return frame


def validate_source_proof(sources: list[dict]) -> None:
    """Check the retained evidence needed after source columns are discarded"""

    validate_source_coverage(sources)

    for row in sources:
        digest = row.get("sha256", "")

        if row.get("validated_competence") != COMPETENCE or row.get("rows", 0) <= 0:
            raise ValueError(f"Cached source lacks competence/row-count proof: {row['file']}")

        if not isinstance(digest, str) or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError(f"Cached source lacks SHA256: {row['file']}")


def _connect(timeout: float) -> FTP:
    ftp = FTP(timeout=timeout)

    ftp.connect(FTP_HOST)
    ftp.login  ()

    return ftp


def _remote_sources(ftp: FTP) -> list[dict]:
    """Check availability of the complete fixed snapshot before downloading"""

    sources = []

    for group in GROUP_COLUMNS:
        directory = f"{FTP_DIRECTORY}/{group}"

        ftp.cwd(directory)

        names   = {
            name.upper() : name
            for name in ftp.nlst()
        }

        missing = [
            name
            for name, (g, _) in expected_files().items()
            if  g == group and name.upper() not in names
        ]

        if missing:
            raise ValueError(f"CNES 202606 unavailable in {directory}; missing: {missing}")

        ftp.voidcmd("TYPE I")

        for state in STATES:
            filename    = f"{group}{state}2606.dbc"
            remote_name = names[filename.upper()]

            sources.append({
                "file"       : filename  ,
                "group"      : group     ,
                "state"      : state     ,
                "competence" : COMPETENCE,

                "url"         : f"ftp://{FTP_HOST}{directory}/{remote_name}",
                "remote_path" : f"{directory}/{remote_name}"                ,
                "size_bytes"  : ftp.size   (remote_name                                       ),
                "modified_at" : ftp.sendcmd(f"MDTM {remote_name}").removeprefix("213 ").strip(),
            })

    validate_source_coverage(sources)

    return sources


def acquire_groups(root: Path, timeout: float = 90) -> tuple[dict[str, pd.DataFrame], dict]:
    """Reuse a complete validated snapshot, otherwise acquire the 81 fixed DBCs"""

    cache         = Path(root) / ".cache" / "cnes" / COMPETENCE
    manifest_path = cache      / "source_manifest.json"

    manifest = (
        json.loads(manifest_path.read_text())
        if   manifest_path.exists()
        else None
    )

    ftp = None

    if manifest:
        validate_source_coverage(manifest["files"])

        sources = manifest["files"]
    else:
        try:
            ftp     = _connect       (timeout)
            sources = _remote_sources(ftp    )
        except (*all_errors, ValueError) as error:
            if ftp is not None:
                ftp.close()

            raise RuntimeError(f"Cannot acquire complete CNES 202606 ST/LT/SR coverage: {error}") from error

    frames   = {
        group : []
        for group in GROUP_COLUMNS
    }

    manifest = manifest or {
        "competence"      : COMPETENCE  ,
        "ufs"             : list(STATES),
        "files"           : sources     ,
        "acquired_at_utc" : datetime.now(timezone.utc).isoformat(),
    }

    write_json(manifest, manifest_path)

    try:
        for index, source in enumerate(sources, 1):
            path = cache / "dbc" / source["file"]

            digest = (
                sha256(path)
                if   path.exists() and path.stat().st_size == source["size_bytes"]
                else None
            )

            compatible = digest is not None and digest == source.get("sha256")

            print(f"[{index:02d}/81] {source['file']}: {'cache' if compatible else 'DATASUS'}", flush=True)

            if not compatible:
                for attempt in range(2):
                    try:
                        if ftp is None:
                            ftp = _connect(timeout)

                        with staged_path(path) as temporary:
                            with temporary.open("wb") as stream:
                                ftp.retrbinary(f"RETR {source['remote_path']}", stream.write)

                            if temporary.stat().st_size != source["size_bytes"]:
                                raise ValueError(f"Incomplete download: {source['file']}")

                            frame = read_dbc(
                                temporary,

                                source["group"],
                                source["state"],
                            )

                            temporary.replace(path)

                        break
                    except (*all_errors, ValueError) as error:
                        if ftp is not None:
                            ftp.close()

                        ftp = None
                        if attempt == 1:
                            raise RuntimeError(f"Failed to retrieve {source['url']}: {error}") from error

                digest = sha256(path)
            else:
                frame = read_dbc(path, source["group"], source["state"])

            source.update(
                sha256              =digest       ,
                rows                =len   (frame),
                validated_competence=COMPETENCE   ,
            )

            frames[source["group"]].append(frame)

            write_json(manifest, manifest_path)

        manifest["validated_at_utc"] = datetime.now(timezone.utc).isoformat()

        validate_source_proof(sources )
        write_json           (manifest, manifest_path)

        return {
            group : pd.concat(parts, ignore_index=True)
            for group, parts in frames.items()
        }, manifest

    finally:
        if ftp is not None:
            ftp.close()


def load_municipalities(root: Path, timeout: float = 90) -> tuple[pd.DataFrame, dict]:
    cache = Path(root) / ".cache" / "cnes" / COMPETENCE / "municipalities_ibge.json"

    loaded_from = "cache" if cache.exists() else "IBGE download"

    if cache.exists():
        raw = cache.read_bytes()
    else:
        try:
            with urlopen(
                Request(
                    MUNICIPALITIES_URL,

                    headers={
                        "User-Agent" : "cnes-candidates/202606",
                    },
                ),

                timeout=timeout,
            ) as response:
                raw = response.read()
        except OSError as error:
            raise RuntimeError(f"Cannot retrieve IBGE municipality reference: {MUNICIPALITIES_URL}: {error}") from error

    payload = json.loads(raw.decode("utf-8-sig"))

    if not isinstance(payload, list) or len(payload) < 5500:
        raise ValueError("Incomplete IBGE municipality reference")

    frame = pd.DataFrame(
        {
            "ibge_municipality_code" : [str(row["id"]) for row in payload],
            "municipality"           : [row["nome"]    for row in payload],
        },

        dtype="string",
    )

    frame["state"] = frame["ibge_municipality_code"].str[:2].map(STATE_PREFIXES).astype("string")

    if (
        not frame["ibge_municipality_code"].str.fullmatch(r"[0-9]{7}").all() or
        not frame["ibge_municipality_code"].is_unique                        or
        set(frame["state"                 ]) != set(STATES)
    ):
        raise ValueError("Invalid municipality reference identifiers/UF coverage")

    if not cache.exists():
        with staged_path(cache) as temporary:
            temporary.write_bytes(raw  )
            temporary.replace    (cache)

    return frame, {
        "url"         : MUNICIPALITIES_URL,
        "sha256"      : sha256(cache),
        "rows"        : len   (frame),
        "loaded_from" : loaded_from  ,

        "cached_at_utc" : datetime.fromtimestamp(cache.stat().st_mtime, timezone.utc).isoformat(),
    }
