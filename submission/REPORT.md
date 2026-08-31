# InverseCart technical report

## Executive summary

InverseCart is a deterministic, offline conversational retrieval agent. Its key
technical idea is to reverse the released customer simulator: reconstruct the
intent card for every catalog product, treat each product as a hypothesis, and
retain only hypotheses capable of explaining the observed dialogue. A
finite-horizon dynamic program then chooses the recommendation depth that best
trades immediate rank reward against the expected value of the next `other`
clarification.

The final runtime receives only organizer-provided catalog fields, conversation
messages, and the supplied anonymized profile. The profile is retained but not
used for ranking. Runtime inference requires no model, external API, third-party
package, network connection, vector store, or credential.

## Method

### Catalog representation

At startup, the agent reproduces the participant-visible intent-card
construction for all 50,000 catalog products. Each `ProductIntent` contains a
coarse category, up to two generated hard constraints, the released
up-to-two-value soft suffix (or first-value fallback for a sparse card),
searchable text, and stable product metadata. A single catalog pass builds
category, initial-message, exact-constraint, and selected material/color
indexes.

An exhaustive release audit found zero card/category mismatches against the
released evaluator across all 50,000 products.

### Inverse conversation retrieval

On the trusted protocol path, the agent replays each transcript against each
candidate card. The initial scenario, disclosed values, ordered `other` replies,
and Intent Override timing must all be explainable by that product. Products
shown on a previous scoreable turn become rejected when another turn arrives.

If a full hard-plus-soft intersection becomes empty, only the soft suffix is
relaxed. Observed hard constraints and genuine scored misses remain mandatory.

### Reversible NLP recovery

The dependency-free parser recognizes supported category, requirement,
preference, disclosure, no-preference, negation, and override message families.
It normalizes wrapper prose while retaining the original catalog-value span.

Exact grounded protocol messages can establish eligibility. An uncertain parse
creates a high-priority focus tier while retaining the last trusted universe —
or the full catalog if uncertainty starts on turn one. This prevents a parser
guess from permanently deleting the target while leaving a plausible non-empty
pool. Exact catalog phrases inside unknown prose are recorded as
`catalog_fallback` ranking evidence and cannot destructively intersect the pool.

Intent state distinguishes active, superseded, negative, and historical clues.
Conflicting replacements are detected for material, color, size, and budget;
generic feature clues remain compatible unless explicitly negated.

### Finite-horizon recommendation depth

For a fixed hypothesis ordering, the DP considers every prefix length `k` up to
the requested Top-K. A target hit at turn `t` and rank `r` receives the exact
released per-session contribution:

```text
reward(t, r) = 0.50 + 0.30 / r + 0.02 × (11 - t)
```

On a miss, the prefix is removed. Each remaining product predicts the next one-
or-two-value response its own card would generate to `other`; equal replies form
a branch for turn `t + 1`. The recurrence includes the released initial
Browsing/Boundary mixture and terminates at turn ten.

The selected exact-path prior is uniform. When uncertain NLP has a non-empty
focus tier, that tier still uses DP. When it has no focus tier, the recovery path
uses a conservative one/two/up-to-ten schedule rather than optimizing an
unreliable ordering.

## Models, tools, APIs, assets, and cost

- Runtime language or embedding model: none.
- Retrieval database/vector service: none.
- Runtime dependencies: Python standard library only.
- Runtime network/API credentials: none.
- Runtime prompt/completion tokens: `0 / 0`.
- Estimated marginal runtime model cost: `$0`.
- Runtime data: organizer-supplied catalog, evaluator messages, and the supplied
  anonymized profile (retained but not used for ranking).
- Asset source: organizer catalog derived from Amazon Reviews 2023,
  `Clothing_Shoes_and_Jewelry`.
- Development assistance: OpenAI Codex supported repository inspection, code
  review, refactoring, test generation, benchmark orchestration, and
  documentation. Codex is not imported or called by the submitted runtime.
- Development diagnostic: a frozen 100-case model-generated human-style
  language fixture. It is not organizer data and is never loaded at runtime.

