# Devpost submission copy

The sections below are written for direct use in the TikTok TechJam 2026
Devpost form. Repository and video URLs should be entered in their dedicated
Devpost fields rather than inserted into the body.

## Project title

InverseCart

## Tagline

Offline conversational product search with inverse-intent retrieval and
score-aware recommendation depth.

## Short description

InverseCart treats every catalog product as a conversation hypothesis, narrows
those hypotheses from multi-turn evidence, and uses finite-horizon dynamic
programming to decide how many products to recommend before learning from the
next clarification.

## Inspiration

Shopping search is usually framed as a ranking problem. This challenge adds a
harder decision: should an agent recommend more products now for coverage, or
return a smaller high-confidence prefix and use another turn to learn more?
Because the first successful recommendation fixes both the turn and reciprocal
rank, clarification cannot be separated from ranking depth.

We wanted to build a system that models that trade-off explicitly while staying
fast, reproducible, and robust to imperfect language parsing.

## What it does

InverseCart is an offline multi-turn shopping agent for the organizer's
50,000-product catalog. From the published interaction protocol, it builds a
compact intent representation for every product. Each product then becomes a
hypothesis about the conversation that would occur if it were the hidden target.

On every turn, the agent:

1. converts the user message into a structured state transition;
2. retains products capable of explaining the conversation so far;
3. preserves a recovery universe when the language interpretation is uncertain;
4. asks `other` to reveal up to two remaining details;
5. dynamically chooses the number of ranked products to return.

The required Buying, Browsing, Intent Override, and Boundary scenarios are
handled through the official `Agent.reset` and `Agent.respond` interface.

## How we built it

The system has four technical layers.

**1. Model-based product hypotheses.** During startup, one catalog pass derives
the published hard/soft intent representation for every product and builds
category, initial-message, and exact-constraint indexes. An exhaustive audit
found zero representation/category mismatches across all 50,000 catalog entries.

**2. Protocol-aware language state.** A dependency-free parser recognizes
category, requirement, preference, disclosure, no-preference, negation, and
override message families. It preserves the original catalog-value span and
tracks active, superseded, negative, and historical evidence. Conflicting
same-slot overrides, such as leather to canvas, deactivate the old value without
discarding compatible history.

**3. Reversible hypothesis filtering.** Exact grounded protocol evidence can
safely narrow eligibility. Paraphrased or weakly grounded evidence instead
creates a high-priority focus tier while retaining a trusted recovery universe.
This addresses a subtle failure mode: a wrong hard filter can leave a non-empty
pool that excludes the target forever, so waiting for an empty-pool fallback is
not enough.

**4. Finite-horizon recommendation planning.** For a fixed candidate ordering,
the agent tries every possible recommendation prefix length. It combines the
immediate competition reward for a hit at rank `r` on turn `t` —
`0.50 + 0.30/r + 0.02×(11-t)` — with the expected value of every next `other`
reply through turn ten. Products that would generate the same next reply form a
DP branch. The chosen cutoff therefore changes with the belief state and
remaining horizon.

The selected inverse-DP prior is uniform. A catalog `rating_number` prior was
implemented as an ablation but produced slightly worse MRR and Technical Score.

## Challenges we ran into

The first challenge was false elimination. Exact filtering is extremely strong
when the message follows the released protocol, but treating an uncertain parse
as equally trusted can permanently remove the target. We split ranking focus
from recoverable eligibility and made the trust transition monotonic within a
session.

The second challenge was optimizing competing metrics. Returning ten products
helps Hit Rate but can hurt MRR; returning too few or clarifying indefinitely can
hurt MTTC. Modelling recommendation depth as a finite-horizon action let us
optimize the combined objective directly within the released assumptions.

The third challenge was intent override timing. Recommendations before the new
intent arrives are not scoreable, while later recommendations are. We therefore
track provisional and genuine misses separately so an override can repair the
former without reviving the latter.

Finally, we wanted comparison results that did not simply overfit the visible
200 sessions. We generated 2,000 development and 800 post-freeze regression
sessions from catalog products with zero public-target overlap. The reported
final public-set run was an integration check after algorithm selection, not a
selection metric.

