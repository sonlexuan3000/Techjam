# InverseCart evaluation report

This report separates algorithm selection, prior selection, generated holdout,
language diagnostics, and the organizer-labeled public development result. None
of these results is presented as an estimate of the organizer's private 800
sessions.

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

## Evaluation roles

The team used three distinct evaluation roles. The inverse-DP algorithm was
chosen on generated development. After the team confirmed with judges that
external data was permitted, the organizer public set was used to choose the
final prior. This is disclosed rather than described as a post-selection check.

| Data | Targets | Purpose | Used for selection? |
|---|---:|---|---|
| Generated development | 2,000 | Algorithm comparison and prior diagnostic | Yes, algorithm |
| Generated holdout | 800 | Distribution/regression check | No |
| Organizer public development | 200 | Final prior selection and integration | Yes, prior |

The generated targets come from the frozen 50,000-product catalog after
excluding all 200 public target ASINs. Each split uses unique products with at
least four evaluator-derived constraints and the released scenario mix:

- 40% Buying;
- 40% Browsing;
- 15% Intent Override;
- 5% Boundary.

The generator, seed, checksums, overlap assertions, and scenario assertions are
reproducible with `make unseen-data`. The shared seed is public, so these splits
are development/holdout fixtures rather than hidden evaluation data.

## Organizer public development A/B

The inverse-DP implementation is identical across the three prior rows; only
the belief prior changes. The public set is organizer-labeled development data
and was used to select the shipped review prior.

| Backend | HR@10 | MRR | MTTC | Efficiency | Technical Score |
|---|---:|---:|---:|---:|---:|
| Released weak BM25 | 0.1250 | 0.068034 | 9.8100 | 0.1190 | 0.106710 |
| Uniform inverse-DP | 1.0000 | 0.997500 | 2.7950 | 0.8205 | 0.963350 |
| Catalog `rating_number` inverse-DP | 1.0000 | 1.000000 | 2.0050 | 0.8995 | 0.979900 |
| **Review-prior inverse-DP — shipped** | **1.0000** | **1.000000** | **1.8400** | **0.9160** | **0.983200** |

Paired by session, the review prior found the target earlier in `117/200`
cases, on the same turn in `82/200`, and later in `1/200`. The public Technical
Score gain over uniform is `+0.019850`; all final hits are rank one.

The recent verified-review aggregate also improves `0.003300` over the catalog
`rating_number` popularity prior on this set.

Scenario breakdown for the final backend:

| Scenario | Sessions | HR@10 | MRR | MTTC |
|---|---:|---:|---:|---:|
| Buying | 80 | 1.0000 | 1.000000 | 1.3375 |
| Browsing | 80 | 1.0000 | 1.000000 | 1.6625 |
| Intent Override | 30 | 1.0000 | 1.000000 | 3.6000 |
| Boundary | 10 | 1.0000 | 1.000000 | 2.0000 |

Reproduce the aggregate from the released evaluator and public set:

```bash
make setup
make integration-check
```

This is the result used for final prior selection on the public development
set, not the organizer-private score.

## Algorithm comparison on generated development

| Backend | Sessions | HR@10 | MRR | MTTC | Technical Score |
|---|---:|---:|---:|---:|---:|
| Previous exact-evidence backend | 2,000 | 0.9865 | 0.852769 | 2.7010 | 0.915061 |
| Uniform inverse-DP | 2,000 | 0.9935 | 0.977300 | 2.6255 | 0.957430 |
| Catalog `rating_number` prior | 2,000 | 0.9935 | 0.974768 | 2.6890 | 0.955400 |
| **Offline review prior — shipped** | **2,000** | **0.9945** | **0.978687** | **2.6200** | **0.958456** |

Against the previous backend, the shipped configuration improves:

- Technical Score by `0.043395`;
- MRR by `0.125918`;
- HR@10 by `0.0080`;
- MTTC by `0.0810` turns.

The offline review prior beats uniform by `0.001026` Technical Score and
`0.001387` MRR on this split. The smaller improvement is consistent with the
generator's roughly uniform target sampling: the fixture does not reproduce a
popularity-weighted target distribution.

Scenario breakdown for the shipped prior:

