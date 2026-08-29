# Team baseline snapshot

This snapshot was reproduced in the migrated team repository on 28 August 2026
using the frozen 50,000-product catalog. It describes the current deterministic
pre-event prototype, not the organizer's weak starter and not a private score
prediction.

| Suite | Sessions | Hit Rate@10 | MRR | MTTC | Technical score |
|---|---:|---:|---:|---:|---:|
| Official public set, historical only | 200 | 0.995 | 0.954631 | 2.0750 | 0.962389 |
| Shared synthetic dev | 2,000 | 0.9865 | 0.852769 | 2.7010 | 0.915061 |
| Public-derived paraphrase stress, historical only | 200 | 0.995 | 0.952964 | 2.0900 | 0.961589 |

Candidate-safe reproduction:

```bash
make setup
make test
make unseen-data
make evaluate-unseen-dev
make human-stress
```

Do not reproduce the two historical public-derived rows while developing a
candidate. They are not selection metrics. Only the integration owner runs
`make integration-check` after both winners and their settings are frozen.

Thirty-nine unit/contract tests pass. The synthetic generator selected 2,800
unique targets with at least four generated constraints; public/dev/second-split
target overlap was zero and all scenario-mix checks passed.

The new independent NLP diagnostic gives a deliberately harder picture of the
current baseline:

| Diagnostic | Passed | Rate |
|---|---:|---:|
| Category extraction | 1 / 100 | 1.0000% |
| Positive-fact extraction | 14 / 87 | 16.0920% |
| Negation/override deactivation | 1 / 34 | 2.9412% |
| Exact-value wrapper grounding | 52 / 52 | 100.0000% |
| Semantic-paraphrase grounding | 1 / 35 | 2.8571% |
| Full case, state plus grounding | 1 / 100 | 1.0000% |

These are parser/grounding diagnostics over generated-dev targets with zero
organizer-public target overlap. They are not the Technical Score and must not
be presented as an estimate of organizer-private performance.

## Interpretation

- Public performance comes from exact catalog evidence, conflict-aware state,
  `rating_number` as a relevance tie-break, and a Top-K schedule of 1, 2, then
  up to 10 from turn three.
- Strong synthetic-dev performance is useful evidence against memorizing only
  the 200 public target ASINs, but the generator shares evaluator assumptions.
- The paraphrase suite keeps hidden constraint strings and scenario timing the
  same while changing surrounding prose. The old exact-wrapper parser scored
  `0.157216`; the lightweight parser scores `0.961589`. This does not prove the
  organizer-private simulator will use those wrappers.
- Unknown-wrapper exact catalog matches are tagged `catalog_fallback` and score
  candidates without intersecting the pool. This keeps a parser guess from
  permanently deleting a non-empty pool containing the true target.
- Value-level paraphrases are outside this test: `not wet in rain` will not be
  rewritten to `waterproof`. That belongs in the semantic matcher, where it can
  be scored with calibrated confidence rather than used as a hard filter.
- The shared 800-row second split is reproducible from a public seed and is
  therefore not secret. A separate uncommitted seed is needed for a genuine
  internal freeze check.

The final dependency-free parser averaged `8.7 µs` per recognized message and
`0.075 ms` for normal exact catalog fallback on an Apple M4. Full catalog index
construction averaged about `5.3 s` once per process.

Every algorithm PR should append its before/after result to the PR description
rather than editing this snapshot opportunistically.
