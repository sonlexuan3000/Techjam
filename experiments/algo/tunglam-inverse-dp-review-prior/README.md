# Algorithm candidate: `tunglam-inverse-dp-review-prior`

- Owner: Tung Lam Nguyen
- Base commit: `c5987f5`
- Status: draft; reproducible, pending public-firewall and data-governance review
- Primary entrypoint: `entrypoint.py`

## Hypothesis

The released evaluator deterministically derives up to two hard constraints and
two soft preferences from each product card, and an `other` reply discloses up
to two still-hidden values. Reconstructing the same card for every catalog
product gives a small set of explicit hypotheses after each reply. A finite
horizon decision policy can then choose the recommendation cutoff `k` that
maximizes expected technical score instead of using a fixed Top-K schedule.

Inside a surviving set, the candidate estimates

```text
P(product=x | evidence) proportional to verified_reviews_365d(x) + 1
```

and normalizes those weights locally. The `+1` is Laplace smoothing: a product
with no observed review in the window remains possible.

## Scope

- Filtering: reconstruct the evaluator-style product card, replay all observed
  hard and soft evidence, and exclude explicitly rejected recommendations.
- Recovery: if soft evidence empties the set, restore only same-category
  products that still satisfy every observed hard constraint. A hard mismatch
  is never restored.
- Ranking: sort by the local posterior mass from the offline review prior, with
  deterministic ASIN tie-breaking.
- Question policy: ask `other`, which is the most informative field under the
  released reply protocol.
- Top-K policy: dynamic programming evaluates every
  `k in [1, min(10, candidates)]` at each turn. It models immediate rank reward,
  the next two-value disclosure, and the released Boundary probability.
- NLP boundary: `src/preprocessing.py` adapts wrapper paraphrases through the
  shared `starter.parser`; filtering, ranking, and DP stay isolated here.
- Dependencies: Python standard library only. No model, API key, network call,
  or runtime token cost.

This is intentionally an algorithm experiment, not a replacement for
`starter/agent.py`.

## Entrypoint and reproduction

From the repository root:

```bash
make setup
make test
make unseen-data

.venv/bin/python -m unittest discover \
  -s experiments/algo/tunglam-inverse-dp-review-prior/tests -v

# Current shared baseline
make evaluate-unseen-dev

# This candidate
make evaluate-candidate-dev \
  ENTRYPOINT=experiments/algo/tunglam-inverse-dp-review-prior/entrypoint.py

# Uniform-prior ablation
.venv/bin/python scripts/evaluate_candidate.py \
  --entrypoint experiments/algo/tunglam-inverse-dp-review-prior/entrypoint_uniform.py \
  --catalog data/catalog.jsonl \
  --dataset data/unseen_eval/dev_set.jsonl \
  --output data/unseen_eval/candidate_uniform_results.json

# Filter-survival and local runtime diagnostics
.venv/bin/python \
  experiments/algo/tunglam-inverse-dp-review-prior/tools/diagnostics.py

# Candidate-pool sizes at each evidence step
.venv/bin/python \
  experiments/algo/tunglam-inverse-dp-review-prior/tools/pool_diagnostics.py
```

Do not run the organizer public 200 for selecting or tuning this candidate. The
metrics below use the deterministic `techjam-unseen-v1` generated-dev split.

## Results

| Suite | HR@10 | MRR | MTTC | Technical Score |
|---|---:|---:|---:|---:|
| Generated-dev team baseline | 0.9865 | 0.852769 | 2.7010 | 0.915061 |
| Generated-dev candidate | 0.9945 | 0.978687 | 2.6200 | 0.958456 |
| Absolute delta | +0.0080 | +0.125918 | -0.0810 | +0.043395 |

Scenario breakdown on the same 2,000 sessions:

| Scenario | Sessions | Baseline HR / MRR / MTTC | Candidate HR / MRR / MTTC |
|---|---:|---:|---:|
| Boundary | 100 | 0.9900 / 0.680345 / 3.4100 | 0.9900 / 0.969167 / 3.5600 |
| Browsing | 800 | 0.98875 / 0.854648 / 2.6775 | 0.99625 / 0.980649 / 2.6150 |
| Buying | 800 | 0.98125 / 0.874412 / 2.24375 | 0.99125 / 0.976026 / 2.0800 |
| Intent Override | 300 | 0.993333 / 0.847520 / 3.746667 | 1.0000 / 0.983722 / 3.7600 |

Diagnostics over the candidate's 5,229 evaluated turns:

- Target Survival Rate: `1.0000`.
- False Elimination Rate: `0.0000`.
- Definition: a session survives only if its target remains in
  `current_candidates` after every response up to termination; any absence at
  any checkpoint counts as a false-elimination session.
