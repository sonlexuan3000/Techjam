# InverseCart evaluation report

This report separates algorithm selection, post-freeze regression, language
diagnostics, and the organizer public integration check. None of these results
is presented as an estimate of the organizer's private 800 sessions.

## Metrics

For `N` sessions:

```text
HitRate@10 = sessions with the target in the scored Top 10 / N
MRR        = mean(1 / first-hit rank), with misses equal to 0
MTTC       = mean(first-hit turn), with misses assigned turn 11
Efficiency = clip((11 - MTTC) / 10, 0, 1)

TechnicalScore = 0.50 × HitRate@10 + 0.30 × MRR + 0.20 × Efficiency
```

Only exact `parent_asin` equality produces a hit. A successful session stops at
its first hit, so a low-ranked early hit cannot be improved in later turns.

`TechnicalScore` is the released objective composite used as an input to
Technical Execution. It is not the complete judged Technical Execution score or
the final hackathon score.

## Evaluation firewall

The team used three distinct evaluation roles:

| Data | Targets | Purpose | Used for selection? |
|---|---:|---|---|
| Generated development | 2,000 | Candidate comparison and ablation | Yes |
| Generated regression | 800 | Post-freeze behavior check | No |
| Organizer public set | 200 | Final contract/integration check | No |

The generated targets come from the frozen 50,000-product catalog after
excluding all 200 public target ASINs. Each split uses unique products with at
least four evaluator-derived constraints and the released scenario mix:

- 40% Buying;
- 40% Browsing;
- 15% Intent Override;
- 5% Boundary.

The generator, seed, checksums, overlap assertions, and scenario assertions are
reproducible with `make unseen-data`. The shared seed is public, so these splits
are development/regression fixtures rather than hidden evaluation data.

## Organizer public integration check

The following final-backend result was recorded after the uniform inverse-DP
candidate had been selected and frozen. The released weak-BM25 result and final
backend result use the same public 200 sessions.

| Backend | HR@10 | MRR | MTTC | Efficiency | Technical Score |
|---|---:|---:|---:|---:|---:|
| Released weak BM25 | 0.1250 | 0.068034 | 9.8100 | 0.1190 | 0.106710 |
| **InverseCart final backend** | **1.0000** | **0.997500** | **2.7950** | **0.8205** | **0.963350** |

Scenario breakdown for the final backend:

| Scenario | Sessions | HR@10 | MRR | MTTC |
|---|---:|---:|---:|---:|
| Buying | 80 | 1.0000 | 1.000000 | 2.3375 |
| Browsing | 80 | 1.0000 | 0.993750 | 2.7250 |
| Intent Override | 30 | 1.0000 | 1.000000 | 3.966667 |
| Boundary | 10 | 1.0000 | 1.000000 | 3.5000 |

Reproduce the aggregate from the released evaluator and public set:

```bash
make setup
make integration-check
```

This is a public development-set result, not the final organizer-private score.

## Candidate selection on generated development

| Backend | Sessions | HR@10 | MRR | MTTC | Technical Score |
|---|---:|---:|---:|---:|---:|
| Previous exact-evidence backend | 2,000 | 0.9865 | 0.852769 | 2.7010 | 0.915061 |
| **Uniform inverse-DP — selected** | **2,000** | **0.9935** | **0.977300** | **2.6255** | **0.957430** |
| Catalog `rating_number` prior | 2,000 | 0.9935 | 0.975782 | 2.6860 | 0.955765 |

Against the previous backend, the selected algorithm improves:

- Technical Score by `0.042369`;
- MRR by `0.124531`;
- HR@10 by `0.0070`;
- MTTC by `0.0755` turns.

The uniform prior also beats the catalog `rating_number` prior by `0.001665`
Technical Score and `0.001518` MRR. This supports using rating volume only as a
late tie-break in uncertain recovery, not as the global belief distribution.

Scenario breakdown for the selected variant:

| Scenario | Sessions | HR@10 | MRR | MTTC |
|---|---:|---:|---:|---:|
| Buying | 800 | 0.991250 | 0.976902 | 2.156250 |
| Browsing | 800 | 0.995000 | 0.976786 | 2.555000 |
| Intent Override | 300 | 0.993333 | 0.979500 | 3.776667 |
| Boundary | 100 | 1.000000 | 0.978000 | 3.490000 |

Reproduce the selected row with:

```bash
make setup
make unseen-data
make evaluate-unseen-dev
```

Reproduce the catalog `rating_number` ablation with:

```bash
make evaluate-candidate-dev \
  ENTRYPOINT=experiments/algo/tunglam-inverse-dp-review-prior/entrypoint_rating_number.py
```

The previous exact-evidence row is a historical result from commit `43dc120`;
it is retained for selection provenance rather than reproduced by the current
entrypoint.

## Post-freeze generated regression

