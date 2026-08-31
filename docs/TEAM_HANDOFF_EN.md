# Technical handoff for the slide, video, and Devpost team

Languages: **English** · [Tiếng Việt](TEAM_HANDOFF_VI.md)

This document is the English counterpart to the Vietnamese team handoff. It is
for teammates who did not directly implement the backend but need to present
InverseCart accurately. If a number or claim in a slide or video differs from
this document, verify it against [`final_results.json`](final_results.json),
[`EVALUATION.md`](EVALUATION.md), and the production code before publishing.

## 1. The 30-second summary

**Project name:** InverseCart

**Track:** TikTok TechJam 2026, Track 4 — Shopping Copilot

Use this sentence consistently:

> InverseCart reverses the customer simulator: every product becomes a
> hypothesis about the conversation, and a score-aware planner decides how many
> products to expose now versus waiting for another answer.

The main technical differentiators are:

- It does not run an independent search on every turn. It maintains a set of
  product hypotheses throughout the conversation.
- It does not always return a fixed Top 10. A finite-horizon dynamic program
  chooses the recommendation count for the current state.
- It does not promote every NLP guess into a hard filter. When interpretation
  is uncertain, it prioritizes a `focus tier` while preserving a
  `recovery universe` from which the target can return.
- The popularity prior changes order and probability only within the eligible
  set; it cannot bypass a hard constraint.
- The competition runtime is offline and uses only the Python standard library.
  It needs no LLM, API key, GPU, vector database, or network request.

The Devpost tagline is:

> Offline conversational product search with inverse-intent retrieval and
> score-aware recommendation depth.

## 2. The actual optimization problem

The evaluator holds a hidden target `parent_asin`. The Agent must find that exact
identifier as early as possible and place it as high as possible in the ranked
list. A session stops at its first valid hit, so a target found early at a poor
rank cannot have its rank repaired on a later turn.

The released metrics are:

```text
HitRate@10 = successful sessions / N
MRR        = mean(1 / first-hit rank), with a miss equal to 0
MTTC       = mean(first-hit turn), with a miss assigned turn 11
Efficiency = clip((11 - MTTC) / 10, 0, 1)

TechnicalScore = 0.50 × HitRate@10 + 0.30 × MRR + 0.20 × Efficiency
```

For a hit on turn `t` at rank `r`, the per-session contribution is:

```text
reward(t, r) = 0.50 + 0.30 / r + 0.02 × (11 - t)
```

Therefore:

- returning more products immediately improves coverage but can lock in a poor
  MRR;
- returning too few may miss the target and consume another turn;
- clarifying for too long hurts MTTC.

This is why “how many products should we return?” is itself a dialogue decision,
not merely an output-format choice.

Sources: [`competition_specification.md`](competition_specification.md),
[`EVALUATION.md`](EVALUATION.md).

## 3. What the evaluator and Agent can see

### 3.1 Catalog data

The frozen catalog contains 50,000 products. Participant-visible fields are:

- `parent_asin`;
- `title`;
- `features`;
- `description`;
- `price`;
- `categories`;
- `details`;
- `average_rating`;
- `rating_number`;
- `store`.

Only exact `parent_asin` equality is scored.

### 3.2 Profile at session reset

The evaluator calls:

```python
agent.reset(session_id, user_profile)
```

The safe aggregate profile contains fields such as:

- `purchase_frequency`;
- `average_prior_rating`;
- `rating_style`;
- `preference_tags`;
- `summary`.

The production Agent stores the profile per session but **does not use it for
ranking**, because the team did not establish a safe, reproducible
personalization gain. The video must not attribute current results to
personalization.

### 3.3 One session loop

1. The evaluator creates a `session_id` and keeps the target and hidden intent
   card on the evaluator side.
2. It calls `reset(session_id, user_profile)`.
3. The simulated customer sends a scenario-dependent message.
4. The Agent receives only `session_id`, `user_message`, `turn`, and `top_k`.
5. The Agent returns a natural-language `message`, structured `ask_attribute`,
   and ranked `recommendations`.
