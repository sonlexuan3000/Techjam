#!/usr/bin/env python3
"""Serve the local TechJam session picker and conversation simulator.

The server intentionally uses only the Python standard library.  It loads one
candidate agent at startup, runs the evaluator's customer policy for a selected
public session, and returns a product-enriched transcript for the browser to
play back.
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
    return {
        "sample_id": str(sample.get("sample_id") or ""),
        "scenario_type": str(sample.get("scenario_type") or "unknown"),
        "difficulty_bucket": str(sample.get("difficulty_bucket") or "unknown"),
        "category_bucket": str(sample.get("category_bucket") or "unknown"),
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
        for item in sessions:
            scenario = item["scenario_type"]
            counts[scenario] = counts.get(scenario, 0) + 1
        return {
            "sessions": sessions,
            "total": len(sessions),
            "scenario_counts": counts,
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

    def _agent_trace(
        self,
        session_id: str,
        recommendation_count: int,
    ) -> dict[str, Any]:
        """Return read-only decision state without evaluator-only target data."""

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

        legacy_trace = {
            "intent": scalar(rank_state.get("intent")),
            "mode": scalar(rank_state.get("mode")),
            "policy": scalar(policy.get("policy")),
            "k": scalar(policy.get("k")),
        }

        algorithm_stats: dict[str, Any] = {}
        stats_getter = getattr(self.agent, "debug_algorithm_stats", None)
        if callable(stats_getter):
            try:
                candidate_stats = stats_getter(session_id)
                if isinstance(candidate_stats, dict):
                    algorithm_stats = candidate_stats
            except Exception:
                # Optional observability must never alter the simulated run.
                algorithm_stats = {}

        sessions = getattr(self.agent, "sessions", None)
        state = sessions.get(session_id) if isinstance(sessions, dict) else None
        if state is None and not algorithm_stats:
            return legacy_trace

        def count(name: str) -> int:
            value = getattr(state, name, ())
            return len(value) if isinstance(value, (dict, list, set, tuple)) else 0

        nlp_fallback = bool(
            algorithm_stats.get("nlp_fallback", getattr(state, "nlp_fallback", False))
        )
        focus_count = algorithm_stats.get("focus_count", count("focus_candidates"))
        trusted_count = algorithm_stats.get("recovery_count", count("trusted_universe"))
        active_count = algorithm_stats.get("hypothesis_count")
        if not isinstance(active_count, int) or isinstance(active_count, bool) or active_count < 0:
            active_count = focus_count if focus_count else count("current_candidates")
        if nlp_fallback and not active_count:
            active_count = trusted_count

        debug: dict[str, Any] = {}
        debug_state = getattr(self.agent, "debug_state", None)
        if callable(debug_state):
            try:
                candidate_debug = debug_state(session_id)
                if isinstance(candidate_debug, dict):
                    debug = candidate_debug
            except Exception:
                # Observability must never alter or break the evaluator-style run.
                debug = {}

        evidence: list[dict[str, str]] = []
        for clue in debug.get("current_intent", []):
            if not isinstance(clue, dict) or not clue.get("active", True):
                continue
            clue_text = str(clue.get("text") or "").strip()
            if not clue_text:
                continue
            evidence.append(
                {
                    "text": clue_text,
                    "slot": str(clue.get("slot") or "feature"),
                    "kind": "active",
                }
            )
        for clue in debug.get("negative_evidence", []):
            if not isinstance(clue, dict):
                continue
            clue_text = str(clue.get("text") or "").strip()
            if clue_text:
                evidence.append(
                    {
                        "text": clue_text,
                        "slot": str(clue.get("slot") or "feature"),
                        "kind": "negative",
                    }
                )

        scenario = scalar(getattr(state, "scenario", None))
        override_applied = bool(getattr(state, "override_applied", True))
        retrieval_mode = str(algorithm_stats.get("retrieval_mode") or "")
        policy_mode = str(algorithm_stats.get("policy_mode") or "")
        if retrieval_mode in {"focus_tier", "recovery_tier", "lexical_fallback"}:
            route = "nlp-recovery"
        else:
            route = "nlp-recovery" if nlp_fallback else "exact-inverse"
        phase = (
            "intent-override"
            if policy_mode == "override_guard"
            or (scenario == "intent_override" and not override_applied)
            else None
        )

        return {
            "route": route,
            "phase": phase,
            "scenario": scenario,
            "k": recommendation_count,
            "active_candidates": active_count,
            "override_applied": override_applied,
            "evidence": evidence[-2:],
        }

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
        previous_candidate_count = len(self.catalog_ids)

        for turn in range(1, MAX_TURNS + 1):
            warning: str | None = None
            try:
                response = self.agent.respond(agent_session_id, user_message, turn, TOP_K)
            except Exception:  # Keep the viewer alive like the evaluator.
                traceback.print_exc()
                response = {"message": "", "ask_attribute": None, "recommendations": []}
                warning = "The agent raised an exception on this turn. See the server log for details."
            if not isinstance(response, dict) or not isinstance(response.get("message"), str):
                response = {"message": "", "ask_attribute": None, "recommendations": []}
                warning = warning or "Agent returned an invalid response."

            ranked_ids = normalize_recommendations(response.get("recommendations"), self.catalog_ids)
            # Capture target-free Agent state before the evaluator compares the
            # returned IDs with its hidden ground truth.
            agent_trace = (
                self._agent_trace(agent_session_id, len(ranked_ids))
                if warning is None
                else {}
            )
            if agent_trace.get("route"):
                agent_trace["previous_candidates"] = previous_candidate_count
                active_candidates = agent_trace.get("active_candidates")
                if isinstance(active_candidates, int) and active_candidates >= 0:
                    previous_candidate_count = active_candidates
            unique_products.update(ranked_ids)
            eligible_hit = override_applied and target in ranked_ids
            if eligible_hit:
                best_rank = ranked_ids.index(target) + 1
                hit_turn = turn

            ask_attribute = response.get("ask_attribute")
            if not isinstance(ask_attribute, str):
                ask_attribute = None
            assistant_message = str(response.get("message") or "")
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
                        "trace": agent_trace,
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
    parser.add_argument("--entrypoint", default=str(DEFAULT_ENTRYPOINT))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    catalog_path = Path(args.catalog).resolve()
    dataset_path = Path(args.dataset).resolve()
    entrypoint_path = Path(args.entrypoint).resolve()

    if not catalog_path.is_file():
        raise SystemExit(
            f"Catalog not found at {catalog_path}. Run `make setup` or download data/catalog.jsonl first."
        )
    if not dataset_path.is_file():
        raise SystemExit(f"Session dataset not found at {dataset_path}.")

    print(f"Loading sessions from {dataset_path} …", flush=True)
    samples = load_jsonl(dataset_path)
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