After the implementation was frozen, the separate 800-session split produced:

| Sessions | HR@10 | MRR | MTTC | Efficiency | Technical Score |
|---:|---:|---:|---:|---:|---:|
| 800 | 0.9975 | 0.980420 | 2.5850 | 0.8415 | 0.961176 |

| Scenario | Sessions | HR@10 | MRR | MTTC |
|---|---:|---:|---:|---:|
| Buying | 320 | 1.000000 | 0.988650 | 2.000000 |
| Browsing | 320 | 0.993750 | 0.973802 | 2.578125 |
| Intent Override | 120 | 1.000000 | 0.975149 | 3.850000 |
| Boundary | 40 | 1.000000 | 0.983333 | 3.525000 |

Because its seed is committed and visible, this result demonstrates
reproducibility and post-freeze stability, not performance on secret data.

## Wrapper robustness

The deterministic wrapper-stress suite changes the surrounding natural-language
templates while preserving:

- exact catalog constraint strings and their order;
- scenario and override timing;
- target products and disclosure state;
- at-most-two-value `other` replies;
- scoring and turn limits.

Across 2,000 generated-development sessions, the canonical and rewritten-wrapper
runs had:

- the same `0.957430` Technical Score;
- the same HR@10, MRR, and MTTC;
- `0/2,000` differing scored-session summaries (hit, first-hit turn, and rank).

This isolates wrapper tolerance. It does not test semantic equivalence when the
catalog value itself is rewritten.

## Independent language diagnostic

The frozen 100-case fixture is model-generated rather than human-labeled. It
intentionally uses human-style wording, negation, overrides, compound messages,
and semantic value paraphrases. Each case uses a distinct
generated-development target, and none uses a public target.

| Diagnostic | Passed | Rate |
|---|---:|---:|
| Category extraction | 1 / 100 | 1.00% |
| Positive-fact extraction | 21 / 87 | 24.14% |
| Negation/override deactivation | 1 / 34 | 2.94% |
| Exact-value wrapper grounding | 42 / 52 | 80.77% |
| Semantic-value grounding | 1 / 35 | 2.86% |
| Complete state plus grounding | 1 / 100 | 1.00% |

This benchmark exposes the main limitation: exact catalog-value grounding is
useful, but general semantic state understanding remains weak. The focus/recovery
architecture prevents uncertain interpretations from becoming irreversible hard
filters; it does not turn those failed cases into successful semantic matches.

Run it with:

```bash
make human-stress
```

## Runtime measurements

Measurements were collected on an Apple M4 using the full catalog.

| Measurement | Result |
|---|---:|
| Catalog size | 50,000 products |
| One-time index startup | 5.75 s |
| Maximum resident memory | ~199 MiB |
| Timed responses | 500 turns |
| Response latency, mean | 30.045 ms |
| Response latency, median | 2.368 ms |
| Response latency, p95 | 136.585 ms |
| Response latency, maximum | 847.916 ms |
| Runtime prompt tokens | 0 |
| Runtime completion tokens | 0 |
| Marginal runtime model cost | $0 |

These values are a recorded one-off Apple M4 measurement. Timing varies with
hardware, candidate-pool size, and transcript state. Startup is paid once per
Agent instance; every turn then executes locally.

The retained diagnostic reproduces startup, peak-RSS increment, mean latency,
and p95 latency on a chosen session count:

```bash
make unseen-data
.venv/bin/python \
  experiments/algo/tunglam-inverse-dp-review-prior/tools/diagnostics.py \
  --catalog data/catalog.jsonl \
  --dataset data/unseen_eval/dev_set.jsonl \
  --limit 200
```

## Verification surface

The final repository has 60 passing unit/core/contract tests across Python 3.10
and 3.11 in CI. Coverage includes:

- focused evaluator intent-card/category parity regressions (the separate
  release audit exhaustively checked all 50,000 products);
- Agent interface and Top-K bounds;
- session isolation and reset behavior;
- hard/soft filtering and fallback;
- override timing and rejected-product state;
- parser event families, punctuation, negation, and compound replies;
- focus/recovery safety under uncertain wrappers;
- candidate/final integration parity;
- standalone submission import and smoke behavior.

```bash
make test
python3 submission/smoke.py --catalog data/catalog.jsonl
```

## Interpretation limits

- Generated datasets share the released evaluator's construction assumptions.
- Generated metrics exclude catalog products with fewer than four distinct
  derived constraints, so they are not results over a uniform sample of the
  complete catalog.
- The public 200 is visible and cannot estimate generalization to private
  products or changed simulator language.
- The 800-session regression split has a public seed and is not a hidden set.
- Wrapper robustness keeps catalog values exact and is not semantic robustness.
- Runtime measurements come from one machine and are not service-level bounds.
- The user profile is retained but not used by the selected ranking policy.
