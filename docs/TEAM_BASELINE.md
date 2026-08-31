# Final backend snapshot

This is the concise freeze record for the selected backend. The canonical
judge-facing analysis is maintained in [`EVALUATION.md`](EVALUATION.md).

## Selected candidate

The production entrypoint uses inverse intent-card reconstruction, reversible
NLP recovery, finite-horizon recommendation-depth planning, and a bundled
`verified_reviews_365d + 1` product prior.

| Generated-development backend | Sessions | HR@10 | MRR | MTTC | Technical Score |
|---|---:|---:|---:|---:|---:|
| Previous exact-evidence backend | 2,000 | 0.9865 | 0.852769 | 2.7010 | 0.915061 |
| Uniform inverse-DP | 2,000 | 0.9935 | 0.977300 | 2.6255 | 0.957430 |
| Catalog `rating_number` prior | 2,000 | 0.9935 | 0.974768 | 2.6890 | 0.955400 |
| **Offline review prior — shipped** | **2,000** | **0.9945** | **0.978687** | **2.6200** | **0.958456** |

The shipped variant improves Technical Score by `0.043395` and MRR by
`0.125918` over the previous backend. Its generated-development gain over
uniform is `0.001026`.

## Final evidence

| Evaluation | Sessions | HR@10 | MRR | MTTC | Technical Score |
|---|---:|---:|---:|---:|---:|
| Generated holdout — review prior | 800 | 0.9925 | 0.976574 | 2.5950 | 0.957322 |
| Organizer public development — review prior | 200 | 1.0000 | 1.000000 | 1.8400 | 0.983200 |

The inverse-DP algorithm was selected on generated development. After external
data was confirmed permitted, the final prior was selected on the labeled
public development set. It improves public Technical Score by `0.019850` over
uniform but regresses `0.003854` on the roughly uniform generated holdout. The
holdout seed is public and neither result is final evaluation.

## Robustness and scope

- 75 tests pass: 54 shared state/parser/contract/frontend tests plus 21 selected
  inverse-DP core tests.
- Exact catalog-value wrapper stress produced `0/2,000` differing scored-session
  summaries (hit, first-hit turn, and rank).
- An exhaustive audit found `0/50,000` card/category mismatches against the
  released evaluator.
- Runtime model/API/token use is zero.
- Exact-value grounding is substantially stronger than semantic-value
  paraphrasing; only `1/35` semantic grounding cases passed in the independent
  diagnostic.

Use these commands for generated-data reproduction:

```bash
make setup
make test
make unseen-data
make evaluate-unseen-dev
make human-stress
```
