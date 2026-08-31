from __future__ import annotations

import argparse
import json
import os
import pickle
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from aggregate_review_features import (
    DAY_MS,
    WINDOW_DAYS,
    cutoff_timestamp_ms,
    extract_parent_asin,
    extract_timestamp_and_verified,
    load_catalog,
)


DEFAULT_URL = (
    "https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/"
    "resolve/main/raw/review_categories/Clothing_Shoes_and_Jewelry.jsonl"
)
DEFAULT_SIZE = 27_810_080_533
DEFAULT_CHUNKS = 32
DEFAULT_OVERLAP = 16 * 1024 * 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate Amazon review features with resumable parallel HTTP ranges."
        )
    )
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--size", type=int, default=DEFAULT_SIZE)
    parser.add_argument("--chunks", type=int, default=DEFAULT_CHUNKS)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--overlap-bytes", type=int, default=DEFAULT_OVERLAP)
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--output", default="data/review_features.jsonl")
    parser.add_argument("--checkpoint-dir", default="/tmp/techjam-review-ranges")
    parser.add_argument("--cutoff", default="2023-10-01")
    parser.add_argument(
        "--scanner-binary",
        default=None,
        help="Optional compiled native range scanner for much faster parsing.",
    )
    return parser.parse_args()


def chunk_bounds(size: int, chunks: int, index: int) -> tuple[int, int]:
    start = size * index // chunks
    end = size * (index + 1) // chunks - 1
    return start, end


