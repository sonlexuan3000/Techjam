# Team baseline snapshot

This snapshot was reproduced in the migrated team repository on 28 August 2026
using the frozen 50,000-product catalog. It describes the current deterministic
pre-event prototype, not the organizer's weak starter and not a private score
prediction.

| Suite | Sessions | Hit Rate@10 | MRR | MTTC | Technical score |
|---|---:|---:|---:|---:|---:|
| Official public set | 200 | 0.995 | 0.952548 | 2.0700 | 0.961864 |
| Shared synthetic dev | 2,000 | 0.987 | 0.853885 | 2.7005 | 0.915655 |
| Deterministic paraphrase stress | 200 | 0.230 | 0.065052 | 9.8650 | 0.157216 |

Reproduce:

```bash
make setup
make test
make evaluate
make unseen-data
make evaluate-unseen-dev
make stress
```

Thirteen unit/contract tests pass. The synthetic generator selected 2,800
unique targets with at least four generated constraints; public/dev/second-split
target overlap was zero and all scenario-mix checks passed.

## Interpretation

- Public performance comes from exact catalog evidence, conflict-aware state,
  `rating_number` as a relevance tie-break, and a Top-K schedule of 1, 2, then
  up to 10 from turn three.
- Strong synthetic-dev performance is useful evidence against memorizing only
  the 200 public target ASINs, but the generator shares evaluator assumptions.
- The paraphrase suite keeps hidden constraint strings and scenario timing the
  same while changing surrounding prose. Its large regression demonstrates a
  brittle wrapper-dependent parser; it does not prove the organizer-private
  simulator will use those wrappers.
- The shared 800-row second split is reproducible from a public seed and is
  therefore not secret. A separate uncommitted seed is needed for a genuine
  internal freeze check.

Every algorithm PR should append its before/after result to the PR description
rather than editing this snapshot opportunistically.