6. The evaluator normalizes the output and scores at most the first 10 valid,
   unique `parent_asin` values.
7. If there is no hit, the evaluator creates the next customer reply. If there
   is a hit, the session ends.
8. A session lasts at most 10 turns. In an Intent Override session,
   recommendations before the new intent appears are not scoreable.

The released scenario mix is:

- 40% Buying;
- 40% Browsing;
- 15% Intent Override;
- 5% Boundary.

Sources: [`competition_specification.md`](competition_specification.md),
[`local_evaluator.py`](../evaluator/local_evaluator.py).

## 4. Full low-level flow of the production Agent

The production entrypoint is
[`submission/agent.py`](../submission/agent.py). The core logic is in
[`submission/src/shopping_copilot/core.py`](../submission/src/shopping_copilot/core.py).

### Step A — Build indexes once at startup

The Agent reads the catalog in one pass and constructs one `ProductIntent` per
product:

```text
parent_asin
coarse category
up to 2 hard constraints
up to 2 soft preferences
searchable metadata text
rating_number
average_rating
prior weight
```

The intent card is reconstructed in the same way as the participant-visible
evaluator:

1. collect `features` and `details`;
2. insert material or color detected in metadata when available;
3. append a budget value from price when available;
4. deduplicate values;
5. use the first two values as hard constraints;
6. use the next two as soft preferences, with a first-value fallback for a
   sparse card.

The same pass builds category, initial-message, exact-constraint, and small
parser lookup indexes. The release audit compared all 50,000 products against
the evaluator and found 0 intent-card/category mismatches.

### Step B — Parse and canonicalize the message

The dependency-free parser recognizes these message families:

- initial category or browsing language;
- hard requirement;
- preference;
- one- or two-value disclosure reply;
- no-preference or Boundary reply;
- negation;
- intent override.

It retains the original value span so catalog values containing punctuation or
internal semicolons are not corrupted.

### Step C — Determine the trust level

A message enters the exact path only when:

- its wrapper belongs to the released protocol; and
- every disclosed value can be grounded in the catalog index.

Otherwise, the session enters the NLP fallback path. This trust decision is
monotonic within the session: after uncertain evidence appears, a later
canonical-looking turn does not silently promote the whole transcript back to
exact-trusted status.

### Step D — Update session state

The state retains:

- raw and canonical messages;
- initial and current candidates;
- the trusted universe;
- focus candidates;
- scenario state;
- override state;
- the NLP-fallback flag;
- rejected products;
- pre-override recommendations and the previous turn's recommendations.

If the evaluator calls the Agent for another turn, every recommendation from the
previous scoreable turn was necessarily a miss and is added to `rejected`.

Intent Override is handled separately:

- recommendations before the override are provisional and not scoreable;
- when the override appears, provisional rejections are restored;
- recommendations that genuinely missed on later scoreable turns are not
  restored by mistake.

The tracker treats `material`, `color`, `size`, and `budget` as confidently
exclusive slots. When a value in the same slot changes, the old value becomes
superseded. Generic features may coexist unless they are explicitly negated.

### Step E — Infer candidates

**Exact trusted path:** retain product cards that could have produced the exact
transcript observed so far, including scenario, ordered `other` replies,
disclosed values, and override timing.

If the full hard-plus-soft intersection becomes empty, the Agent relaxes only
the soft suffix. Observed hard constraints and genuinely rejected products
remain mandatory exclusions.

**Uncertain NLP path:** split the search into two tiers:

- `focus tier`: products favored by the current parse, ranked and tried first;
- `recovery universe`: the most recent safe eligibility set, or the entire
  catalog if uncertainty begins on turn one.

An uncertain parse may change priority, but it cannot silently redefine
eligibility. When the focus is exhausted, the target may return through
recovery.

### Step F — Order candidates

The production belief weight is:

```text
w(product) = verified_reviews_365d(product) + 1
```

On the exact or focus path, deterministic ordering uses:

