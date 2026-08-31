#!/usr/bin/env python3
"""Serve the local TechJam session picker and conversation simulator.

The server intentionally uses only the Python standard library. It loads one
candidate agent at startup, runs the evaluator's customer policy for a selected
evaluation session, and returns a product-enriched transcript for the browser
to play back.
"""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
import mimetypes
from pathlib import Path
import sys
import threading
import time
import traceback
from typing import Any
from urllib.parse import urlparse
import uuid


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluator.local_evaluator import (  # noqa: E402
    MAX_TURNS,
    TOP_K,
    coarse_category,
    customer_reply,
    initial_message,
    load_jsonl,
    materialize_hidden_fields,
    normalize_recommendations,
)
from scripts.evaluate_candidate import load_candidate  # noqa: E402


DEFAULT_ENTRYPOINT = (
    PROJECT_ROOT / "experiments/algo/tunglam-inverse-dp-review-prior/entrypoint.py"
)
DEFAULT_CANDIDATE_NAME = "Offline review-prior inverse-DP · production"
DEFAULT_CATALOG = PROJECT_ROOT / "data/catalog.jsonl"
DEFAULT_DATASET = PROJECT_ROOT / "data/public_set.jsonl"
DEFAULT_GENERATED_DATASET = PROJECT_ROOT / "data/unseen_eval/dev_set.jsonl"
DEFAULT_GENERATED_SESSION_LIMIT = 20

SESSION_SOURCE_FIELD = "_frontend_dataset_source"
SCENARIO_DIFFICULTY = {
    "buying": "easy",
    "browsing": "medium",
    "intent_override": "hard",
    "boundary": "medium",
}


class UnknownSessionError(LookupError):
    """Raised when a requested picker session does not exist."""


