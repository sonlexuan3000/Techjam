# Selected backend snapshot

This snapshot was reproduced on 31 August 2026 using the frozen 50,000-product
catalog and the shared generated-dev split. It describes the selected offline
backend, not an organizer-private score prediction.

| Variant | Sessions | Hit Rate@10 | MRR | MTTC | Technical score |
|---|---:|---:|---:|---:|---:|
| Previous exact-evidence backend | 2,000 | 0.9865 | 0.852769 | 2.7010 | 0.915061 |
| Selected uniform inverse-DP | 2,000 | 0.9935 | 0.977300 | 2.6255 | 0.957430 |
| Catalog `rating_number` ablation | 2,000 | 0.9935 | 0.975782 | 2.6860 | 0.955765 |

Candidate-safe reproduction:

```bash
make setup
make test
make unseen-data
make evaluate-unseen-dev
make human-stress
```

Do not run the organizer-public set while developing a candidate. It is not a
selection metric. Only the integration owner runs `make integration-check`
after the backend and its settings are frozen.

Sixty unit/core/contract tests pass. The synthetic generator selected 2,800
unique targets with at least four generated constraints; public/dev/second-split
target overlap was zero and all scenario-mix checks passed.

The new independent NLP diagnostic gives a deliberately harder picture of the
current baseline:

| Diagnostic | Passed | Rate |
|---|---:|---:|
| Category extraction | 1 / 100 | 1.0000% |
| Positive-fact extraction | 21 / 87 | 24.1379% |
| Negation/override deactivation | 1 / 34 | 2.9412% |
| Exact-value wrapper grounding | 42 / 52 | 80.7692% |
| Semantic-paraphrase grounding | 1 / 35 | 2.8571% |
| Full case, state plus grounding | 1 / 100 | 1.0000% |

These are parser/grounding diagnostics over generated-dev targets with zero
organizer-public target overlap. They are not the Technical Score and must not
be presented as an estimate of organizer-private performance.

## Selection rationale

- The uniform inverse-DP backend improves generated-dev score by `0.042369`
  over the previous backend and beats the eligible `rating_number` ablation by
  `0.001665`.
- A removed external review-history prior scored `0.958456`, only `0.001026`
  above uniform with an uncertainty interval crossing zero. It is excluded from
  production because the source has no clear redistribution license and can
  overlap the source family used to construct evaluation targets.
- The selected runtime reads only the organizer catalog and conversation input.
  It uses no external API, emits zero model tokens, and has zero marginal model
  cost.

## Interpretation

- Performance comes from reconstructing each product's revealable four-value
  intent card, replaying the observed disclosure protocol, retaining reversible
  recovery candidates, and choosing recommendation count with finite-horizon
  dynamic programming.
- Strong synthetic-dev performance is useful evidence against memorizing only
  the 200 public target ASINs, but the generator shares evaluator assumptions.
- The generated wrapper-stress suite keeps hidden constraint strings and
  scenario timing the same while changing surrounding prose. The selected
  backend keeps score `0.957430`, with `0/2,000` exact-versus-wrapper session
  summaries differing. This does not prove the organizer-private simulator will
  use those wrappers or that value-level semantics are solved.
- Unknown-wrapper exact catalog matches are tagged `catalog_fallback` and score
  candidates without intersecting the pool. This keeps a parser guess from
  permanently deleting a non-empty pool containing the true target.
- Value-level paraphrases are outside this test: `not wet in rain` will not be
  rewritten to `waterproof`. That belongs in the semantic matcher, where it can
  be scored with calibrated confidence rather than used as a hard filter.
- The shared 800-row second split is reproducible from a public seed and is
  therefore not secret. A separate uncommitted seed is needed for a genuine
  internal freeze check.

The dependency-free parser previously averaged `8.7 µs` per recognized message
and `0.075 ms` for normal exact catalog fallback on an Apple M4. The integrated
backend's full index startup measured `5.75 s` and about `199 MiB` maximum RSS.
Across 500 turns, response latency measured `30.045 ms` mean and `136.585 ms`
p95; the largest observed turn took `847.916 ms`.

Every algorithm PR should append its before/after result to the PR description
rather than editing this snapshot opportunistically.