## Accomplishments that we are proud of

- On the final post-freeze organizer public integration check, InverseCart
  reached HR@10 `1.0000`, MRR `0.997500`, MTTC `2.7950`, and Technical Score
  `0.963350` across 200 sessions.
- On 2,000 generated-development sessions, it reached HR@10 `0.9935`, MRR
  `0.977300`, MTTC `2.6255`, and Technical Score `0.957430`.
- It improved generated-development Technical Score by `0.042369` and MRR by
  `0.124531` over the previous exact-evidence backend.
- A separate 800-session post-freeze regression run scored `0.961176`.
- Exact-value wrapper changes produced `0/2,000` differing scored-session
  summaries (hit, first-hit turn, and rank).
- The final runtime uses only the Python standard library and requires zero
  model calls, tokens, API credentials, or marginal model cost.
- Sixty unit, state, contract, core, and integration tests pass on Python 3.10
  and 3.11.

The public and generated results are development evidence, not claims about the
organizer's private evaluation set.

## What we learned

More recommendations are not always better. A successful low-ranked result can
be worse than exposing a small prefix and using the next response to separate
the remaining hypotheses.

We also learned that catalog popularity was not automatically a better prior.
On the generated-development target distribution, a uniform belief produced
better MRR and Technical Score than the `rating_number` ablation.

Most importantly, uncertainty should be represented explicitly. A parser guess
can influence ranking without being promoted immediately into irreversible
eligibility logic.

## What's next

The largest remaining gap is value-level semantic grounding. The current
language layer handles supported wrapper families and exact catalog values, but
does not reliably map a rewrite such as “does not get wet in rain” to
“waterproof.” We would add a calibrated semantic matcher as a scoring layer and
require it to pass target-survival tests before allowing it to affect hard
eligibility.

We would also evaluate aggregate-profile personalization only after showing a
reproducible gain, add confidence-aware customer explanations, and wrap the
stateful Agent with synchronization and observability for concurrent serving.

## Built with

- Python 3.10+
- Python standard library
- GitHub Actions
- Organizer-supplied Amazon Reviews 2023-derived catalog and evaluator
- OpenAI Codex for development-time inspection, code review, testing, benchmark
  orchestration, and documentation; Codex is not used by the runtime

## Repository-verifiable technical contributions

- **Tung Lam Nguyen:** original inverse intent-card filtering and finite-horizon
  recommendation-depth DP candidate.
- **Lê Xuân Sơn:** Track 4 repository and evaluation setup, data-safety review,
  lightweight NLP and recovery integration, candidate review and selection,
  official adapter, tests, benchmark verification, release packaging, and
  technical documentation.

## APIs, libraries, and assets disclosure

- Runtime APIs: none.
- Runtime third-party libraries: none.
- Runtime language or embedding models: none.
- Runtime credentials: none.
- Runtime network access: none after the catalog has been provided.
- Asset: the organizer-supplied 50,000-product catalog derived from Amazon
  Reviews 2023, `Clothing_Shoes_and_Jewelry`.
- Development fixture: 100 model-generated human-style language cases, used
  only as a diagnostic and never loaded by the runtime.

## Testing instructions

```bash
git clone https://github.com/sonlexuan3000/Techjam.git
cd Techjam
make setup
make test
make demo
```

`make setup` downloads the frozen organizer catalog, verifies its SHA-256, and
checks the 50,000-row count. No API key or environment variable is required.

## Known limitations

- The policy depends on the released card construction, disclosure order,
  scenario behavior, score function, and ten-turn horizon.
- General semantic-value paraphrases remain weak; the recovery tier limits
  damage but does not solve semantic equivalence.
- The independent model-generated diagnostic grounded only `1/35` semantic
  rewrites and passed `1/100` complete state-plus-grounding cases.
- The anonymized user profile is retained but not used for ranking.
- The Agent supports sequential sessions and needs an external lock for
  concurrent calls.
