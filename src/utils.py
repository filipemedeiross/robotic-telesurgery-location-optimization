"""Temporary files for validated, atomic publication"""

from pathlib    import Path
from contextlib import contextmanager
from tempfile   import NamedTemporaryFile


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