- Mean / p95 `respond` latency: `34.53 ms / 156.78 ms`.
- Startup time: `3.994 s`.
- Peak RSS increase during startup: `151.77 MiB`.
- Runtime token usage: `0`.

Runtime diagnostics were measured locally on an Apple M4 and are machine- and
load-dependent.

Candidate-pool changes across the same generated-dev messages (means, with
medians in parentheses):

| Evidence step | Transitions | Before | After |
|---|---:|---:|---:|
| Initial category only | 900 | 50,000 (50,000) | 329.998 (232) |
| Initial category + one hard constraint | 800 | 50,000 (50,000) | 81.737 (16) |
| Initial category + old soft preference | 300 | 50,000 (50,000) | 14.137 (1) |
| First disclosure, up to two values | 2,000 | 183.315 (47) | 10.511 (1) |
| Second disclosure, up to two values | 2,000 | 10.511 (1) | 4.574 (1) |
| Intent override replay | 300 | 3.330 (1) | 3.330 (1) |

No-preference messages are excluded because they add no constraint. The
override row does not shrink the pool on average because the old preference is
removed before the new target-grounded value is replayed.

## Ablation

| Prior | HR@10 | MRR | MTTC | Technical Score |
|---|---:|---:|---:|---:|
| Equal probability per surviving product | 0.9935 | 0.977300 | 2.6255 | 0.957430 |
| `verified_reviews_365d + 1` | 0.9945 | 0.978687 | 2.6200 | 0.958456 |

The review prior improves mean score by `0.001026`, but the paired 2,000-case
bootstrap 95% interval for its reward difference includes zero
(`[-0.003606, 0.001461]`). Therefore the review prior is a small, uncertain
gain; the large delta from the team baseline should not be attributed to
popularity data alone. The inverse-card filtering and DP policy are bundled in
this candidate and still need separate causal ablations before integration.

## Failure analysis and trade-offs

- The candidate misses 11/2,000 sessions: 1 Boundary, 3 Browsing, and 7 Buying;
  it misses no Intent Override session in this split.
- Boundary MTTC regresses from `3.41` to `3.56` even though Boundary MRR
  improves. The DP sometimes waits for information longer than the baseline.
- The policy explicitly models the released simulator's card construction,
  two-value `other` reply, Boundary rate, ten-turn horizon, and score formula.
  This is the main overfitting risk: private or human reply behavior may differ.
- Development context included earlier exploratory inspection of the released
  public evaluator behavior. No organizer-public metric or per-case result is
  reported here, and all comparisons in this README use generated-dev, but this
  is not a clean blind candidate under the repository's newer public-firewall
  rule. Reviewers should treat it as hypothesis-generating until the evaluation
  owner decides whether it is eligible for winner selection.
- Wrapper paraphrases are supported, but semantic value rewriting such as
  `not wet in rain -> waterproof` is outside this adapter.
- Soft-conflict recovery preserves hard constraints and rejected-product state,
  but it cannot recover when a genuinely hard phrase was parsed incorrectly.
- The 365-day review aggregate is a proxy for purchase probability, not sales
  ground truth. Its weak ablation result is reported rather than hidden.

## Offline review prior and data governance

`data/review_prior.tsv` contains exactly one aggregate count per catalog
`parent_asin`; it contains no user ID, review text, timestamp, image, or
individual review record. It was derived from the McAuley Lab Amazon Reviews
2023 `Clothing_Shoes_and_Jewelry` review file using the exclusive
`2023-10-01` cutoff. Its SHA-256 is
`45bc7fa2053e55c2bdef7454c2461886a02ef25d0d25339d5d51a5affaafcfd6`.

See `data/README.md` for full provenance and extraction commands. The source
dataset terms and the repository's `DATA_ATTRIBUTION.md` apply. Organizer/team
approval should be obtained before this derived asset is merged into the final
submission.

## Files

- `entrypoint.py`: official isolated `build_agent(catalog_path)` adapter.
- `entrypoint_uniform.py`: equal-probability ablation adapter.
- `src/agent.py`: product-card reconstruction, filtering, posterior ranking,
  soft fallback, and finite-horizon DP.
- `src/preprocessing.py`: thin paraphrase adapter over the shared parser.
- `data/review_prior.tsv`: compact runtime review aggregate.
- `data/README.md`: data provenance, checksums, governance, and reproduction.
- `tests/test_agent.py`: focused unit tests for inverse filtering, override,
  DP cutoff, prior loading, fallback invariants, and paraphrase routing.
- `tools/diagnostics.py`: reproducible survival, latency, startup, and memory
  measurements.
- `tools/pool_diagnostics.py`: candidate-pool size before and after each
  protocol evidence step.
- `tools/review_prior/`: resumable extractor, native scanner, and compact TSV
  exporter used to reproduce the offline prior.
