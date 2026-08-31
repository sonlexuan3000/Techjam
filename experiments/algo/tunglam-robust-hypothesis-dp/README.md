# Algorithm candidate: `tunglam-robust-hypothesis-dp`

- Owner: Tung Lam Nguyen
- Base commit: `8088fb1`
- Status: evaluated prototype
- Entrypoint: `entrypoint.py`

## Hypothesis

Do not treat the first-message wrapper as proof of the future scenario. Keep a
posterior over Buying, Browsing, Intent Override, and Boundary until the
conversation itself resolves it. Recommendations before turn four are handled
in two worlds:

1. normal/scored world: reaching the next turn rejects the shown products;
2. pending-override world: the same products remain in reversible history and
   are restored if an explicit override actually arrives.

This removes the exact-format dependency behind the old pre-override Top-1
guard. An initial preference raises the probability of Intent Override but can
never make it 100%.

For value-level paraphrases, a dependency-free semantic alias/token matcher
creates a focus tier. It never changes eligibility: the original trusted
universe remains available as recovery if semantic matching is wrong.

## Scope

- Subclasses the integrated inverse-DP implementation; no shared file changes.
- Uses the fixed scenario mix only as a prior.
- Confirms Intent Override only on an observed override event.
- Eliminates the pending override branch after a non-override turn four.
- Adds conservative aliases such as:
  - `not wet in rain <-> water resistant <-> waterproof`;
  - `good grip <-> rubber sole <-> traction`;
  - `cushioned <-> comfortable`.
- Uses the existing offline review prior and finite-horizon DP.
- Standard library only; no API or model tokens.

## Reproduction

```bash
make setup
make unseen-data

.venv/bin/python -m unittest discover \
  -s experiments/algo/tunglam-robust-hypothesis-dp/tests -v

make evaluate-candidate-dev \
  ENTRYPOINT=experiments/algo/tunglam-robust-hypothesis-dp/entrypoint.py

.venv/bin/python scripts/run_paraphrase_stress_eval.py \
  --catalog data/catalog.jsonl \
  --dataset data/unseen_eval/dev_set.jsonl \
  --output data/unseen_eval/robust_hypothesis_wrapper_results.json \
  --entrypoint experiments/algo/tunglam-robust-hypothesis-dp/entrypoint.py

.venv/bin/python \
  experiments/algo/tunglam-robust-hypothesis-dp/tools/evaluate_semantic_stress.py \
  --catalog data/catalog.jsonl \
  --dataset data/unseen_eval/dev_set.jsonl \
  --output data/unseen_eval/robust_hypothesis_semantic_results.json \
  --entrypoint experiments/algo/tunglam-robust-hypothesis-dp/entrypoint.py
```

## Safety properties

- Initial wording is likelihood evidence, not a scenario label.
- An explicit override is the only event that confirms Intent Override.
- Products rejected in the scored-world branch are recoverable on the first
  override.
- Semantic matches define recommendation focus, not permanent deletion.
- Unknown paraphrases fall back to the existing recovery schedule.

## Results

### Official-format generated dev (2,000 sessions)

| Candidate | HR@10 | MRR | MTTC | Technical score |
|---|---:|---:|---:|---:|
| Integrated inverse-DP | 0.9945 | 0.978687 | 2.6200 | 0.958456 |
| This candidate | 0.9945 | 0.978687 | 2.6200 | 0.958456 |

All 2,000 per-session outcomes `(hit, first turn, rank)` are identical. The
wrapper-only paraphrase stress run is also identical. Therefore removing the
released scenario label did not cost score on the known protocol.

### Development-only semantic stress (2,000 sessions)

The stress script deterministically replaces selected catalog values with
meaning-preserving phrases such as `water resistant -> not wet in rain` and
`rubber sole -> good traction`. It changed a message before completion in 366
sessions. This is a robustness probe, not organizer data.

| Candidate | HR@10 | MRR | MTTC | Technical score |
|---|---:|---:|---:|---:|
| Integrated inverse-DP | 0.9905 | 0.944987 | 2.6695 | 0.945356 |
| This candidate | 0.9905 | 0.952083 | 2.6840 | 0.947195 |

On the 366 actually transformed sessions, MRR increases from `0.792066` to
`0.830837`, while HR@10 remains `0.978142`. Across all 2,000 sessions there are
27 paired improvements, 6 regressions, and 1,967 unchanged outcomes. A
5,000-resample paired bootstrap gives a 95% interval of
`[+0.000969, +0.002732]` for the technical-score delta; the observed delta is
`+0.001839`.

The MRR gain comes with a small MTTC regression (`+0.0145` turns overall).
The first broad semantic-focus prototype performed worse because generic
concepts could hide the recovery tier. The implementation now promotes a
semantic focus only when the intersection is non-empty, matches every semantic
clue, and contains at most 25 products.

### Startup cost

Measured in fresh local Python processes on the same catalog:

| Candidate | Construction time | Peak RSS increase |
|---|---:|---:|
| Integrated inverse-DP | 6.63 s | 193.59 MiB |
| This candidate | 8.27 s | 193.95 MiB |

The semantic index stores only the 11 canonical alias concepts, covering
12,303 products, instead of duplicating every catalog metadata token.

## Limitations

- The alias table is deliberately small and is not general language
  understanding.
- The `25`-candidate semantic-focus gate was selected on the development
  stress test and can itself overfit. It should be validated on a separately
  generated or held-out paraphrase set before integration.
- Scenario probabilities currently drive state/rollback and diagnostics; the
  finite-horizon DP still optimizes the scoreable branch.
- The card construction, two-value reveal order, and `other` transition model
  remain inherited assumptions.
