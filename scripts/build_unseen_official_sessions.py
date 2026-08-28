from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluator.local_evaluator import intent_card  # noqa: E402


DEV_SIZE = 2_000
HOLDOUT_SIZE = 800
EXPECTED_PUBLIC_SIZE = 200
MIN_DISTINCT_CONSTRAINTS = 4
SCENARIO_WEIGHTS = {
    "buying": 40,
    "browsing": 40,
    "intent_override": 15,
    "boundary": 5,
}
PROFILE_TAGS = (
    "comfort",
    "durability",
    "fit",
    "lightweight",
    "quality",
    "style",
    "value",
    "versatility",
)
PURCHASE_FREQUENCIES = (
    "1-2 prior purchases",
    "3-4 prior purchases",
    "5+ prior purchases",
)
PRIOR_RATINGS = (2.8, 3.2, 3.6, 4.0, 4.3, 4.6, 4.8, 5.0)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _stable_rng(seed: str, namespace: str) -> random.Random:
    material = f"{seed}\0{namespace}".encode("utf-8")
    integer_seed = int.from_bytes(hashlib.sha256(material).digest(), "big")
    return random.Random(integer_seed)


def _read_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON in {path} at line {line_number}: {error}") from error
            if not isinstance(value, dict):
                raise ValueError(f"Expected an object in {path} at line {line_number}")
            records.append(value)
    return records


def _load_catalog(path: Path) -> tuple[list[dict], dict[str, dict]]:
    products = _read_jsonl(path)
    by_asin: dict[str, dict] = {}
    for index, product in enumerate(products, start=1):
        asin = str(product.get("parent_asin") or "").strip()
        if not asin:
            raise ValueError(f"Catalog record {index} has no parent_asin")
        if asin in by_asin:
            raise ValueError(f"Catalog contains duplicate parent_asin: {asin}")
        by_asin[asin] = product
    return products, by_asin


def _load_public_targets(path: Path) -> tuple[list[dict], set[str]]:
    samples = _read_jsonl(path)
    targets: set[str] = set()
    for index, sample in enumerate(samples, start=1):
        ground_truth = sample.get("ground_truth")
        asin = str(
            ground_truth.get("parent_asin") if isinstance(ground_truth, dict) else ""
        ).strip()
        if not asin:
            raise ValueError(f"Public sample {index} has no ground_truth.parent_asin")
        targets.add(asin)

    if len(samples) != EXPECTED_PUBLIC_SIZE:
        raise ValueError(
            f"Expected {EXPECTED_PUBLIC_SIZE} public rows, found {len(samples)} in {path}"
        )
    if len(targets) != EXPECTED_PUBLIC_SIZE:
        raise ValueError(
            f"Expected {EXPECTED_PUBLIC_SIZE} unique public targets, found {len(targets)}"
        )
    return samples, targets


def _distinct_card_constraints(product: dict) -> tuple[str, ...]:
    card = intent_card(product)
    ordered = [
        *[str(value) for value in card.get("hard_constraints", [])],
        *[str(value) for value in card.get("soft_preferences", [])],
    ]
    return tuple(dict.fromkeys(value for value in ordered if value.strip()))


