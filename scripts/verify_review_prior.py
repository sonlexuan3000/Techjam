#!/usr/bin/env python3
"""Verify the bundled review prior against the frozen organizer catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


EXPECTED_SHA256 = (
    "45bc7fa2053e55c2bdef7454c2461886a02ef25d0d25339d5d51a5affaafcfd6"
)
EXPECTED_HEADER = "parent_asin\tverified_reviews_365d"


def load_catalog_identifiers(path: Path) -> set[str]:
    identifiers: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            parent_asin = str(json.loads(line)["parent_asin"])
            if parent_asin in identifiers:
                raise ValueError(
                    f"duplicate catalog parent_asin at line {line_number}: "
                    f"{parent_asin}"
                )
            identifiers.add(parent_asin)
    return identifiers


def load_prior(path: Path) -> tuple[set[str], list[int]]:
    identifiers: set[str] = set()
    counts: list[int] = []
    with path.open(encoding="utf-8") as handle:
        header = handle.readline().rstrip("\n")
        if header != EXPECTED_HEADER:
            raise ValueError(f"unexpected prior header: {header!r}")
        for line_number, line in enumerate(handle, start=2):
            if not line.strip():
                continue
            try:
                parent_asin, raw_count = line.rstrip("\n").split("\t")
                count = int(raw_count)
            except ValueError as error:
                raise ValueError(
                    f"invalid prior row at line {line_number}"
                ) from error
            if not parent_asin or count < 0:
                raise ValueError(f"invalid prior row at line {line_number}")
            if parent_asin in identifiers:
                raise ValueError(
                    f"duplicate prior parent_asin at line {line_number}: "
                    f"{parent_asin}"
                )
            identifiers.add(parent_asin)
            counts.append(count)
    return identifiers, counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("data/catalog.jsonl"))
    parser.add_argument(
        "--prior",
        type=Path,
        default=Path("submission/data/review_prior.tsv"),
    )
    args = parser.parse_args()

    digest = hashlib.sha256(args.prior.read_bytes()).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError(
            f"review-prior SHA-256 mismatch: {digest}; expected {EXPECTED_SHA256}"
        )

    catalog_identifiers = load_catalog_identifiers(args.catalog)
    prior_identifiers, counts = load_prior(args.prior)
    if prior_identifiers != catalog_identifiers:
        missing = len(catalog_identifiers - prior_identifiers)
        extra = len(prior_identifiers - catalog_identifiers)
        raise ValueError(
            f"review-prior/catalog coverage mismatch: missing={missing}, extra={extra}"
        )

    print(
        "Review prior OK: "
        f"{len(counts):,} products, "
        f"{sum(count > 0 for count in counts):,} nonzero, "
        f"SHA-256 {digest}"
    )


if __name__ == "__main__":
    main()