1. smoothed review weight;
2. catalog `rating_number`;
3. `average_rating`;
4. `parent_asin`.

The `+1` keeps a product with no observed review possible. The prior cannot
reintroduce a product that violates a hard constraint.

### Step G — Use DP to choose recommendation depth

Each DP hypothesis is:

```text
(parent_asin, disclosed_constraint_mask)
```

For every `k` from 1 to the requested Top-K cap, the DP combines:

- expected immediate reward if the target is in ranks `1..k` now;
- the miss branch after that prefix is rejected;
- every `other` reply the remaining product cards could generate;
- future value through turn 10.

Products that generate the same `other` reply form one branch. A branch's
probability is the sum of the prior weights of its products. On the initial vague
turn, the recurrence also models the released Browsing/Boundary mixture.

The DP chooses **prefix length**. It does not change the ranking permutation and
does not choose the question type.

If NLP fallback has no trustworthy focus left, the Agent does not apply DP to a
weak ordering. It uses a conservative schedule:

- turn 1: at most 1 product;
- turn 2: at most 2 products;
- turn 3 onward: at most 10 products.

### Step H — Return the response

Production returns:

```python
{
    "message": "Which two product details matter most to you?",
    "ask_attribute": "other",
    "recommendations": [{"parent_asin": "..."}],
    "usage": {"prompt_tokens": 0, "completion_tokens": 0},
}
```

The final backend chooses `other` because the released simulator can disclose up
to two remaining values from the entire intent card. This produces a richer
partition than a named attribute when metadata fields are sparse or
inconsistent.

Detailed sources: [`ARCHITECTURE.md`](ARCHITECTURE.md),
[`submission/README.md`](../submission/README.md).

## 5. Why a correct turn-one hit can be legitimate

A turn-one hit does not mean the bot read the ground truth.

1. The released initial message is generated deterministically from the target
   card.
2. The Agent constructs the same type of card for the entire catalog from
   participant-visible metadata.
3. A category plus an exact requirement can match only a very small set.
4. Within that set, the review prior may place the target at rank 1.
5. The Agent never receives `ground_truth`, a hidden card, or a target flag
   through its interface.

For the default `public_0001` example, the exact opening message leaves only
**2** hypotheses. Target `B09PYB7B6Z` has a 365-day review count of `2`, while
the competitor has `0`, so the prior orders the target first and DP returns
K=1. Across all 200 public-development sessions, the first-hit distribution is:
90 sessions on turn 1, 71 on turn 2, 20 on turn 3, and 19 on turn 4. Turn-one
hits are therefore normal behavior for this backend, not something that needs
to be hidden.

The frontend needs the target in order to act as the evaluator and highlight
the scored outcome. That is different from the production Agent reading the
target. `GET /api/sessions` deliberately omits ground truth and hidden intent;
`POST /api/simulate` invokes the Agent through its normal contract.

Use this caption in the recording:

> Ground-truth highlighting is evaluator-side visualization only. The Agent
> receives only profile, message, turn, and Top-K.

Keep the frontend's default behavior unchanged. For the recording, manually
select `public_0120` to satisfy the full multi-turn demo requirement and show
candidate narrowing. If `public_0001` is shown, explain its two-hypothesis pool
as above.

## 6. Data and leakage boundary

### What the runtime actually reads

- the organizer catalog;
- conversation inputs supplied through the Agent contract;
- `submission/data/review_prior.tsv`.

The prior contains exactly one aggregate count for each of the 50,000 catalog
ASINs. There are 5,777 products with a nonzero count; smoothing assigns every
remaining product a weight of one.

The prior **does not contain**:

- `sample_id`;
- user or profile mapping;
- review text;
- user identifiers;
- individual review timestamps;
- individual review rows;
- public-session mappings;
- target flags;
- unreleased organizer labels.

The count is the number of verified reviews in the 365 days before the exclusive
`2023-10-01` cutoff. It is aggregated from Amazon Reviews 2023,
`Clothing_Shoes_and_Jewelry`, and joined by `parent_asin`.

### Claims that are supported

