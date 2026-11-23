"""Download input data without modifying its bytes"""

import shutil
import tempfile
import argparse

from pathlib        import Path
from urllib.request import urlopen
from urllib.error   import URLError
from http  .client  import HTTPException


REPOSITORY = "filipemedeiross/oncological-prostatectomy-access-optimization"
GIT_REF    = "main"
BASE_URL   = f"https://raw.githubusercontent.com/{REPOSITORY}/{GIT_REF}/data"

FILENAMES = (
    "municipal_data_2026_first_half.csv"         ,
    "oncology_prostatectomy_2026_first_half.csv" ,
    "origin_destination_data_2026_first_half.csv",
    "telesurgery_2026_first_half.txt"            ,
)

TIMEOUT_SECONDS = 30

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR     = PROJECT_ROOT / "data"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--force",

        action="store_true"                                                        ,
        help  ="Download files again, even if they already exist and are not empty",
    )

    return parser.parse_args()


def download_file(filename: str) -> int:
    """Validate the temporary file before replacing the destination; return its size"""

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    destination    = DATA_DIR / filename
    temporary_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb"    ,
            dir =DATA_DIR,

            prefix=f".{filename}.",
            suffix=".tmp"         ,
            delete=False          ,
        ) as temporary:
            temporary_path = Path(temporary.name)

            with urlopen(
                f"{BASE_URL}/{filename}",

                timeout=TIMEOUT_SECONDS,
            ) as response:
                shutil.copyfileobj(response, temporary)

                size          = temporary.tell       ()
                expected_size = response .headers.get("Content-Length")

                if size == 0:
                    raise ValueError("the server returned an empty file")

                if expected_size is not None and size != int(expected_size):
                    raise ValueError(
                        f"Incomplete download: expected {expected_size} bytes, received {size}"
                    )

        temporary_path.replace(destination)

        return size
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> int:
    args = parse_args()

    downloaded = skipped = failed = 0

    print(f"Source: {REPOSITORY} (Git ref: {GIT_REF})", flush=True)
    print(f"Destination: {DATA_DIR}"                  , flush=True)

    for index, filename in enumerate(FILENAMES, start=1):
        progress = f"[{index}/{len(FILENAMES)}] {filename}"

        try:
            destination = DATA_DIR / filename

            if (
                not args       .force                 and
                    destination.is_file()             and
                    destination.stat   ().st_size > 0
            ):
                print(f"{progress}: skipped (already exists and is not empty).", flush=True)

                skipped += 1

                continue

            print(f"{progress}: downloading...", flush=True)

            size = download_file(filename)

        except TimeoutError:
            print(f"{progress}: ERROR — timed out after {TIMEOUT_SECONDS} seconds.", flush=True); failed     += 1
        except (URLError, HTTPException, OSError, ValueError) as error:
            print(f"{progress}: ERROR — {error}"                                   , flush=True); failed     += 1
        else:
            print(f"{progress}: downloaded ({size} bytes)."                        , flush=True); downloaded += 1

    print()
    print(f"Summary: {downloaded} downloaded, {skipped} skipped, {failed} failed.", flush=True)

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
