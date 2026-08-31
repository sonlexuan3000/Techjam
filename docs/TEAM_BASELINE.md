# Final backend snapshot

This is the concise freeze record for the selected backend. The canonical
judge-facing analysis is maintained in [`EVALUATION.md`](EVALUATION.md).

## Selected candidate

The production entrypoint uses inverse intent-card reconstruction, reversible
NLP recovery, and finite-horizon recommendation-depth planning with a uniform
product prior.

| Generated-development backend | Sessions | HR@10 | MRR | MTTC | Technical Score |
|---|---:|---:|---:|---:|---:|
| Previous exact-evidence backend | 2,000 | 0.9865 | 0.852769 | 2.7010 | 0.915061 |
| **Uniform inverse-DP — selected** | **2,000** | **0.9935** | **0.977300** | **2.6255** | **0.957430** |
| Catalog `rating_number` prior | 2,000 | 0.9935 | 0.975782 | 2.6860 | 0.955765 |

The selected variant improves Technical Score by `0.042369` and MRR by
`0.124531` over the previous backend. A global catalog-popularity prior did not
improve the objective.

## Post-freeze evidence

| Evaluation | Sessions | HR@10 | MRR | MTTC | Technical Score |
|---|---:|---:|---:|---:|---:|
| Generated regression | 800 | 0.9975 | 0.980420 | 2.5850 | 0.961176 |
| Organizer public integration | 200 | 1.0000 | 0.997500 | 2.7950 | 0.963350 |

The final candidate and prior were selected on generated development; the
reported final public run occurred after integration freeze. The generated
regression split has a public seed and is not private evaluation.

## Robustness and scope

- 60 shared/core/contract tests pass.
- Exact catalog-value wrapper stress produced `0/2,000` differing scored-session
  summaries (hit, first-hit turn, and rank).
- An exhaustive audit found `0/50,000` card/category mismatches against the
  released evaluator.
- Runtime model/API/token use is zero.
- Exact-value grounding is substantially stronger than semantic-value
  paraphrasing; only `1/35` semantic grounding cases passed in the independent
  diagnostic.

Use these commands for candidate-safe reproduction:

```bash
make setup
make test
make unseen-data
make evaluate-unseen-dev
make human-stress
```
