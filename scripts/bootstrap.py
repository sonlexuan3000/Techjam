#!/usr/bin/env python3
"""Download and verify the frozen TechJam participant catalog."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import shutil
import urllib.request
from pathlib import Path


CATALOG_URL = (
    "https://github.com/TechJam2026/techjam-conversational-search/"
    "releases/download/participant-kit/catalog.jsonl.gz"
)
EXPECTED_SHA256 = "07fd142631fd6b03e2b4d09988c3eb7d53720e9d57010c79db48eeaada50a8f8"
EXPECTED_ROWS = 50_000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: Path) -> None:
    temporary = destination.with_name(destination.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "techjam-bootstrap/1.0"})
    print(f"Downloading {url}")
    with urllib.request.urlopen(request) as response, temporary.open("wb") as output:
        shutil.copyfileobj(response, output)
    temporary.replace(destination)


def unpack(archive: Path, destination: Path) -> None:
    temporary = destination.with_name(destination.name + ".part")
    print(f"Unpacking {archive} -> {destination}")
    with gzip.open(archive, "rb") as source, temporary.open("wb") as output:
        shutil.copyfileobj(source, output)
    temporary.replace(destination)


def row_count(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for line in handle if line.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force-unpack",
        action="store_true",
        help="replace data/catalog.jsonl after verifying the frozen archive",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    data_directory = root / "data"
    archive = data_directory / "catalog.jsonl.gz"
    catalog = data_directory / "catalog.jsonl"
    data_directory.mkdir(parents=True, exist_ok=True)

    if not archive.exists():
        download(CATALOG_URL, archive)

    actual_hash = sha256(archive)
    if actual_hash != EXPECTED_SHA256:
        raise SystemExit(
            f"Catalog checksum mismatch: expected {EXPECTED_SHA256}, got {actual_hash}. "
            f"Remove {archive} and run setup again."
        )
    print(f"SHA-256 OK: {actual_hash}")

    if args.force_unpack or not catalog.exists():
        unpack(archive, catalog)

    actual_rows = row_count(catalog)
    if actual_rows != EXPECTED_ROWS:
        raise SystemExit(
            f"Catalog row-count mismatch: expected {EXPECTED_ROWS}, got {actual_rows}. "
            "Run with --force-unpack."
        )
    print(f"Catalog OK: {catalog} ({actual_rows:,} products)")


if __name__ == "__main__":
    main()