- The runtime asset contains no unreleased/session-label leakage.
- The Agent does not load a public-set target mapping.
- The final prior type was selected on the organizer-labeled public development
  set, and that selection is disclosed.
- No final-evaluation session or unreleased label was available or used.

### Claims that are not supported

Do not say that the prior is “fully leakage-free over time.” The aggregate scans
the disclosed source before its cutoff and may contain events from periods that
the organizer later treats as held out. It is a predictive popularity prior,
not a causal estimate or a claim of temporally leakage-free evaluation.

The algorithm was selected on generated development. The final review prior was
selected on public development after the team confirmed that external data was
permitted. The generated holdout was retained as a distribution/regression
check and moved in the opposite direction from public development; it is not a
hidden or private set.

Sources: [`DATA_ATTRIBUTION.md`](../DATA_ATTRIBUTION.md),
[`DEVELOPMENT_PROVENANCE.md`](DEVELOPMENT_PROVENANCE.md),
[`submission/data/README.md`](../submission/data/README.md).

## 7. Verified results and ablations

### Organizer public development

| Backend | Sessions | HR@10 | MRR | MTTC | Technical Score |
|---|---:|---:|---:|---:|---:|
| Released weak BM25 | 200 | 0.1250 | 0.068034 | 9.8100 | 0.106710 |
| Uniform inverse-DP | 200 | 1.0000 | 0.997500 | 2.7950 | 0.963350 |
| Catalog `rating_number` inverse-DP | 200 | 1.0000 | 1.000000 | 2.0050 | 0.979900 |
| **Review-prior inverse-DP — shipped** | **200** | **1.0000** | **1.000000** | **1.8400** | **0.983200** |

Against the identical uniform core, the review prior moved the target to an
earlier turn in 117 sessions, left 82 sessions unchanged, and moved one later.
Public Technical Score improved by `+0.019850`.

### Generated development used for algorithm selection

| Backend | Sessions | HR@10 | MRR | MTTC | Technical Score |
|---|---:|---:|---:|---:|---:|
| Previous exact-evidence backend | 2,000 | 0.9865 | 0.852769 | 2.7010 | 0.915061 |
| Uniform inverse-DP | 2,000 | 0.9935 | 0.977300 | 2.6255 | 0.957430 |
| Catalog `rating_number` prior | 2,000 | 0.9935 | 0.974768 | 2.6890 | 0.955400 |
| **Review prior — shipped** | **2,000** | **0.9945** | **0.978687** | **2.6200** | **0.958456** |

The review prior improves only `+0.001026` over uniform on this split. The large
gain from the previous backend to the final system comes from inverse hypothesis
filtering and DP, not merely popularity.

### Generated holdout distribution check

| Prior | Sessions | HR@10 | MRR | MTTC | Technical Score |
|---|---:|---:|---:|---:|---:|
| Uniform | 800 | 0.9975 | 0.980420 | 2.5850 | 0.961176 |
| **Review prior — shipped** | **800** | **0.9925** | **0.976574** | **2.5950** | **0.957322** |

The review prior regresses `-0.003854` on this roughly uniformly sampled target
fixture. This contrary result must be disclosed; it shows that the prior depends
on the target distribution.

### Public scenario breakdown for the final backend

| Scenario | Sessions | HR@10 | MRR | MTTC |
|---|---:|---:|---:|---:|
| Buying | 80 | 1.0000 | 1.000000 | 1.3375 |
| Browsing | 80 | 1.0000 | 1.000000 | 1.6625 |
| Intent Override | 30 | 1.0000 | 1.000000 | 3.6000 |
| Boundary | 10 | 1.0000 | 1.000000 | 2.0000 |

Intent Override has a higher MTTC largely because the target is not allowed to
convert before the replacement intent appears on turn 3 or 4.

### NLP robustness boundary

- Changing the wrapper while preserving the exact catalog value produced the
  same score, `0.958456`, with `0/2,000` differing scored-session summaries.
- The independent 100-case diagnostic found:

