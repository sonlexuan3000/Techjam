# Algorithm candidate: `tunglam-inverse-dp-review-prior`

- Original owner: Tung Lam Nguyen
- Original commit: `044c2fa`
- Safety-review commit: `db9aff5`
- Status: selected and integrated into `starter.agent.Agent`
- Primary entrypoint: `entrypoint.py` (offline verified-review prior)
- Ablations: `entrypoint_uniform.py`, `entrypoint_rating_number.py`

## What is preserved

The candidate reconstructs the same two-hard/two-soft intent card for every
catalog product, then replays the released conversation protocol backwards to
find products that could have produced the observed replies. Its finite-horizon
dynamic program chooses `k` for each recommendation turn instead of using a
fixed Top-K schedule.

The integration keeps the original high-value pieces:

- inverse intent-card reconstruction;
- exact hard/soft conversation replay;
- explicit rejection of products already shown on scored turns;
- hard-only recovery if an exact soft match becomes empty;
- the `other` question policy;
- finite-horizon DP over rank reward, future disclosures, Boundary probability,
  ten turns, and the requested Top-K cap.

The primary inverse-DP belief weight is `verified_reviews_365d + 1`. Review
volume controls the fixed product order and the probability mass used by the DP;
it never establishes eligibility. Catalog rating count and average rating are
deterministic tie-breaks after review weight.

## Safe NLP boundary

Raw messages that already use the released protocol stay on the original exact
inverse-DP path.

For a recognized paraphrase, the shared dependency-free `starter.parser` first
canonicalizes the wrapper. Candidates that exactly explain that canonical
transcript form a **focus tier** and still use the inverse filter plus DP. The
remaining eligible products stay in a **recovery universe**. They are not
recommended ahead of a valid focus tier, but an uncertain parse cannot delete
them permanently.

Once a session has used the paraphrase path, it never silently becomes trusted
again. A late explicit override also repairs recommendations that may have been
incorrectly marked as scored before the scenario was known; a second override
does not restore genuine scored misses.

The NLP lookup indexes only the four constraints each reconstructed card can
reveal. It does not build a second full-catalog metadata index or call an API.

This layer handles released wrappers and exact catalog values. It is not a
general semantic matcher: phrases such as `not wet in rain -> waterproof` remain
unresolved recovery-only input unless another component resolves the meaning.

## Data policy

The shipped `submission/data/review_prior.tsv` contains one product-level count
for each of the 50,000 catalog ASINs: verified Amazon Reviews 2023 records in the
365 days ending at the exclusive `2023-10-01` cutoff. Runtime weight is count
plus one. The file contains no user identifier, review text, timestamp,
individual review row, or organizer session label and is used entirely offline.

After the team confirmed that external data was permitted, the prior was
selected on the organizer-labeled public development set. The full-source
aggregate may include events from periods later treated as held out, so the
documentation does not claim temporal leakage-free evaluation. Exact source,
row counts, checksums, extraction commands, public gain, and generated-holdout
regression are all retained for auditability.

## Reproduction

The commands below exercise a compatibility alias to the integrated source.
Commit `044c2fa` preserves the original isolated review-prior candidate;
`db9aff5` records the later safety review that temporarily selected uniform
while data permission was unresolved. The current entrypoint restores the
review prior after that permission was confirmed.

From the repository root:

```bash
make setup
make unseen-data

.venv/bin/python -m unittest discover -v

.venv/bin/python -m unittest discover \
  -s experiments/algo/tunglam-inverse-dp-review-prior/tests -v

.venv/bin/python scripts/evaluate_candidate.py \
  --entrypoint experiments/algo/tunglam-inverse-dp-review-prior/entrypoint.py \
  --catalog data/catalog.jsonl \
  --dataset data/unseen_eval/dev_set.jsonl \
  --output data/unseen_eval/candidate_inverse_dp_results.json

.venv/bin/python scripts/run_paraphrase_stress_eval.py \
  --catalog data/catalog.jsonl \
  --dataset data/unseen_eval/dev_set.jsonl \
  --output data/unseen_eval/candidate_inverse_dp_wrapper_results.json \
  --entrypoint experiments/algo/tunglam-inverse-dp-review-prior/entrypoint.py
```

The generated results below use the deterministic `techjam-unseen-v1` split.
They drove algorithm selection and remain a distribution diagnostic; the final
prior itself was selected on the labeled public 200 and is reported separately.

