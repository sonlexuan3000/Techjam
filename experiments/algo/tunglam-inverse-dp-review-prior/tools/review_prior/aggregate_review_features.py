from __future__ import annotations

import argparse
from contextlib import nullcontext
import gzip
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


PARENT_ASIN_RE = re.compile(br'"parent_asin"\s*:\s*"([^"]+)"')
TIMESTAMP_RE = re.compile(br'"timestamp"\s*:\s*(\d+)')
VERIFIED_RE = re.compile(br'"verified_purchase"\s*:\s*(true|false)')
PARENT_ASIN_MARKER = b'"parent_asin": "'
TIMESTAMP_MARKER = b'"timestamp": '
VERIFIED_MARKER = b'"verified_purchase": '
DAY_MS = 24 * 60 * 60 * 1000
WINDOW_DAYS = (30, 90, 180, 365, 730)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Stream an Amazon Reviews 2023 category JSONL gzip from stdin and "
            "aggregate review-volume features for products in the frozen catalog."
        )
    )
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--output", default="data/review_features.jsonl")
    parser.add_argument(
        "--cutoff",
        default="2023-10-01",
        help="Exclusive UTC cutoff date used for recent windows (YYYY-MM-DD).",
    )
    parser.add_argument("--progress-every", type=int, default=1_000_000)
    parser.add_argument(
        "--input-compression",
        choices=("gzip", "none"),
        default="gzip",
        help="Set to none when an external gzip process already decompresses stdin.",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="Optional early-stop limit for smoke tests.",
    )
    return parser.parse_args()


def load_catalog(path: str | Path) -> tuple[list[str], set[bytes]]:
    identifiers: list[str] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                identifiers.append(str(json.loads(line)["parent_asin"]))
    return identifiers, {identifier.encode() for identifier in identifiers}


def cutoff_timestamp_ms(value: str) -> int:
    parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def extract_parent_asin(raw_line: bytes) -> tuple[bytes, int] | None:
    marker_index = raw_line.rfind(PARENT_ASIN_MARKER)
    if marker_index >= 0:
        value_start = marker_index + len(PARENT_ASIN_MARKER)
        value_end = raw_line.find(b'"', value_start)
        if value_end >= 0:
            return raw_line[value_start:value_end], value_end
    fallback = PARENT_ASIN_RE.search(raw_line)
    return (fallback.group(1), fallback.end()) if fallback is not None else None


def extract_timestamp_and_verified(
    raw_line: bytes, search_start: int
) -> tuple[int, bool] | None:
    timestamp_index = raw_line.find(TIMESTAMP_MARKER, search_start)
    verified_index = raw_line.find(VERIFIED_MARKER, search_start)
    if timestamp_index >= 0 and verified_index >= 0:
        timestamp_start = timestamp_index + len(TIMESTAMP_MARKER)
        timestamp_end = raw_line.find(b",", timestamp_start)
        if timestamp_end >= 0:
            return (
                int(raw_line[timestamp_start:timestamp_end]),
                raw_line.startswith(b"true", verified_index + len(VERIFIED_MARKER)),
            )
    timestamp_match = TIMESTAMP_RE.search(raw_line, search_start)
    verified_match = VERIFIED_RE.search(raw_line, search_start)
    if timestamp_match is None or verified_match is None:
        return None
    return int(timestamp_match.group(1)), verified_match.group(1) == b"true"


def main() -> None:
    args = parse_args()
    catalog_order, catalog_ids = load_catalog(args.catalog)
    cutoff_ms = cutoff_timestamp_ms(args.cutoff)
    starts = {
        days: cutoff_ms - days * DAY_MS
        for days in WINDOW_DAYS
    }
    # total, verified, latest timestamp, then raw/verified pairs by window.
    stats = {identifier.encode(): [0] * (3 + 2 * len(WINDOW_DAYS)) for identifier in catalog_order}

    total_rows = 0
    matched_rows = 0
    malformed_rows = 0
    earliest_timestamp: int | None = None
    latest_timestamp: int | None = None
    started = time.monotonic()

    stream_context = (
        gzip.GzipFile(fileobj=sys.stdin.buffer, mode="rb")
        if args.input_compression == "gzip"
        else nullcontext(sys.stdin.buffer)
    )
    with stream_context as stream:
        for raw_line in stream:
            if args.max_rows is not None and total_rows >= args.max_rows:
                break
            total_rows += 1
            parent_result = extract_parent_asin(raw_line)
            if parent_result is None:
                malformed_rows += 1
                continue
            parent_asin, parent_end = parent_result
            if parent_asin not in catalog_ids:
                if args.progress_every and total_rows % args.progress_every == 0:
                    elapsed = max(time.monotonic() - started, 1e-9)
                    print(
                        f"rows={total_rows:,} matched={matched_rows:,} "
                        f"rate={total_rows / elapsed:,.0f} rows/s",
                        file=sys.stderr,
                        flush=True,
                    )
                continue

            review_result = extract_timestamp_and_verified(raw_line, parent_end)
            if review_result is None:
                malformed_rows += 1
                continue

            timestamp, verified = review_result
            values = stats[parent_asin]
            values[0] += 1
            values[1] += int(verified)
            values[2] = max(values[2], timestamp)
            matched_rows += 1
            earliest_timestamp = (
                timestamp
                if earliest_timestamp is None
                else min(earliest_timestamp, timestamp)
            )
            latest_timestamp = (
                timestamp
                if latest_timestamp is None
                else max(latest_timestamp, timestamp)
            )

            if timestamp < cutoff_ms:
                for window_index, days in enumerate(WINDOW_DAYS):
                    if timestamp >= starts[days]:
                        raw_index = 3 + 2 * window_index
                        values[raw_index] += 1
                        values[raw_index + 1] += int(verified)

            if args.progress_every and total_rows % args.progress_every == 0:
                elapsed = max(time.monotonic() - started, 1e-9)
                print(
                    f"rows={total_rows:,} matched={matched_rows:,} "
                    f"rate={total_rows / elapsed:,.0f} rows/s",
                    file=sys.stderr,
                    flush=True,
                )

    output_path = Path(args.output)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as handle:
        for identifier in catalog_order:
            values = stats[identifier.encode()]
            record = {
                "parent_asin": identifier,
                "raw_review_count": values[0],
                "verified_review_count": values[1],
                "latest_review_timestamp": values[2] or None,
            }
            for window_index, days in enumerate(WINDOW_DAYS):
                raw_index = 3 + 2 * window_index
                record[f"reviews_{days}d"] = values[raw_index]
                record[f"verified_reviews_{days}d"] = values[raw_index + 1]
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    temporary_path.replace(output_path)

    elapsed = max(time.monotonic() - started, 1e-9)
    nonzero_products = sum(values[0] > 0 for values in stats.values())
    print(
        json.dumps(
            {
                "catalog_products": len(catalog_order),
                "products_with_reviews": nonzero_products,
                "total_rows": total_rows,
                "matched_rows": matched_rows,
                "malformed_rows": malformed_rows,
                "earliest_matched_timestamp": earliest_timestamp,
                "latest_matched_timestamp": latest_timestamp,
                "cutoff": args.cutoff,
                "elapsed_seconds": round(elapsed, 3),
                "rows_per_second": round(total_rows / elapsed, 3),
                "output": str(output_path),
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