| Diagnostic | Passed |
|---|---:|
| Exact-value wrapper grounding | 42 / 52 |
| Semantic-value grounding | 1 / 35 |
| Complete state plus grounding | 1 / 100 |

Do not use the wrapper result to claim arbitrary semantic understanding.

### Runtime and tests

Measured on an Apple M4 with the 50,000-product catalog:

- startup `6.4312 s`;
- Agent startup RSS increment `194.80 MiB`;
- `17.527 ms` mean and `74.693 ms` p95 over 368 response calls;
- runtime prompt/completion tokens `0 / 0`;
- marginal runtime model cost `$0`.

`make test` currently runs 54 shared state/parser/contract/frontend tests and 21
selected inverse-DP tests, for **75 passing** in total. Runtime values are
measurements on one machine, not service-level guarantees.

Metric sources: [`final_results.json`](final_results.json),
[`baseline_results.json`](baseline_results.json), [`EVALUATION.md`](EVALUATION.md),
[`Makefile`](../Makefile).

## 8. Recommended demo sessions

Run:

```bash
make setup
make frontend
```

Open <http://localhost:8787>. Keep the frontend's default behavior unchanged;
use the search field or session picker to select the recording session.

### Primary: `public_0120`

- Scenario: Browsing, difficulty medium.
- Category: Card Cases & Money Organizers / Wallets.
- Target: `B08GPGX2QG`, SENDEFN women's leather wallet.
- Production result: hit on turn 3 at rank 1.

The deterministic conversation is:

1. The user is browsing for a wallet and is still exploring.
2. After the first `other` question, the user discloses `leather` and
   `color: red`.
3. After the next question, the user discloses `Leather lining` and
   `Snap closure`; the target reaches rank 1.

This session is long enough to show candidate narrowing, constraint
accumulation, and the `other` policy, but short enough for the video.

### Backup: `public_0080`

- Intent Override, difficulty hard.
- Target `B0BPRQY4CF`, IZOD men's polo.
- Valid hit on turn 4 at rank 1.
- Use it to show that a target can appear in recommendations before the
  override, while the evaluator is not yet allowed to count it as a hit.

### Backup: `public_0112`

- Boundary, difficulty medium.
- Target `B086ZNJY8K`, Nautica men's walking sneaker.
- The user first gives a no-preference reply, then discloses `leather` and
  `Leather sole`.
- Hit on turn 3 at rank 1.

## 9. Eight-slide outline

### Slide 1 — Title and hook

- InverseCart.
- “Search for the product that could have generated the conversation.”
- Offline, deterministic, score-aware conversational retrieval.

### Slide 2 — Why this is not ordinary Top-10 search

- Hit Rate needs coverage.
- MRR needs a high rank.
- MTTC needs fewer turns.
- The first hit ends the session, so the system must choose between recommending
  now and clarifying.

### Slide 3 — Core insight: product as hypothesis

- Turn each product metadata row into an intent card.
- Each card predicts its possible initial message and `other` replies.
- The transcript progressively removes hypotheses that cannot explain the
  conversation.

### Slide 4 — Architecture

Visual flow:

```text
Catalog + review aggregate
        ↓
Intent cards + indexes
        ↓
Message parser → session state
        ↓
Exact candidates or focus + recovery
        ↓
Fixed candidate ordering
        ↓
Finite-horizon Top-K policy
        ↓
Recommendations + other
```

### Slide 5 — How DP chooses K

- Try every `k` from 1 to the Top-K cap.
- Balance immediate rank reward against the expected value of the next reply.
- Identical replies form one DP branch.
- DP chooses prefix length, not permutation or question type.

### Slide 6 — NLP safety and Intent Override

- Exact grounded evidence may filter eligibility.
- Uncertain evidence creates focus only; recovery remains.
- A same-slot override supersedes the old value.
- Provisional pre-override recommendations are restored at the correct time.

### Slide 7 — Results and ablation

The main chart should use these four public Technical Scores:

```text
Weak BM25             0.106710
Uniform inverse-DP    0.963350
rating_number prior   0.979900
Review prior shipped  0.983200
```

