# Official-catalog unseen evaluation

This directory is reserved for deterministic synthetic evaluation sessions built from products in the frozen 50,000-product catalog that are not targets in the 200-row public set.

The committed default seed is visible to the whole team. Therefore both splits
are shared regression data, not a secret private-test estimate. An evaluation
owner may keep a different seed uncommitted for a genuinely internal aggregate
freeze check.

The builder:

- reads `data/catalog.jsonl` and `data/public_set.jsonl`;
- verifies that the public set contains exactly 200 distinct targets;
- excludes every public target;
- calls the official `evaluator.local_evaluator.intent_card` function and retains products with at least four distinct generated constraints;
- selects 2,000 unique dev targets and 800 different second-split targets;
- gives each split the official 40% Buying, 40% Browsing, 15% Intent Override, and 5% Boundary mix;
- creates aggregate profiles using an RNG that never receives a target ASIN or product metadata;
- records source/output checksums, split counts, and overlap checks in `manifest.json`.

It does not access organizer-private labels. These sessions are synthetic robustness tests, not a reconstruction or estimate of the private target set.

## Generate

From the repository root:

```bash
python scripts/build_unseen_official_sessions.py \
  --seed techjam-unseen-v1
```

This creates ignored local files:

```text
data/unseen_eval/dev_set.jsonl
data/unseen_eval/holdout_set.jsonl
data/unseen_eval/manifest.json
```

Generation refuses to overwrite those files unless `--force` is passed. Keep the
default seed stable while comparing experiments.

## Evaluate

Use dev while implementing:

```bash
python evaluator/local_evaluator.py \
  --catalog data/catalog.jsonl \
  --dataset data/unseen_eval/dev_set.jsonl \
  --output data/unseen_eval/dev_results.json
```

For a cleaner regression check, freeze and commit the agent before running the
second split (the filename remains `holdout_set.jsonl` for generator compatibility):

```bash
python evaluator/local_evaluator.py \
  --catalog data/catalog.jsonl \
  --dataset data/unseen_eval/holdout_set.jsonl \
  --output data/unseen_eval/holdout_results.json
```

For team discipline, commit a candidate version before running the second split
and avoid tuning from individual failures. The generated data and results stay
untracked so target mappings are not accidentally published.

## Paraphrase stress test

The official local simulator uses fixed message wrappers. To detect a parser
that has memorized those wrappers, run the separate deterministic stress test:

```bash
python scripts/run_paraphrase_stress_eval.py \
  --catalog data/catalog.jsonl \
  --dataset data/public_set.jsonl \
  --output data/unseen_eval/public_paraphrase_stress_results.json
```

This preserves targets, constraint strings, disclosure order, scenario timing,
and scoring, but changes the surrounding natural language. Its result is a
robustness diagnostic, not an official or private-score estimate.
