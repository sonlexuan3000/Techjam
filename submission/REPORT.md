# InverseCart technical report

## Executive summary

InverseCart is a deterministic, offline conversational retrieval agent. Its key
technical idea is to reverse the released customer simulator: reconstruct the
intent card for every catalog product, treat each product as a hypothesis, and
retain only hypotheses capable of explaining the observed dialogue. A
finite-horizon dynamic program then chooses the recommendation depth that best
trades immediate rank reward against the expected value of the next `other`
clarification.

The final runtime receives organizer-provided catalog fields, conversation
messages, the supplied anonymized profile, and one bundled product-level review
count. The profile is retained but not used for ranking. Runtime inference
requires no model, external API, third-party package, network connection,
vector store, or credential.

The Agent never loads session datasets, target ASINs, intent cards, behavior
flags, or evaluation results. The bundled sidecar is only a 50,000-row
`parent_asin -> verified_reviews_365d` table. This boundary also explains why a
turn-one hit can be legitimate: the opening message may identify only a small
set of product hypotheses, after which the disclosed prior determines their
order. On public development, 90 of 200 sessions hit on turn one; the remaining
first hits are 71 on turn two, 20 on turn three, and 19 on turn four.

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

The selected exact-path weight is `verified_reviews_365d + 1`. The verified
count comes from a 365-day window ending before `2023-10-01`; smoothing keeps
zero-review products possible. It controls both candidate order and DP branch
probabilities, but never constraint eligibility. When uncertain NLP has a
non-empty focus tier, that tier still uses DP. When it has no focus tier, the
recovery path uses a conservative one/two/up-to-ten schedule rather than
optimizing an unreliable ordering.

## Models, tools, APIs, assets, and cost

- Runtime language or embedding model: none.
- Retrieval database/vector service: none.
- Runtime dependencies: Python standard library only.
- Runtime network/API credentials: none.
- Runtime prompt/completion tokens: `0 / 0`.
- Estimated marginal runtime model cost: `$0`.
- Runtime data: organizer-supplied catalog, evaluator messages, supplied
  anonymized profile (retained but not used for ranking), and bundled
  product-level review aggregate.
- Asset source: organizer catalog plus `verified_reviews_365d` counts derived
  from Amazon Reviews 2023, `Clothing_Shoes_and_Jewelry`. The TSV stores no
  individual review, text, timestamp, user identifier, or session label.
- Development assistance: OpenAI Codex supported repository inspection, code
  review, refactoring, test generation, benchmark orchestration, and
  documentation. Codex is not imported or called by the submitted runtime.
- Development diagnostic: a frozen 100-case model-generated human-style
  language fixture. It is not organizer data and is never loaded at runtime.

Development assistance was covered by the team's existing account and was not
separately metered as a per-session runtime cost.

## Evaluation protocol

Algorithm selection used 2,000 deterministic generated-development sessions
whose target ASINs have zero overlap with the organizer public 200. A separate
800-session generated split provides a reproducible distribution check. Both
sample eligible products roughly uniformly and use public seeds.

After the team confirmed with judges that external data was permitted, the
final review prior was selected on the organizer-labeled public development set.
We therefore report its public gain and generated-holdout regression together;
neither is presented as unreleased final-evaluation performance.

### Public development result

| Sessions | HR@10 | MRR | MTTC | Efficiency | Technical Score |
|---:|---:|---:|---:|---:|---:|
| 200 | 1.0000 | 1.000000 | 1.8400 | 0.9160 | 0.983200 |

The identical uniform core scored `0.963350`. Paired by session, the final prior
finds 117 targets earlier, 82 on the same turn, and one later.

The catalog `rating_number` prior scored `0.979900`; the recent verified-review
aggregate adds another `0.003300` on the same public development set.

### Candidate selection

| Generated-development backend | HR@10 | MRR | MTTC | Technical Score |
|---|---:|---:|---:|---:|
| Previous exact-evidence backend | 0.9865 | 0.852769 | 2.7010 | 0.915061 |
| Uniform inverse-DP | 0.9935 | 0.977300 | 2.6255 | 0.957430 |
| Catalog `rating_number` prior | 0.9935 | 0.974768 | 2.6890 | 0.955400 |
| **Offline review prior — shipped** | **0.9945** | **0.978687** | **2.6200** | **0.958456** |