def _list_text(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    if value not in (None, ""):
        return [str(value)]
    return []


def product_view(product: dict[str, Any]) -> dict[str, Any]:
    """Keep only catalog fields needed by a compact recommendation card."""

    categories = _list_text(product.get("categories"))
    features = _list_text(product.get("features"))
    return {
        "parent_asin": str(product["parent_asin"]),
        "title": str(product.get("title") or "Untitled product"),
        "price": product.get("price"),
        "category": categories[-1] if categories else "Product",
        "feature": features[0] if features else "",
        "average_rating": product.get("average_rating"),
        "rating_number": product.get("rating_number"),
        "store": str(product.get("store") or ""),
    }


def label_sessions(samples: list[dict], source: str) -> list[dict]:
    """Copy session rows and attach frontend-only dataset provenance."""

    return [{**sample, SESSION_SOURCE_FIELD: source} for sample in samples]


def select_generated_sessions(samples: list[dict], limit: int) -> list[dict]:
    """Select a deterministic scenario-proportional preview from generated dev."""

    if limit < 0:
        raise ValueError("generated session limit cannot be negative")
    if limit == 0 or not samples:
        return []

    grouped: dict[str, list[dict]] = {}
    for sample in samples:
        scenario = str(sample.get("scenario_type") or "unknown")
        grouped.setdefault(scenario, []).append(sample)
    for group in grouped.values():
        group.sort(key=lambda item: str(item.get("sample_id") or ""))

    capped_limit = min(limit, len(samples))
    total = len(samples)
    ideals = {
        scenario: capped_limit * len(group) / total
        for scenario, group in grouped.items()
    }
    quotas = {
        scenario: min(len(group), int(ideals[scenario]))
        for scenario, group in grouped.items()
    }
    remaining = capped_limit - sum(quotas.values())
    remainder_order = sorted(
        grouped,
        key=lambda scenario: (
            ideals[scenario] - quotas[scenario],
            len(grouped[scenario]),
            scenario,
        ),
        reverse=True,
    )
    while remaining:
        allocated = False
        for scenario in remainder_order:
            if quotas[scenario] >= len(grouped[scenario]):
                continue
            quotas[scenario] += 1
            remaining -= 1
            allocated = True
            if remaining == 0:
                break
        if not allocated:
            break

    selected: list[dict] = []
    for scenario, group in grouped.items():
        quota = quotas[scenario]
        # Spread the preview across the full generated split instead of taking
        # a contiguous block from the start of the file.
        selected.extend(group[index * len(group) // quota] for index in range(quota))
    selected.sort(key=lambda item: str(item.get("sample_id") or ""))
    return selected


def load_catalog_views(
    catalog_path: str | Path,
    target_ids: set[str],
) -> tuple[set[str], dict[str, list[str]], dict[str, dict], dict[str, dict]]:
    """Load lightweight display data plus full rows for session targets."""

    catalog_ids: set[str] = set()
    target_categories: dict[str, list[str]] = {}
    target_products: dict[str, dict] = {}
    product_views: dict[str, dict] = {}

    with Path(catalog_path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            product = json.loads(line)
            parent_asin = str(product["parent_asin"])
            catalog_ids.add(parent_asin)
            product_views[parent_asin] = product_view(product)
            if parent_asin in target_ids:
                target_products[parent_asin] = product
                target_categories[parent_asin] = _list_text(product.get("categories"))

    missing = target_ids - target_products.keys()
    if missing:
        preview = ", ".join(sorted(missing)[:5])
        raise ValueError(f"catalog is missing {len(missing)} session target(s): {preview}")
    return catalog_ids, target_categories, target_products, product_views


def picker_session(sample: dict[str, Any]) -> dict[str, Any]:
    """Return safe chooser metadata without the target or generated intent."""

    profile = sample.get("user_profile") if isinstance(sample.get("user_profile"), dict) else {}
    scenario = str(sample.get("scenario_type") or "unknown")
    return {
        "sample_id": str(sample.get("sample_id") or ""),
        "dataset_source": str(sample.get(SESSION_SOURCE_FIELD) or "custom"),
        "scenario_type": scenario,
        "difficulty_bucket": str(
            sample.get("difficulty_bucket") or SCENARIO_DIFFICULTY.get(scenario, "unknown")
        ),
        "category_bucket": str(sample.get("category_bucket") or "clothing"),
        "user_profile": {
            "summary": str(profile.get("summary") or "No profile summary available."),
            "preference_tags": _list_text(profile.get("preference_tags")),
            "purchase_frequency": str(profile.get("purchase_frequency") or "Unknown"),
            "rating_style": str(profile.get("rating_style") or "Unknown"),
            "average_prior_rating": profile.get("average_prior_rating"),
        },
    }


class SimulationService:
    """Serialize access to one stateful candidate and produce full transcripts."""

    def __init__(
        self,
        *,
        agent: Any,
        samples: list[dict],
        catalog_ids: set[str],
        target_categories: dict[str, list[str]],
        target_products: dict[str, dict],
        product_views: dict[str, dict],
        candidate_name: str,
    ) -> None:
        self.agent = agent
        sample_ids = [
            str(sample["sample_id"])
            for sample in samples
            if sample.get("sample_id") not in (None, "")
        ]
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("frontend session datasets contain duplicate sample IDs")
        self.samples = {
            str(sample["sample_id"]): sample
            for sample in samples
            if sample.get("sample_id") not in (None, "")
        }
        self.catalog_ids = catalog_ids
        self.target_categories = target_categories
        self.target_products = target_products
        self.product_views = product_views
        self.candidate_name = candidate_name
        self._lock = threading.Lock()

    def list_sessions(self) -> dict[str, Any]:
        sessions = [picker_session(sample) for sample in self.samples.values()]
        sessions.sort(key=lambda item: item["sample_id"])
        counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}
        for item in sessions:
            scenario = item["scenario_type"]
            counts[scenario] = counts.get(scenario, 0) + 1
            source = item["dataset_source"]
            source_counts[source] = source_counts.get(source, 0) + 1
        return {
            "sessions": sessions,
            "total": len(sessions),
            "scenario_counts": counts,
            "source_counts": source_counts,
            "candidate": self.candidate_name,
        }

    def _recommendation_views(
        self,
        ranked_ids: list[str],
        *,
        target: str,
        target_is_eligible: bool,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for rank, parent_asin in enumerate(ranked_ids, start=1):
            view = dict(
                self.product_views.get(
                    parent_asin,
                    {
                        "parent_asin": parent_asin,
                        "title": parent_asin,
                        "price": None,
                        "category": "Product",
                        "feature": "",
                        "average_rating": None,
                        "rating_number": None,
                        "store": "",
                    },
                )
            )
            view["rank"] = rank
            view["is_target"] = target_is_eligible and parent_asin == target
            result.append(view)
        return result

    def _agent_trace(self) -> dict[str, Any]:
        rank_state = getattr(self.agent, "last_rank_state", {})
        policy = getattr(self.agent, "last_recommendation_policy", {})
        if not isinstance(rank_state, dict):
            rank_state = {}
        if not isinstance(policy, dict):
            policy = {}
        def scalar(value: object) -> str | int | float | bool | None:
            if value is None or isinstance(value, (str, int, bool)):
                return value
            if isinstance(value, float) and math.isfinite(value):
                return value
            return None

        return {
            "intent": scalar(rank_state.get("intent")),
            "mode": scalar(rank_state.get("mode")),
            "policy": scalar(policy.get("policy")),
            "k": scalar(policy.get("k")),
        }

    def _agent_algorithm_stats(self, session_id: str) -> dict[str, Any]:
        """Read the optional target-free diagnostics exposed by an agent."""

        getter = getattr(self.agent, "debug_algorithm_stats", None)
        if not callable(getter):
            return {}
        try:
            raw = getter(session_id)
        except (KeyError, RuntimeError, TypeError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}

        result: dict[str, Any] = {}
        for key in (
            "hypothesis_count",
            "focus_count",
            "recovery_count",
            "evidence_count",
            "rejected_count",
            "dp_state_count",
            "selected_k",
        ):
            value = raw.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                result[key] = value
        for key in ("retrieval_mode", "policy_mode", "prior_mode"):
            value = raw.get(key)
            if isinstance(value, str) and value:
                result[key] = value
        if isinstance(raw.get("nlp_fallback"), bool):
            result["nlp_fallback"] = raw["nlp_fallback"]
        return result

    def _calculation_stats(
        self,
        *,
        elapsed_ms: float,
        recommendation_count: int,
        new_product_count: int,
        seen_product_count: int,
        turn: int,
        algorithm_stats: dict[str, Any],
    ) -> dict[str, Any]:
        """Collect exact target-free statistics for the thinking card."""

        result = {
            "catalog_products": len(self.catalog_ids),
            "shortlist_size": recommendation_count,
            "new_products": new_product_count,
            "products_shown": seen_product_count,
            "elapsed_ms": round(max(0.0, elapsed_ms), 2),
            "turn": turn,
        }
        result.update(algorithm_stats)
        result.setdefault("selected_k", recommendation_count)
        return result

    def simulate(self, sample_id: str) -> dict[str, Any]:
        sample = self.samples.get(sample_id)
        if sample is None:
            raise UnknownSessionError(f"unknown session: {sample_id}")

        # The candidate exposes mutable session/debug state. A single lock also
        # keeps each browser request as one uninterrupted evaluator-style run.
        with self._lock:
            return self._simulate_locked(sample)

    def _simulate_locked(self, sample: dict[str, Any]) -> dict[str, Any]:
        simulation_id = f"frontend_{uuid.uuid4().hex}"
        # Full transcripts are produced under a service-wide lock, so one
        # stable candidate session slot can be safely reset and reused. This
        # avoids retaining a new Agent SessionState for every replay.
        agent_session_id = "frontend_preview"
        target = str(sample["ground_truth"]["parent_asin"])
        intent_card, behavior = materialize_hidden_fields(sample, self.target_products)
        effective_sample = {**sample, "intent_card": intent_card, "behavior": behavior}

        self.agent.reset(agent_session_id, sample["user_profile"])
        disclosed: set[str] = set()
        boundary_used = False
        override_applied = sample["scenario_type"] != "intent_override"
        user_message = initial_message(
            effective_sample,
            coarse_category(self.target_categories.get(target, [])),
            disclosed,
        )

        transcript: list[dict[str, Any]] = []
        hit_turn: int | None = None
        best_rank: int | None = None
        unique_products: set[str] = set()

        for turn in range(1, MAX_TURNS + 1):
            warning: str | None = None
            response_started = time.perf_counter()
            try:
                response = self.agent.respond(agent_session_id, user_message, turn, TOP_K)
            except Exception:  # Keep the viewer alive like the evaluator.
                traceback.print_exc()
                response = {"message": "", "ask_attribute": None, "recommendations": []}
                warning = "The agent raised an exception on this turn. See the server log for details."
            response_elapsed_ms = (time.perf_counter() - response_started) * 1_000
            if not isinstance(response, dict) or not isinstance(response.get("message"), str):
                response = {"message": "", "ask_attribute": None, "recommendations": []}
                warning = warning or "Agent returned an invalid response."

            ranked_ids = normalize_recommendations(response.get("recommendations"), self.catalog_ids)
            new_product_count = len(set(ranked_ids) - unique_products)
            unique_products.update(ranked_ids)
            eligible_hit = override_applied and target in ranked_ids
            if eligible_hit:
                best_rank = ranked_ids.index(target) + 1
                hit_turn = turn

            ask_attribute = response.get("ask_attribute")
            if not isinstance(ask_attribute, str):
                ask_attribute = None
            assistant_message = str(response.get("message") or "")
            trace = self._agent_trace() if warning is None else {}
            algorithm_stats = (
                self._agent_algorithm_stats(agent_session_id)
                if warning is None
                else {}
            )
            transcript.append(
                {
                    "turn": turn,
                    "user": {"message": user_message},
                    "assistant": {
                        "message": assistant_message,
                        "ask_attribute": ask_attribute,
                        "recommendations": self._recommendation_views(
                            ranked_ids,
                            target=target,
                            target_is_eligible=override_applied,
                        ),
                        "trace": trace,
                        "calculation": self._calculation_stats(
                            elapsed_ms=response_elapsed_ms,
                            recommendation_count=len(ranked_ids),
                            new_product_count=new_product_count,
                            seen_product_count=len(unique_products),
                            turn=turn,
                            algorithm_stats=algorithm_stats,
                        ),
                        "warning": warning,
                    },
                    "hit": eligible_hit,
                    "target_rank": best_rank if eligible_hit else None,
                }
            )

            if eligible_hit or turn == MAX_TURNS:
                break

            override = effective_sample.get("behavior", {}).get("override") or {}
            if not override_applied and turn + 1 == int(override.get("turn", 3)):
                override_applied = True
                new_value = str(override.get("new_value", ""))
                if new_value:
                    disclosed.add(new_value)
                user_message = str(
                    override.get("message", "Actually, please ignore my earlier preference.")
                )
            else:
                user_message, boundary_used = customer_reply(
                    effective_sample,
                    ask_attribute,
                    disclosed,
                    boundary_used,
                )

        target_view = dict(self.product_views[target])
        target_view["rank"] = best_rank
        return {
            "simulation_id": simulation_id,
            "candidate": self.candidate_name,
            "session": picker_session(sample),
            "transcript": transcript,
            "outcome": {
                "status": "hit" if hit_turn is not None else "miss",
                "hit": hit_turn is not None,
                "first_hit_turn": hit_turn,
                "best_rank": best_rank,
                "turns": len(transcript),
                "unique_products": len(unique_products),
                "target": target_view,
            },
        }


class FrontendRequestHandler(BaseHTTPRequestHandler):
    """HTTP routes for static assets and the two small JSON APIs."""

    service: SimulationService
    static_root = STATIC_ROOT
    server_version = "TechJamFrontend/1.0"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, format_string: str, *args: object) -> None:
        sys.stderr.write(f"[frontend] {self.address_string()} {format_string % args}\n")

    def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        try:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError):
            traceback.print_exc()
            status = HTTPStatus.INTERNAL_SERVER_ERROR
            body = json.dumps({"error": "The server could not serialize its response."}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, message: str, status: HTTPStatus) -> None:
        self._send_json({"error": message}, status)

    def _read_json(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if length <= 0 or length > 1_000_000:
            raise ValueError("request body must be between 1 byte and 1 MB")
        try:
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("request body must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json({"status": "ok", "candidate": self.service.candidate_name})
            return
        if path == "/api/sessions":
            self._send_json(self.service.list_sessions())
            return

        static_files = {
            "/": "index.html",
            "/index.html": "index.html",
            "/styles.css": "styles.css",
            "/app.js": "app.js",
        }
        filename = static_files.get(path)
        if filename is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        file_path = self.static_root / filename
        body = file_path.read_bytes()
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if urlparse(self.path).path != "/api/simulate":
            self._send_error_json("Unknown API route.", HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self._read_json()
            sample_id = payload.get("sample_id")
            if not isinstance(sample_id, str) or not sample_id.strip():
                raise ValueError("sample_id must be a non-empty string")
        except ValueError as exc:
            self._send_error_json(str(exc), HTTPStatus.BAD_REQUEST)
            return
        except TimeoutError:
            self._send_error_json("Timed out while reading the request body.", HTTPStatus.REQUEST_TIMEOUT)
            return

        try:
            result = self.service.simulate(sample_id.strip())
        except UnknownSessionError as exc:
            self._send_error_json(str(exc), HTTPStatus.NOT_FOUND)
            return
        except Exception:  # Make startup/demo failures visible to the UI.
            traceback.print_exc()
            self._send_error_json(
                "Simulation failed. Check the local server log for details.",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return
        self._send_json(result)


def make_handler(service: SimulationService) -> type[FrontendRequestHandler]:
    class BoundFrontendRequestHandler(FrontendRequestHandler):
        pass

    BoundFrontendRequestHandler.service = service
    return BoundFrontendRequestHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--generated-dataset", default=str(DEFAULT_GENERATED_DATASET))
    parser.add_argument(
        "--generated-limit",
        type=int,
        default=DEFAULT_GENERATED_SESSION_LIMIT,
        help="number of deterministic generated-dev sessions to add (0 disables them)",
    )
    parser.add_argument("--entrypoint", default=str(DEFAULT_ENTRYPOINT))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    catalog_path = Path(args.catalog).resolve()
    dataset_path = Path(args.dataset).resolve()
    generated_dataset_path = Path(args.generated_dataset).resolve()
    entrypoint_path = Path(args.entrypoint).resolve()

    if not catalog_path.is_file():
        raise SystemExit(
            f"Catalog not found at {catalog_path}. Run `make setup` or download data/catalog.jsonl first."
        )
    if not dataset_path.is_file():
        raise SystemExit(f"Session dataset not found at {dataset_path}.")
    if args.generated_limit < 0:
        raise SystemExit("--generated-limit cannot be negative.")

    print(f"Loading sessions from {dataset_path} …", flush=True)
    primary_source = "public" if dataset_path == DEFAULT_DATASET.resolve() else "custom"
    samples = label_sessions(load_jsonl(dataset_path), primary_source)
    if args.generated_limit and generated_dataset_path != dataset_path:
        if generated_dataset_path.is_file():
            generated_samples = select_generated_sessions(
                load_jsonl(generated_dataset_path),
                args.generated_limit,
            )
            samples.extend(label_sessions(generated_samples, "generated_dev"))
            print(
                f"Added {len(generated_samples)} generated-dev preview sessions from "
                f"{generated_dataset_path}.",
                flush=True,
            )
        else:
            print(
                f"Generated-dev dataset not found at {generated_dataset_path}; "
                "continuing without preview sessions. Run `make unseen-data` to create it.",
                flush=True,
            )
    target_ids = {str(sample["ground_truth"]["parent_asin"]) for sample in samples}
    print(f"Loading {catalog_path.name} for product cards …", flush=True)
    catalog_ids, target_categories, target_products, product_views = load_catalog_views(
        catalog_path, target_ids
    )
    print(f"Building candidate index from {entrypoint_path} …", flush=True)
    agent, resolved_entrypoint = load_candidate(entrypoint_path, str(catalog_path))
    service = SimulationService(
        agent=agent,
        samples=samples,
        catalog_ids=catalog_ids,
        target_categories=target_categories,
        target_products=target_products,
        product_views=product_views,
        candidate_name=(
            DEFAULT_CANDIDATE_NAME
            if resolved_entrypoint == DEFAULT_ENTRYPOINT.resolve()
            else resolved_entrypoint.parent.name
        ),
    )

    server = HTTPServer((args.host, args.port), make_handler(service))
    display_host = "localhost" if args.host in {"127.0.0.1", "0.0.0.0"} else args.host
    print(f"Conversation viewer ready at http://{display_host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping conversation viewer.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
