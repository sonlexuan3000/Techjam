#!/usr/bin/env python3
"""Evaluate an isolated experiment entrypoint on a chosen local dataset."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluator.local_evaluator import catalog_index, evaluate, load_jsonl  # noqa: E402


def load_candidate(entrypoint: str | Path, catalog_path: str) -> tuple[Any, Path]:
    entrypoint_path = Path(entrypoint).resolve()
    if not entrypoint_path.is_file():
        raise ValueError(f"candidate entrypoint does not exist: {entrypoint_path}")

    module_suffix = hashlib.sha256(str(entrypoint_path).encode()).hexdigest()[:12]
    module_name = f"techjam_candidate_{module_suffix}"
    spec = importlib.util.spec_from_file_location(module_name, entrypoint_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load candidate entrypoint: {entrypoint_path}")

    module = importlib.util.module_from_spec(spec)
    candidate_dir = str(entrypoint_path.parent)
    sys.path.insert(0, candidate_dir)
    try:
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    finally:
        sys.path.remove(candidate_dir)

    builder = getattr(module, "build_agent", None)
    if not callable(builder):
        raise ValueError(f"{entrypoint_path} must expose build_agent(catalog_path)")
    candidate = builder(catalog_path)
    missing = [
        method
        for method in ("reset", "respond")
        if not callable(getattr(candidate, method, None))
    ]
    if missing:
        raise ValueError(f"candidate lacks required Agent methods: {missing}")
    return candidate, entrypoint_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entrypoint", required=True)
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    candidate, entrypoint_path = load_candidate(args.entrypoint, args.catalog)
    samples = load_jsonl(args.dataset)
    catalog_ids, categories, products = catalog_index(args.catalog)
    result = evaluate(candidate, samples, catalog_ids, categories, products)
    result = {
        "candidate_entrypoint": str(entrypoint_path),
        "dataset": str(Path(args.dataset)),
        **result,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "sessions"},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
