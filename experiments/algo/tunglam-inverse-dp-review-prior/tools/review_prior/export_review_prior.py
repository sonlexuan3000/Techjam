from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export one aggregate review feature as a compact offline TSV."
    )
    parser.add_argument("--input", default="data/review_features.jsonl")
    parser.add_argument("--output", default="data/review_prior.tsv")
    parser.add_argument("--field", default="verified_reviews_365d")
    args = parser.parse_args()

    output_path = Path(args.output)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    with Path(args.input).open(encoding="utf-8") as source, temporary_path.open(
        "w", encoding="utf-8"
    ) as destination:
        destination.write(f"parent_asin\t{args.field}\n")
        for line in source:
            if not line.strip():
                continue
            record = json.loads(line)
            destination.write(
                f"{record['parent_asin']}\t{int(record.get(args.field, 0) or 0)}\n"
            )
    temporary_path.replace(output_path)


if __name__ == "__main__":
    main()