def process_chunk(task: tuple) -> dict:
    (
        index,
        chunks,
        size,
        overlap,
        url,
        catalog_path,
        checkpoint_directory,
        cutoff_ms,
    ) = task
    checkpoint_path = Path(checkpoint_directory) / f"chunk-{index:03d}.pickle"
    if checkpoint_path.exists():
        with checkpoint_path.open("rb") as handle:
            cached = pickle.load(handle)
        return {**cached["summary"], "cached": True}

    _, catalog_ids = load_catalog(catalog_path)
    starts = {days: cutoff_ms - days * DAY_MS for days in WINDOW_DAYS}
    nominal_start, nominal_end = chunk_bounds(size, chunks, index)
    request_start = 0 if index == 0 else nominal_start - 1
    request_end = min(size - 1, nominal_end + overlap)
    command = [
        "curl",
        "--fail",
        "--silent",
        "--show-error",
        "--location",
        "--range",
        f"{request_start}-{request_end}",
        url,
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE)
    if process.stdout is None:
        raise RuntimeError("curl stdout pipe was not created")

    stats: dict[bytes, list[int]] = {}
    total_rows = 0
    matched_rows = 0
    malformed_rows = 0
    earliest_timestamp: int | None = None
    latest_timestamp: int | None = None
    position = request_start
    started = time.monotonic()

    if index > 0:
        partial_line = process.stdout.readline()
        position += len(partial_line)
        if not partial_line.endswith(b"\n"):
            process.kill()
            raise RuntimeError(
                f"chunk {index} could not find its initial newline boundary"
            )

    while position <= nominal_end:
        raw_line = process.stdout.readline()
        if not raw_line:
            break
        line_start = position
        position += len(raw_line)
        if not raw_line.endswith(b"\n") and index + 1 < chunks:
            process.kill()
            raise RuntimeError(
                f"chunk {index} needs more than {overlap} overlap bytes"
            )
        if line_start > nominal_end:
            break

        total_rows += 1
        parent_result = extract_parent_asin(raw_line)
        if parent_result is None:
            malformed_rows += 1
            continue
        parent_asin, parent_end = parent_result
        if parent_asin not in catalog_ids:
            continue
        review_result = extract_timestamp_and_verified(raw_line, parent_end)
        if review_result is None:
            malformed_rows += 1
            continue

        timestamp, verified = review_result
        values = stats.setdefault(
            parent_asin, [0] * (3 + 2 * len(WINDOW_DAYS))
        )
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

    # Consume the small overlap tail so curl can finish cleanly. Closing the
    # pipe here would make curl report code 56 even though the owned records
    # were processed successfully.
    while process.stdout.read(1024 * 1024):
        pass
    process.stdout.close()
    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"curl failed for chunk {index} with code {return_code}")

    summary = {
        "chunk": index,
        "total_rows": total_rows,
        "matched_rows": matched_rows,
        "malformed_rows": malformed_rows,
        "earliest_timestamp": earliest_timestamp,
        "latest_timestamp": latest_timestamp,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = checkpoint_path.with_suffix(".pickle.tmp")
    with temporary_path.open("wb") as handle:
        pickle.dump({"summary": summary, "stats": stats}, handle)
    temporary_path.replace(checkpoint_path)
    return {**summary, "cached": False}


def process_native_chunk(task: tuple) -> dict:
    base_task, scanner_binary = task
    (
        index,
        chunks,
        size,
        overlap,
        url,
        catalog_path,
        checkpoint_directory,
        cutoff_ms,
    ) = base_task
    checkpoint_path = Path(checkpoint_directory) / f"chunk-{index:03d}.pickle"
    if checkpoint_path.exists():
        with checkpoint_path.open("rb") as handle:
            cached = pickle.load(handle)
        return {**cached["summary"], "cached": True}

    nominal_start, nominal_end = chunk_bounds(size, chunks, index)
    request_start = 0 if index == 0 else nominal_start - 1
    request_end = min(size - 1, nominal_end + overlap)
    curl_command = [
        "curl",
        "--fail",
        "--silent",
        "--show-error",
        "--location",
        "--range",
        f"{request_start}-{request_end}",
        url,
    ]
    scanner_command = [
        scanner_binary,
        catalog_path,
        str(request_start),
        str(nominal_end),
        str(cutoff_ms),
        "1" if index + 1 == chunks else "0",
    ]
    started = time.monotonic()
    curl_process = subprocess.Popen(curl_command, stdout=subprocess.PIPE)
    if curl_process.stdout is None:
        raise RuntimeError("curl stdout pipe was not created")
    native_output = checkpoint_path.with_suffix(".native.tmp")
    with native_output.open("wb") as handle:
        scanner_process = subprocess.run(
            scanner_command,
            stdin=curl_process.stdout,
            stdout=handle,
            check=False,
        )
    curl_process.stdout.close()
    curl_return_code = curl_process.wait()
    if curl_return_code != 0 or scanner_process.returncode != 0:
        raise RuntimeError(
            f"native chunk {index} failed: curl={curl_return_code} "
            f"scanner={scanner_process.returncode}"
        )

    stats: dict[bytes, list[int]] = {}
    with native_output.open(encoding="utf-8") as handle:
        header = handle.readline().rstrip("\n").split("\t")
        if len(header) != 6 or header[0] != "#summary":
            raise RuntimeError(f"native chunk {index} has an invalid summary")
        total_rows, matched_rows, malformed_rows, earliest, latest = map(
            int, header[1:]
        )
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) != 14:
                raise RuntimeError(f"native chunk {index} has an invalid row")
            stats[fields[0].encode()] = [int(value) for value in fields[1:]]
    native_output.unlink()

    summary = {
        "chunk": index,
        "total_rows": total_rows,
        "matched_rows": matched_rows,
        "malformed_rows": malformed_rows,
        "earliest_timestamp": earliest or None,
        "latest_timestamp": latest or None,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = checkpoint_path.with_suffix(".pickle.tmp")
    with temporary_path.open("wb") as handle:
        pickle.dump({"summary": summary, "stats": stats}, handle)
    temporary_path.replace(checkpoint_path)
    return {**summary, "cached": False}


def merge_checkpoints(
    catalog_path: str,
    checkpoint_directory: str,
    chunks: int,
    output_path: str,
) -> dict:
    catalog_order, _ = load_catalog(catalog_path)
    combined = {
        identifier.encode(): [0] * (3 + 2 * len(WINDOW_DAYS))
        for identifier in catalog_order
    }
    summaries: list[dict] = []

    for index in range(chunks):
        checkpoint_path = Path(checkpoint_directory) / f"chunk-{index:03d}.pickle"
        with checkpoint_path.open("rb") as handle:
            checkpoint = pickle.load(handle)
        summaries.append(checkpoint["summary"])
        for parent_asin, partial_values in checkpoint["stats"].items():
            values = combined[parent_asin]
            values[0] += partial_values[0]
            values[1] += partial_values[1]
            values[2] = max(values[2], partial_values[2])
            for value_index in range(3, len(values)):
                values[value_index] += partial_values[value_index]

    destination = Path(output_path)
    temporary_path = destination.with_suffix(destination.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as handle:
        for identifier in catalog_order:
            values = combined[identifier.encode()]
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
    temporary_path.replace(destination)

    return {
        "catalog_products": len(catalog_order),
        "products_with_reviews": sum(values[0] > 0 for values in combined.values()),
        "total_rows": sum(summary["total_rows"] for summary in summaries),
        "matched_rows": sum(summary["matched_rows"] for summary in summaries),
        "malformed_rows": sum(summary["malformed_rows"] for summary in summaries),
        "earliest_matched_timestamp": min(
            summary["earliest_timestamp"]
            for summary in summaries
            if summary["earliest_timestamp"] is not None
        ),
        "latest_matched_timestamp": max(
            summary["latest_timestamp"]
            for summary in summaries
            if summary["latest_timestamp"] is not None
        ),
        "output": output_path,
    }


def main() -> None:
    args = parse_args()
    if args.size <= 0 or args.chunks <= 0 or args.workers <= 0:
        raise ValueError("size, chunks, and workers must be positive")
    checkpoint_directory = Path(args.checkpoint_dir)
    checkpoint_directory.mkdir(parents=True, exist_ok=True)
    cutoff_ms = cutoff_timestamp_ms(args.cutoff)
    base_tasks = [
        (
            index,
            args.chunks,
            args.size,
            args.overlap_bytes,
            args.url,
            args.catalog,
            str(checkpoint_directory),
            cutoff_ms,
        )
        for index in range(args.chunks)
    ]
    tasks = (
        [(task, args.scanner_binary) for task in base_tasks]
        if args.scanner_binary
        else base_tasks
    )
    worker_function = process_native_chunk if args.scanner_binary else process_chunk

    started = time.monotonic()
    completed = 0
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(worker_function, task) for task in tasks]
        for future in as_completed(futures):
            summary = future.result()
            completed += 1
            print(
                f"completed={completed}/{args.chunks} chunk={summary['chunk']} "
                f"rows={summary['total_rows']:,} "
                f"matched={summary['matched_rows']:,} "
                f"seconds={summary['elapsed_seconds']} cached={summary['cached']}",
                flush=True,
            )

    result = merge_checkpoints(
        args.catalog,
        str(checkpoint_directory),
        args.chunks,
        args.output,
    )
    result.update(
        {
            "source_url": args.url,
            "source_size": args.size,
            "chunks": args.chunks,
            "workers": args.workers,
            "cutoff": args.cutoff,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "pid": os.getpid(),
        }
    )
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