Development assistance was covered by the team's existing account and was not
separately metered as a per-session runtime cost.

## Evaluation protocol

Candidate selection used 2,000 deterministic generated-development sessions
whose target ASINs have zero overlap with the organizer public 200. After the
implementation was frozen, a separate 800-session generated split was used for
regression. Its seed is public, so it is not a hidden or private-test estimate.

The final inverse-DP candidate and uniform-prior choice were made on generated
development. The reported final public run occurred after the integration
freeze and was treated as a protocol check rather than a selection metric.

### Public integration result

| Sessions | HR@10 | MRR | MTTC | Efficiency | Technical Score |
|---:|---:|---:|---:|---:|---:|
| 200 | 1.0000 | 0.997500 | 2.7950 | 0.8205 | 0.963350 |

### Candidate selection

| Generated-development backend | HR@10 | MRR | MTTC | Technical Score |
|---|---:|---:|---:|---:|
| Previous exact-evidence backend | 0.9865 | 0.852769 | 2.7010 | 0.915061 |
| **Uniform inverse-DP — selected** | **0.9935** | **0.977300** | **2.6255** | **0.957430** |
| Catalog `rating_number` prior | 0.9935 | 0.975782 | 2.6860 | 0.955765 |

The selected backend improves Technical Score by `0.042369` and MRR by
`0.124531` over the previous backend on the same generated-development split.
The uniform prior also outperformed the `rating_number` prior, so catalog
popularity is retained only as a late tie-break among equally relevant uncertain
matches.

### Post-freeze regression

| Sessions | HR@10 | MRR | MTTC | Technical Score |
|---:|---:|---:|---:|---:|
| 800 | 0.9975 | 0.980420 | 2.5850 | 0.961176 |

### Language robustness

Changing only the natural-language wrappers while preserving exact catalog
values produced the same `0.957430` generated-development score and `0/2,000`
differing session summaries.

The harder independent 100-case diagnostic showed the boundary clearly:

| Diagnostic | Passed |
|---|---:|
| Exact-value wrapper grounding | 42 / 52 |
| Semantic-value grounding | 1 / 35 |
| Complete state plus grounding | 1 / 100 |

The recovery tier limits false elimination from semantic misses; it does not
claim to solve semantic equivalence.

## Runtime performance and reproducibility

An Apple M4 measurement with the 50,000-product catalog showed `5.75 s` startup
and approximately `199 MiB` maximum resident memory. Across 500 turns,
response latency was `30.045 ms` mean, `2.368 ms` median, `136.585 ms` p95, and
`847.916 ms` maximum. Timing varies with hardware and candidate-pool size.

From the complete repository:

```bash
make setup
make test
make unseen-data
make evaluate-unseen-dev
# Run only after the implementation is frozen
make evaluate-unseen-holdout
make human-stress
make demo
make submission-archive
```

The final suite contains 44 shared/state/contract tests and 16 selected
inverse-DP core tests. CI runs on Python 3.10 and 3.11.

## Limitations

- The policy is optimized within the released intent-card construction,
  disclosure order, scenario model, score function, uniform target prior, and
  ten-turn horizon. Changed private mechanics may reduce the gain.
- The language layer handles supported wrappers and exact catalog values, not
  arbitrary semantic paraphrases.
- The anonymized `user_profile` is retained per session but not used in ranking
  because no safe, measured personalization gain was established.
- One Agent instance supports multiple sequential sessions and needs external
  synchronization when embedded in a concurrent server.
- Generated development/regression data shares released evaluator assumptions;
  public and generated scores are not organizer-private predictions.

## Repository-verifiable technical contributions

The entries below cover Track 4 implementation work verifiable from repository
history at the integration freeze.

- **Tung Lam Nguyen:** original inverse intent-card filtering and finite-horizon
  recommendation-depth DP candidate.
- **Lê Xuân Sơn:** Track 4 repository and evaluation setup, data-safety review,
  lightweight NLP and recovery integration, candidate review and selection,
  official adapter, tests, benchmark verification, release packaging, and
  technical documentation.