## Results

| Generated-dev variant | HR@10 | MRR | MTTC | Technical score |
|---|---:|---:|---:|---:|
| Team baseline | 0.9865 | 0.852769 | 2.7010 | 0.915061 |
| Uniform inverse-DP | 0.9935 | 0.977300 | 2.6255 | 0.957430 |
| Catalog `rating_number` inverse-DP | 0.9935 | 0.974768 | 2.6890 | 0.955400 |
| **Offline review prior (shipped)** | **0.9945** | **0.978687** | **2.6200** | **0.958456** |

The shipped candidate improves generated Technical Score by `0.043395` over the
team baseline and by `0.001026` over uniform.

Scenario results for the shipped prior:

| Scenario | Sessions | HR@10 | MRR | MTTC |
|---|---:|---:|---:|---:|
| Boundary | 100 | 0.9900 | 0.969167 | 3.5600 |
| Browsing | 800 | 0.99625 | 0.980649 | 2.6150 |
| Buying | 800 | 0.99125 | 0.976026 | 2.0800 |
| Intent Override | 300 | 1.000000 | 0.983722 | 3.760000 |

Final prior A/B:

| Evaluation / prior | Sessions | HR@10 | MRR | MTTC | Technical score |
|---|---:|---:|---:|---:|---:|
| Public / uniform | 200 | 1.0000 | 0.997500 | 2.7950 | 0.963350 |
| Public / catalog `rating_number` | 200 | 1.0000 | 1.000000 | 2.0050 | 0.979900 |
| **Public / review prior** | **200** | **1.0000** | **1.000000** | **1.8400** | **0.983200** |
| Generated holdout / uniform | 800 | 0.9975 | 0.980420 | 2.5850 | 0.961176 |
| **Generated holdout / review prior** | **800** | **0.9925** | **0.976574** | **2.5950** | **0.957322** |

On public development the review prior is `+0.019850`; on the roughly uniform
generated holdout it is `-0.003854`. Paired public turns are 117 earlier, 82
unchanged, and one later. No private-session result is claimed.

Final integration verification recorded:

- shared suite: `45/45` passed;
- inverse-DP suite: `21/21` passed, including prior schema, smoothing, and
  hard-filter invariants;
- reconstructed cards/categories match the evaluator for all `50,000` catalog products;
- the integrated review-prior adapter matches the original `044c2fa` candidate
  session-for-session across public 200, generated development, and generated
  holdout;
- final-prior wrapper stress scores `0.958456` with identical HR/MRR/MTTC;
- all `2,000/2,000` exact-vs-wrapper session summaries match;
- packaged runtime performance is measured separately in
  `submission/REPORT.md`;
- runtime API/model/token usage: zero.

## Limitations

- The large score gain depends on the released card construction, disclosure
  order, `other` behavior, scenario model, score formula, and horizon. A private
  evaluator that changes those mechanics can reduce the gain.
- Wrapper stress preserves exact catalog values; it does not prove semantic
  paraphrase support.
- The independent 100-case human-style fixture shows that the shared parser's
  category, paired override/negation, and semantic-value coverage still need a
  separate NLP iteration. The recovery tier prevents those misses from becoming
  irreversible hard-filter errors.
- Review popularity is a distribution assumption. The generated 800-session
  holdout regresses `0.003854` against uniform, while the labeled public set
  improves `0.019850`; neither reveals private performance.

## Files

- `entrypoint.py`: primary offline-review-prior adapter.
- `entrypoint_uniform.py`: uniform-belief ablation.
- `entrypoint_rating_number.py`: organizer-catalog-only prior ablation.
- `tunglam_inverse_dp/agent.py`: compatibility import retained for historical
  benchmark commands.
- `tunglam_inverse_dp/preprocessing.py`: compatibility import retained for
  historical benchmark commands.
- `submission/src/shopping_copilot/core.py`: integrated card reconstruction,
  safe focus/recovery, filtering, ranking, and DP.
- `submission/src/shopping_copilot/preprocessing.py`: integrated wrapper
  normalization with provenance.
- `tests/test_agent.py`: inverse filtering, DP, paraphrase safety, trust-chain,
  and override rollback tests.
- `tools/diagnostics.py`: exact-protocol survival/runtime diagnostics.
- `tools/pool_diagnostics.py`: exact-protocol pool-size diagnostics.
