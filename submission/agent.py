"""Competition-facing entry file exporting the selected ``Agent`` class."""

from __future__ import annotations

from pathlib import Path
import sys

try:
    from .src.shopping_copilot.core import Agent as _InverseDPAgent
except ImportError:  # Support harnesses that load this entry file by path.
    _SOURCE_ROOT = Path(__file__).resolve().parent / "src"
    if str(_SOURCE_ROOT) not in sys.path:
        sys.path.insert(0, str(_SOURCE_ROOT))
    from shopping_copilot.core import Agent as _InverseDPAgent


_PRIOR_PATH = Path(__file__).resolve().parent / "data" / "review_prior.tsv"


class Agent(_InverseDPAgent):
    """Inverse-card agent using the bundled aggregate review-count prior."""

    def __init__(self, catalog_path: str | Path = "data/catalog.jsonl") -> None:
        super().__init__(
            catalog_path=catalog_path,
            prior_field="verified_reviews_365d",
            prior_smoothing=1.0,
            prior_path=_PRIOR_PATH,
        )


__all__ = ["Agent"]