| Scenario | Sessions | HR@10 | MRR | MTTC |
|---|---:|---:|---:|---:|
| Buying | 800 | 0.991250 | 0.976026 | 2.080000 |
| Browsing | 800 | 0.996250 | 0.980649 | 2.615000 |
| Intent Override | 300 | 1.000000 | 0.983722 | 3.760000 |
| Boundary | 100 | 0.990000 | 0.969167 | 3.560000 |

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

## Generated holdout A/B

The separate 800-session split exposes the prior's distribution tradeoff:

| Prior | Sessions | HR@10 | MRR | MTTC | Efficiency | Technical Score |
|---|---:|---:|---:|---:|---:|---:|
| Uniform | 800 | 0.9975 | 0.980420 | 2.5850 | 0.8415 | 0.961176 |
| **Offline review prior — shipped** | **800** | **0.9925** | **0.976574** | **2.5950** | **0.8405** | **0.957322** |

The review prior regresses `0.003854` against uniform on this fixture. Paired by
session, it finds 76 targets earlier, 624 on the same turn, and 100 later; it
gains no hits and loses four. Rank improves in 10 sessions, is unchanged in
778, and worsens in 12.

| Scenario | Sessions | HR@10 | MRR | MTTC |
|---|---:|---:|---:|---:|
| Buying | 320 | 1.000000 | 0.977764 | 2.003125 |
| Browsing | 320 | 0.984375 | 0.972005 | 2.581250 |
| Intent Override | 120 | 0.991667 | 0.983333 | 3.816667 |
| Boundary | 40 | 1.000000 | 0.983333 | 3.775000 |

Because its seed is committed and visible, this result is a reproducible
distribution diagnostic, not performance on secret data. Eligible products are
sampled roughly uniformly, so the split naturally favors a uniform belief more
than a popularity-weighted deployment distribution would.

## Wrapper robustness

The deterministic wrapper-stress suite changes the surrounding natural-language
templates while preserving:

- exact catalog constraint strings and their order;
- scenario and override timing;
- target products and disclosure state;
- at-most-two-value `other` replies;
- scoring and turn limits.

Across 2,000 generated-development sessions, the final review-prior canonical
and rewritten-wrapper runs had:

- the same `0.958456` Technical Score;
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

Measurements were collected on an Apple M4 using the final review-prior backend
and organizer public sessions.

| Measurement | Result |
|---|---:|
| Catalog size | 50,000 products |
| One-time index startup | 6.4312 s |
| Agent startup RSS increment | 194.80 MiB |
| Timed responses | 368 turns |
| Response latency, mean | 17.527 ms |
| Response latency, p95 | 74.693 ms |
| Runtime prompt tokens | 0 |
| Runtime completion tokens | 0 |
| Marginal runtime model cost | $0 |

These values are a recorded one-off Apple M4 measurement. The whole diagnostic
process peaked at approximately `403.39 MiB`, but that process includes a second
catalog index owned by the evaluator and is not the Agent's standalone memory
footprint. Timing varies with hardware, candidate-pool size, and transcript
state. Startup is paid once per Agent instance; every turn then executes
locally.

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

The final repository has 66 passing unit/core/contract tests across Python 3.10
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
- standalone submission import and smoke behavior;
- prior-file schema, coverage, non-negative values, smoothing, and entrypoint
  integration.

```bash
make test
python3 submission/smoke.py --catalog data/catalog.jsonl
```

## Interpretation limits

- Generated datasets share the released evaluator's construction assumptions.
- Generated metrics exclude catalog products with fewer than four distinct
  derived constraints. Within that eligible pool they sample targets roughly
  uniformly, so they are not a test of the review-popularity assumption.
- The public 200 was used to select the final prior and cannot estimate
  generalization to private products or changed simulator language.
- The 800-session holdout has a public seed and is not a hidden set.
- The source review aggregate was computed over the full disclosed source file
  before the stated cutoff. It may include events from periods the organizer
  later treats as held out. It contains no session mapping or private label, but
  this temporal limitation prevents a causal or leakage-free claim.
- Wrapper robustness keeps catalog values exact and is not semantic robustness.
- Runtime measurements come from one machine and are not service-level bounds.
- The user profile is retained but not used by the selected ranking policy.