Honest caption: the public set was used to select the final prior; the generated
holdout regressed by `0.003854` versus uniform.

### Slide 8 — Ship-ready properties and limitations

- Python standard library, offline, zero model-token/API cost.
- 75 current tests.
- Reproducible archive and data provenance.
- Largest weakness: semantic-value paraphrasing.
- Public and generated results do not predict final-evaluation performance.

## 10. Recommended three-minute video cut

This is an internal editorial recommendation, **not an additional organizer
rule**.

| Time | Content | Visual |
|---|---|---|
| 0:00–0:15 | Hook | Title and one-line idea |
| 0:15–0:35 | Metric conflict | Hit Rate/MRR/MTTC triangle |
| 0:35–1:20 | Live `public_0120` | Viewer in Step mode, three turns |
| 1:20–2:05 | Architecture | Highlight product hypotheses, focus/recovery, DP |
| 2:05–2:40 | Metrics | Public ablation and honest holdout caption |
| 2:40–3:00 | Practicality and close | Offline, zero tokens, limitation |

The video needs at least one demonstrated multi-turn session according to the
repository technical specification. Event-level video format, URL visibility,
and deadline still need to be checked on the official Devpost page.

Short narration script:

> Normal search ranks products independently. InverseCart asks a different
> question: which product could have generated everything the customer has said
> so far? Each remaining product predicts the next clarification. A
> finite-horizon planner then chooses how many results to expose now, balancing
> coverage, reciprocal rank and turn efficiency. When language is uncertain, a
> recovery universe prevents a parser guess from deleting the target. The final
> runtime is deterministic, offline and uses zero model tokens.

Detailed recording notes are in
[`VIDEO_TECHNICAL_NOTES.md`](VIDEO_TECHNICAL_NOTES.md).

## 11. Devpost and document checklist

### Content that must stay consistent

- Project title: InverseCart.
- Tagline and short description.
- Problem and inspiration.
- What it does.
- Five technical layers: intent cards, parser/state, recovery, DP, and prior.
- Model, API, and cost disclosure.
- Call the public result labeled development, not a private or final score.
- Explain the roles of generated development and holdout and the target-
  distribution caveat.
- Known limitations.
- Setup and test commands.
- Repository URL and public video URL in the proper Devpost fields.

### Before pasting

- Use [`DEVPOST_SUBMISSION.md`](DEVPOST_SUBMISSION.md) as the source copy.
- The release test count must be 75: 54 shared plus 21 inverse-DP.
- Do not add the adaptive-K experiment to the shipped method; production remains
  review-prior inverse-DP.
- If the viewer is mentioned, call it a local visualization/demo tool, not the
  scoring runtime.
- Check repository and video visibility against the official Devpost rules.

## 12. Judge Q&A

### “How can it know the right product on turn one? Does it read the answer?”

No. The simulator deterministically generates the initial message from target
metadata. The Agent builds the same kind of intent card for the whole catalog,
so an exact message can narrow to a very small set. The popularity prior orders
that set. Ground truth exists only in the evaluator/frontend scoring layer and
is not passed to `Agent.respond`.

### “Does the prior hardcode the public 200?”

No session mapping or target label exists in the TSV. Each row contains only a
`parent_asin` and an aggregate verified-review count. However, the team compared
priors and selected the final review prior on the public 200 development set;
that selection is disclosed and is not described as a blind test.

### “Does the external review data leak evaluation data?”

There is no unreleased/session-label leakage. The team does not claim temporal
leakage freedom, because the aggregate source may overlap periods that the
organizer treats as held out. This is a predictive prior, not a causal estimate.

### “Did the gain come from the review prior or the algorithm?”

The public weak BM25 score is `0.106710`; uniform inverse-DP already reaches
`0.963350`; the final review-prior system reaches `0.983200`. The main gain comes
from inverse hypothesis inference and recommendation-depth planning. The prior
is an additional belief layer.

### “Why does the Agent always ask `other`?”