The shipped backend improves Technical Score by `0.043395` and MRR by
`0.125918` over the previous backend on the same generated-development split.
Its gain over uniform is `0.001026`; the catalog `rating_number` prior remains a
separate weaker ablation.

### Generated holdout

| Prior | Sessions | HR@10 | MRR | MTTC | Technical Score |
|---|---:|---:|---:|---:|---:|
| Uniform | 800 | 0.9975 | 0.980420 | 2.5850 | 0.961176 |
| **Offline review prior — shipped** | **800** | **0.9925** | **0.976574** | **2.5950** | **0.957322** |

The final prior regresses `0.003854` on this roughly uniformly sampled fixture.
It gains no hits and loses four relative to uniform. This contrary result is a
target-distribution warning, not hidden evaluation.

### Language robustness

Changing only the natural-language wrappers while preserving exact catalog
values produced the same final-prior `0.958456` generated-development score and
`0/2,000` differing session summaries.

The harder independent 100-case diagnostic showed the boundary clearly:

| Diagnostic | Passed |
|---|---:|
| Exact-value wrapper grounding | 42 / 52 |
| Semantic-value grounding | 1 / 35 |
| Complete state plus grounding | 1 / 100 |

The recovery tier limits false elimination from semantic misses; it does not
claim to solve semantic equivalence.

## Runtime performance and reproducibility

An Apple M4 measurement of the final backend with the 50,000-product catalog
showed `6.4312 s` startup and a `194.80 MiB` Agent startup RSS increment. Across
368 public-development response calls, latency was `17.527 ms` mean and
`74.693 ms` p95. The full diagnostic process peaked near `403.39 MiB` because
it also held a second evaluator catalog index. Timing varies with hardware and
candidate-pool size.

From the complete repository:

```bash
make setup
make test
make unseen-data
make evaluate-unseen-dev
# Evaluate the separate generated holdout
make evaluate-unseen-holdout
make human-stress
make demo
make submission-archive
```

The final suite contains 54 shared state/parser/contract/frontend tests and 21
selected inverse-DP core tests: 75 total. CI runs on Python 3.10 and 3.11.

## Team member contributions

| Team member | Primary ownership | Concrete contribution |
|---|---|---|
| **Nguyễn Tuệ Vy** | Product story and presentation | Owns the end-to-end demo narrative, three-minute video production, and final Devpost/release QA. |
| **Vũ Đăng Khoa** | Evaluation studio and adaptive-policy research | Built the shipped conversation viewer, target-free diagnostics, and playback; implemented and benchmarked the adaptive-K experiment. |
| **Lưu Phúc Vinh** | Alternative recommendation policy | Implemented and tested the conservative dynamic-K candidate, providing an independently runnable policy for shortlist comparison and regression review. |
| **Lê Xuân Sơn** | NLP, integration, and release engineering | Built the wrapper-tolerant parser and evaluation harness; integrated the production backend, offline prior, documentation, CI, and reproducible archive. |
| **Nguyễn Tùng Lâm** | Core retrieval and planning | Designed and implemented the inverse-card candidate filter, constraint state, finite-horizon DP policy, preprocessing, prior tooling, and core tests later productionized for submission. |

The adaptive-K and conservative dynamic-K implementations are documented
experiments; the submitted Agent uses the integrated inverse-DP backend.

## Limitations

- The organizer states that final evaluation preserves the released intent-card
  behavior, deterministic message templates, interface, scoring, and response
  policy. The remaining generalization risk is the unreleased target
  distribution, especially whether it matches the review-popularity prior.
- The language layer handles supported wrappers and exact catalog values, not
  arbitrary semantic paraphrases.
- The anonymized `user_profile` is retained per session but not used in ranking
  because no safe, measured personalization gain was established.
- One Agent instance supports multiple sequential sessions and needs external
  synchronization when embedded in a concurrent server.
- Generated development/holdout data shares released evaluator assumptions;
  public and generated scores are not final-evaluation predictions.
- The public development set was used to select the final prior.
- The review aggregate scans the full disclosed source before its cutoff and
  may include periods later treated as held out; it carries no per-session or
  private labels, but is not claimed to be temporally leakage-free.
