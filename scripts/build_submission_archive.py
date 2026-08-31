#!/usr/bin/env python3
"""Build a deterministic source-only archive of the submission bundle."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUBMISSION_ROOT = PROJECT_ROOT / "submission"
REQUIRED_FILES = {
    "README.md",
    "REPORT.md",
    "agent.py",
    "requirements.txt",
    "smoke.py",
    "src/shopping_copilot/core.py",
    "src/shopping_copilot/intent_tracker.py",
    "src/shopping_copilot/parser.py",
    "src/shopping_copilot/preprocessing.py",
}
ALLOWED_SUFFIXES = {".md", ".py", ".txt"}


def bundle_files() -> list[Path]:
    files = sorted(
        path
        for path in SUBMISSION_ROOT.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix in ALLOWED_SUFFIXES
    )
    relative = {path.relative_to(SUBMISSION_ROOT).as_posix() for path in files}
    missing = REQUIRED_FILES - relative
    if missing:
        raise RuntimeError(f"submission bundle is missing required files: {sorted(missing)}")
    return files


def build_archive(output_path: Path) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in bundle_files():
            relative = path.relative_to(SUBMISSION_ROOT)
            info = zipfile.ZipInfo(
                filename=(Path("submission") / relative).as_posix(),
                date_time=(1980, 1, 1, 0, 0, 0),
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    return hashlib.sha256(output_path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "dist" / "shopping-copilot-submission.zip",
    )
    args = parser.parse_args()
    digest = build_archive(args.output)
    print(f"Built {args.output}")
    print(f"SHA-256 {digest}")


if __name__ == "__main__":
    main()