The released simulator lets `other` disclose up to two remaining values from the
entire card. That creates strong, predictable candidate partitions when named
metadata fields are sparse or inconsistent.

### “Does DP choose the question or rerank products?”

No. DP chooses `k` for a fixed ordering. The final backend's structured question
is always `other`.

### “How are hard and soft constraints different?”

Observed hard evidence remains mandatory. If the full hard-plus-soft match is
empty, the Agent may relax soft values, but it does not restore a hard mismatch
or a genuine miss.

### “How well does NLP handle semantic paraphrases?”

It is strongest when the wrapper changes but the exact catalog value remains.
General semantic rewriting is still weak: the diagnostic grounded only `1/35`.
Focus/recovery limits false elimination; it does not convert an unresolved
sentence into a correct semantic match.

### “Does the Agent use the user profile?”

The profile is stored to satisfy the session contract, but ranking does not use
it because the team has not established a safe, reproducible gain.

### “Does it require an LLM, API, or GPU?”

No. The runtime uses the Python standard library, runs offline, and reports zero
runtime model calls, tokens, and marginal model cost.

### “Is the frontend part of scoring?”

No. The frontend is a local viewer. The archive builder packages only the
`submission/` directory and the compact prior required by the Agent.

### “Can the public result guarantee the final score?”

No. The public 200 was used to select the prior, generated data shares released
simulator assumptions, and the prior regresses on generated holdout. All
reported numbers are development evidence.

### “Is the Agent thread-safe?”

One Agent instance supports multiple sessions sequentially through `session_id`.
Concurrent calls require an external lock; the local viewer serializes
simulation access.

## 13. Claim guardrails

### Supported wording

- “100% Hit Rate@10 and MRR 1.0 on the organizer's 200-session public
  development set.”
- “Public Technical Score of 0.983200.”
- “The algorithm was selected on generated development; the final prior was
  selected on public development.”
- “The runtime asset contains no public/final-session mapping or unreleased
  label.”
- “Offline, deterministic, standard-library-only runtime.”
- “Recovery protects eligibility under uncertain parsing.”

### Wording to avoid

- “The private score is/will be 0.9832.”
- “The bot understands every paraphrase.”
- “DP chooses the best question.”
- “Profile personalization improves the score.”
- “The review source is fully temporally leakage-free.”
- “The generated 800-session holdout is a hidden/private test.”
- “Technical Score is the entire final hackathon score.”
- “The new adaptive-K experiment runs in the submission.”
- “The frontend target badge proves the Agent can see the target.”

## 14. Glossary

| Term | Plain-language meaning |
|---|---|
| `parent_asin` | The exact product identifier scored by the evaluator |
| Intent card | The category, hard values, and soft values used by the simulator |
| Hard constraint | A condition that remains mandatory on the trusted path |
| Soft preference | A preference that may be relaxed if the full intersection is empty |
| Hypothesis | A product that may still explain the current transcript |
| Inverse simulator | Inferring which product could have generated the observed dialogue |
| Candidate pool | The products still under consideration |
| Trusted universe | The latest eligibility set established by trusted evidence |
| Focus tier | Candidates prioritized by an uncertain NLP interpretation |
| Recovery tier | Remaining safe candidates used after the focus is exhausted |
| Evidence | Category, constraint, negation, or override information from a message |
| Override | Replacement of an old preference with a new intent or value |
| Prior | Initial belief weight before all evidence is available |
| Smoothing `+1` | Keeps a zero-review product at positive probability |
| DP | Computes expected future score over turns and reply branches |
| `k` | Recommendation count on the current turn |
| Top-K cap | Maximum recommendation count allowed by the request/evaluator |
| Hit Rate@10 | Fraction of sessions that find the target in the scored Top 10 |
| MRR | Mean reciprocal first-hit rank |
| MTTC | Mean first-hit turn, with a miss counted as 11 |
| Efficiency | The score transformation derived from MTTC |
| Public development | 200 labeled sessions released by the organizer |
| Generated development | 2,000 reproducible sessions used for algorithm selection |
| Generated holdout | 800 publicly seeded sessions used for a regression check |
| Wrapper paraphrase | Changed surrounding phrasing with the exact catalog value retained |
| Semantic paraphrase | Rewording the value itself, for example rain-safe → waterproof |
| Viewer/frontend | Local evaluator visualization for demos, not the submitted runtime |