def _scenario_counts(size: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    for scenario, weight in SCENARIO_WEIGHTS.items():
        numerator = size * weight
        if numerator % 100:
            raise ValueError(f"Split size {size} cannot represent the exact scenario mix")
        counts[scenario] = numerator // 100
    if sum(counts.values()) != size:
        raise AssertionError("Scenario counts do not sum to split size")
    return counts


def _scenario_sequence(size: int, rng: random.Random) -> list[str]:
    scenarios = [
        scenario
        for scenario, count in _scenario_counts(size).items()
        for _ in range(count)
    ]
    rng.shuffle(scenarios)
    return scenarios


def _rating_style(average_rating: float) -> str:
    if average_rating >= 4.3:
        return "usually positive"
    if average_rating >= 3.6:
        return "balanced"
    return "selective"


def _synthetic_profile(rng: random.Random) -> dict:
    """Create a profile without consulting the target ASIN or its metadata."""

    average_rating = rng.choice(PRIOR_RATINGS)
    tag_count = rng.choice((2, 3, 3, 4))
    tags = rng.sample(list(PROFILE_TAGS), k=tag_count)
    rating_style = _rating_style(average_rating)
    tag_summary = ", ".join(tags)
    return {
        "purchase_frequency": rng.choice(PURCHASE_FREQUENCIES),
        "average_prior_rating": average_rating,
        "rating_style": rating_style,
        "preference_tags": tags,
        "summary": f"Prior purchases emphasize {tag_summary}; ratings are {rating_style}.",
    }


def _build_split(
    name: str,
    targets: list[str],
    *,
    seed: str,
) -> list[dict]:
    scenario_rng = _stable_rng(seed, f"{name}:scenarios")
    profile_rng = _stable_rng(seed, f"{name}:profiles")
    scenarios = _scenario_sequence(len(targets), scenario_rng)
    profiles = [_synthetic_profile(profile_rng) for _ in targets]

    return [
        {
            "sample_id": f"unseen_{name}_{index:05d}",
            "scenario_type": scenario,
            "user_profile": profile,
            "ground_truth": {"parent_asin": target},
        }
        for index, (target, scenario, profile) in enumerate(
            zip(targets, scenarios, profiles, strict=True),
            start=1,
        )
    ]


def _jsonl_bytes(records: Iterable[dict]) -> bytes:
    lines = [
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for record in records
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _target_digest(targets: set[str]) -> str:
    payload = ("\n".join(sorted(targets)) + "\n").encode("utf-8")
    return _sha256_bytes(payload)


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _split_manifest(
    records: list[dict],
    output_path: Path,
    output_bytes: bytes,
) -> dict:
    targets = {str(record["ground_truth"]["parent_asin"]) for record in records}
    return {
        "path": output_path.as_posix(),
        "session_count": len(records),
        "target_count": len(targets),
        "scenario_counts": dict(
            sorted(Counter(record["scenario_type"] for record in records).items())
        ),
        "sha256": _sha256_bytes(output_bytes),
        "sorted_target_ids_sha256": _target_digest(targets),
    }


def build(args: argparse.Namespace) -> dict:
    catalog_path = Path(args.catalog)
    public_path = Path(args.public_set)
    output_dir = Path(args.output_dir)
    dev_path = output_dir / "dev_set.jsonl"
    holdout_path = output_dir / "holdout_set.jsonl"
    manifest_path = output_dir / "manifest.json"

    for path in (catalog_path, public_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    existing_outputs = [
        path for path in (dev_path, holdout_path, manifest_path) if path.exists()
    ]
    if existing_outputs and not args.force:
        joined = ", ".join(path.as_posix() for path in existing_outputs)
        raise FileExistsError(
            f"Refusing to overwrite existing output(s): {joined}. "
            "Pass --force to replace them."
        )

    catalog_records, catalog_by_asin = _load_catalog(catalog_path)
    public_samples, public_targets = _load_public_targets(public_path)
    missing_public_targets = public_targets - set(catalog_by_asin)
    if missing_public_targets:
        raise ValueError(
            f"Public targets missing from catalog: {', '.join(sorted(missing_public_targets)[:10])}"
        )

    eligible: list[str] = []
    constraint_counts: dict[str, int] = {}
    for asin, product in catalog_by_asin.items():
        if asin in public_targets:
            continue
        distinct_constraints = _distinct_card_constraints(product)
        constraint_counts[asin] = len(distinct_constraints)
        if len(distinct_constraints) >= MIN_DISTINCT_CONSTRAINTS:
            eligible.append(asin)

    required_targets = DEV_SIZE + HOLDOUT_SIZE
    if len(eligible) < required_targets:
        raise ValueError(
            f"Need {required_targets} eligible unseen products, found only {len(eligible)}"
        )

    eligible.sort()
    target_rng = _stable_rng(str(args.seed), "target-selection")
    target_rng.shuffle(eligible)
    selected = eligible[:required_targets]
    dev_targets = selected[:DEV_SIZE]
    holdout_targets = selected[DEV_SIZE:]

    dev_records = _build_split("dev", dev_targets, seed=str(args.seed))
    holdout_records = _build_split("holdout", holdout_targets, seed=str(args.seed))
    dev_bytes = _jsonl_bytes(dev_records)
    holdout_bytes = _jsonl_bytes(holdout_records)

    dev_target_set = set(dev_targets)
    holdout_target_set = set(holdout_targets)
    overlap_counts = {
        "public_vs_dev_targets": len(public_targets & dev_target_set),
        "public_vs_holdout_targets": len(public_targets & holdout_target_set),
        "dev_vs_holdout_targets": len(dev_target_set & holdout_target_set),
    }
    actual_dev_scenarios = Counter(record["scenario_type"] for record in dev_records)
    actual_holdout_scenarios = Counter(record["scenario_type"] for record in holdout_records)
    checks = {
        "public_row_count_is_200": len(public_samples) == EXPECTED_PUBLIC_SIZE,
        "public_target_count_is_200": len(public_targets) == EXPECTED_PUBLIC_SIZE,
        "all_public_targets_exist_in_catalog": not missing_public_targets,
        "all_selected_targets_have_at_least_four_constraints": all(
            constraint_counts[target] >= MIN_DISTINCT_CONSTRAINTS for target in selected
        ),
        "dev_has_2000_unique_targets": len(dev_target_set) == DEV_SIZE,
        "holdout_has_800_unique_targets": len(holdout_target_set) == HOLDOUT_SIZE,
        "dev_scenario_mix_is_exact": dict(actual_dev_scenarios) == _scenario_counts(DEV_SIZE),
        "holdout_scenario_mix_is_exact": dict(actual_holdout_scenarios)
        == _scenario_counts(HOLDOUT_SIZE),
        "all_target_overlaps_are_zero": all(count == 0 for count in overlap_counts.values()),
    }
    if not all(checks.values()):
        failed = ", ".join(name for name, passed in checks.items() if not passed)
        raise AssertionError(f"Generated dataset failed checks: {failed}")

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "generator": {
            "path": Path(__file__).relative_to(PROJECT_ROOT).as_posix(),
            "sha256": _sha256_file(Path(__file__)),
            "seed": str(args.seed),
        },
        "inputs": {
            "catalog": {
                "path": catalog_path.as_posix(),
                "sha256": _sha256_file(catalog_path),
                "row_count": len(catalog_records),
                "unique_parent_asin_count": len(catalog_by_asin),
            },
            "public_set": {
                "path": public_path.as_posix(),
                "sha256": _sha256_file(public_path),
                "row_count": len(public_samples),
                "unique_target_count": len(public_targets),
            },
            "private_labels_read": False,
        },
        "selection": {
            "minimum_distinct_intent_constraints": MIN_DISTINCT_CONSTRAINTS,
            "products_after_public_target_exclusion": len(catalog_by_asin) - len(public_targets),
            "eligible_product_count": len(eligible),
            "selected_target_count": required_targets,
        },
        "splits": {
            "dev": _split_manifest(dev_records, dev_path, dev_bytes),
            "holdout": _split_manifest(holdout_records, holdout_path, holdout_bytes),
        },
        "overlap_counts": overlap_counts,
        "checks": {**checks, "all_checks_pass": all(checks.values())},
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")

    _atomic_write(dev_path, dev_bytes)
    _atomic_write(holdout_path, holdout_bytes)
    _atomic_write(manifest_path, manifest_bytes)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build deterministic public-target-disjoint sessions from the frozen "
            "official catalog."
        )
    )
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--public-set", default="data/public_set.jsonl")
    parser.add_argument("--output-dir", default="data/unseen_eval")
    parser.add_argument(
        "--seed",
        default="techjam-unseen-v1",
        help="Deterministic split seed. Change it only before defining a fresh holdout.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing generated dev/holdout set and manifest.",
    )
    return parser.parse_args()


def main() -> None:
    manifest = build(parse_args())
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
