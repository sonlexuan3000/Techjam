# Algorithm candidate: `tunglam-inverse-dp` (data-safe revision)

- Original owner: Tung Lam Nguyen
- Original commit: `044c2fa`
- Reviewed base: `c5987f5`
- Status: selected and integrated into `starter.agent.Agent`
- Frozen pre-integration source commit: `6ff9b1e`
- Primary entrypoint: `entrypoint.py` (uniform prior)
- Optional ablation: `entrypoint_rating_number.py`

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

The primary inverse-DP belief prior is uniform because generated targets are
sampled uniformly and this variant performed better than the global catalog
`rating_number` prior. The uncertain NLP recovery ranker retains the existing
catalog rating count only as a tie-break among equally relevant matches.

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

The original proposal bundled `verified_reviews_365d` derived from Amazon
Reviews 2023. Review found that the source has no explicit redistribution
license and that its purchase-review events overlap the source family used to
construct evaluation targets. The gain over uniform was only `0.001026` on the
generated dev split and its paired uncertainty interval included zero.

That asset, its extractors, and runtime support were removed. The retained
candidate uses only fields already present in the organizer-supplied catalog.
The original experiment remains recoverable from Git history.

## Reproduction

The commands below now exercise a compatibility alias to the integrated source.
Use commit `6ff9b1e` to reproduce the isolated candidate exactly as it was
reviewed and selected; the metrics table is the preserved selection record.

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

Do not use the organizer public 200 to select or tune this candidate. The
results below use only the deterministic `techjam-unseen-v1` generated-dev
split.

## Results

| Generated-dev variant | HR@10 | MRR | MTTC | Technical score |
|---|---:|---:|---:|---:|
| Team baseline | 0.9865 | 0.852769 | 2.7010 | 0.915061 |
| Uniform inverse-DP (primary) | 0.9935 | 0.977300 | 2.6255 | 0.957430 |
| Catalog `rating_number` inverse-DP | 0.9935 | 0.975782 | 2.6860 | 0.955765 |
| Removed external review prior | 0.9945 | 0.978687 | 2.6200 | 0.958456 |

The primary candidate improves the generated technical score by `0.042369`
over the team baseline while avoiding external data.

Scenario results for the primary candidate:

| Scenario | Sessions | HR@10 | MRR | MTTC |
|---|---:|---:|---:|---:|
| Boundary | 100 | 1.0000 | 0.978000 | 3.4900 |
| Browsing | 800 | 0.9950 | 0.976786 | 2.5550 |
| Buying | 800 | 0.99125 | 0.976902 | 2.15625 |
| Intent Override | 300 | 0.993333 | 0.979500 | 3.776667 |

Verification completed without running the organizer public set:

- shared suite: `39/39` passed;
- candidate suite: `16/16` passed, including evaluator card/category parity;
- reconstructed cards/categories match the evaluator for all `50,000` catalog products;
- exact generated-dev aggregate matches the pre-integration uniform ablation;
- deterministic wrapper stress also scores `0.957430` with identical HR/MRR/MTTC;
- all `2,000/2,000` exact-vs-wrapper session summaries match;
- pre-integration candidate startup on an Apple M4: about `5.37 s`, maximum
  RSS about `197 MiB` (the packaged integration is measured separately in
  `submission/REPORT.md`);
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
- Uniform target probability is an assumption. The catalog-only
  `rating_number` adapter is retained for controlled comparison.

## Files

- `entrypoint.py`: primary uniform-prior adapter.
- `entrypoint_uniform.py`: compatibility alias for earlier benchmark commands.
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