## 15. Source map

| What to understand | Source file |
|---|---|
| Landing story and quick start | [`README.md`](../README.md) |
| Production package | [`submission/README.md`](../submission/README.md) |
| Self-contained report | [`submission/REPORT.md`](../submission/REPORT.md) |
| Architecture/state/DP | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| Metrics, ablation, and caveats | [`EVALUATION.md`](EVALUATION.md) |
| Machine-readable metrics | [`final_results.json`](final_results.json) |
| Baseline metrics | [`baseline_results.json`](baseline_results.json) |
| Devpost copy | [`DEVPOST_SUBMISSION.md`](DEVPOST_SUBMISSION.md) |
| Video notes | [`VIDEO_TECHNICAL_NOTES.md`](VIDEO_TECHNICAL_NOTES.md) |
| Data provenance | [`DATA_ATTRIBUTION.md`](../DATA_ATTRIBUTION.md) |
| Prior extraction disclosure | [`DEVELOPMENT_PROVENANCE.md`](DEVELOPMENT_PROVENANCE.md) |
| Technical rules | [`competition_specification.md`](competition_specification.md) |
| Package rules | [`submission_rules.md`](submission_rules.md) |
| Final evaluator/code freeze | [`final_evaluation_faq.md`](final_evaluation_faq.md) |
| Final submission checklist | [`FINAL_SUBMISSION_CHECKLIST.md`](FINAL_SUBMISSION_CHECKLIST.md) |
| Viewer usage | [`frontend/README.md`](../frontend/README.md) |
| Production entrypoint | [`submission/agent.py`](../submission/agent.py) |
| Core implementation | [`core.py`](../submission/src/shopping_copilot/core.py) |
| Parser/state | [`parser.py`](../submission/src/shopping_copilot/parser.py), [`intent_tracker.py`](../submission/src/shopping_copilot/intent_tracker.py) |

## 16. Release and reproduction commands

From the repository root:

```bash
# Bootstrap the catalog, verify its checksum, and verify prior coverage
make setup

# 54 shared state/parser/contract/frontend + 21 selected inverse-DP tests
make test

# Verify public development; do not use this as a new tuning loop
make integration-check

# Reproduce generated development and holdout
make unseen-data
make evaluate-unseen-dev
make evaluate-unseen-holdout

# Language diagnostics
make human-stress

# CLI demo and local viewer
make demo
make frontend

# Build the deterministic offline runtime ZIP
make submission-archive
```

After building:

```bash
unzip -l dist/shopping-copilot-submission.zip
shasum -a 256 dist/shopping-copilot-submission.zip
```

After extracting the ZIP, run the smoke test with the organizer-provided
catalog:

```bash
python3 submission/smoke.py --catalog /absolute/path/to/catalog.jsonl
```

The archive contains only the runtime under `submission/`. It excludes the
catalog, generated datasets, frontend, raw review rows, Git history, virtual
environment, and evaluation outputs.

## 17. Final pre-publish check

- [ ] `make test` passes 75 tests.
- [ ] `make integration-check` reproduces the recorded public metrics.
- [ ] `make submission-archive` succeeds.
- [ ] The extracted archive passes the smoke test.
- [ ] README, report, Devpost, and video use the same backend name and result.
- [ ] Every test-count claim says 75 = 54 shared + 21 inverse-DP.
- [ ] The video shows a multi-turn session; `public_0120` is recommended.
- [ ] A caption explains that target highlighting is evaluator-side.
- [ ] The public result is called a development result.
- [ ] Prior selection and the holdout regression are disclosed.
- [ ] No claim of arbitrary semantic-paraphrase support is made.
- [ ] Repository and video visibility satisfy the official Devpost rules.
