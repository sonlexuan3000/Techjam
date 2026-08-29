# Five-person team plan: make parser errors recoverable

The current baseline already reaches about 99% Hit Rate on the official public
set. One teammate already owns safe filtering, candidate recovery, ranking,
`other`, and Top-K policy together. Keep that working path under one owner rather
than splitting tightly coupled code between two people.

The main design goal is:

> A parsing or semantic-matching mistake may lower a product's score, but must
> not silently kill the target for the rest of the session.

Roles 1–3 are the three algorithm owners. Role 4 independently measures whether
their changes generalize, and role 5 keeps the official Agent shippable.

## 1. Input NLP and conversation state

Owns normal user text to structured, uncertainty-aware intent:

- detect category and extract the exact spans that express constraints;
- identify slot, polarity, no-preference, and wording strength;
- handle multiple constraints, negation, overrides, and session history;
- preserve raw text, evidence source, and parser confidence;
- avoid guessing a hidden evaluator `hard` or `soft` label.

Example output:

```python
ParsedConstraint(
    slot="feature",
    raw_value="not get wet in rain",
    polarity="positive",
    strength="preference",
    confidence=0.88,
    source="user_message",
)
```

This owner extracts what the user meant. They do not decide which products to
remove and do not build the final ranking.

Target modules: `starter/parser.py`, `starter/state.py`, and
`tests/test_parser_state.py`.

## 2. Core search owner: filtering, ranking, and dialogue policy

This is the teammate who already owns roles 2 and 3 from the previous plan. They
preserve and improve the current high-scoring path:

- candidate pools and reversible filtering;
- recovery candidates when evidence is uncertain or contradictory;
- ranking formula and score breakdown;
- `rating_number` as a relevance tie-break;
- `other` question schedule and later information-gain experiments;
- dynamic Top-K, currently 1 then 2 then up to 10;
- already-shown products, overrides, and scenario trade-offs.

This owner consumes parser events and product-match scores. Soft or uncertain
evidence should normally change scores, not permanently delete products. Even a
high-confidence filter must be reversible; an empty-pool fallback is not enough,
because a wrong filter can leave a non-empty pool that excludes the target.

A useful mental model is:

```text
Tier A: matches all high-confidence active constraints
Tier B: matches most constraints or misses an uncertain constraint
Tier C: category-relevant recovery candidates
```

Preserve the current behavior with focused unit tests. Treat the existing 99%
public number as a historical integration reference; tune this module on
generated-dev, not on the organizer 200.

Target modules: `starter/search.py`, `starter/filtering.py`,
`starter/ranking.py`, `starter/policy.py`, `tests/test_filtering.py`,
`tests/test_ranking.py`, and `tests/test_policy.py`.

## 3. Catalog semantic matching and product representation

Owns the layer between parsed constraints and the core search owner. This is the
new role created by combining the old filtering and ranking roles:

- normalize catalog fields and build field-aware indexes;
- canonical aliases such as `grey -> gray` and `x-large -> XL`;
- match paraphrases such as `not get wet in rain -> waterproof`;
- exact, token, fuzzy, and optional embedding-based match routes;
- return per-product match scores and matching evidence, not a final decision;
- calibrate match confidence and provide a reliable exact-match fallback;
- benchmark startup time, memory, and per-query latency.

Example output:

```python
ConstraintMatch(
    constraint_id="c2",
    product_asin="B0...",
    score=0.81,
    route="semantic",
    matched_field="features",
    matched_text="Waterproof upper keeps feet dry",
)
```

This owner does not choose Top-K or ask questions. Their job is to say how well
each product matches each constraint and why; role 2 decides how that evidence
affects filtering and ranking.

Target modules: `starter/catalog.py`, `starter/matcher.py`,
`starter/semantic.py`, and `tests/test_matcher.py`.

## 4. Adversarial evaluation and generated data

Owns reproducibility and tries to break the full pipeline:

- generated-dev, second-split, and independent paraphrase benchmarks;
- paraphrased wrappers and paraphrased values;
- typos, multiple preferences in one sentence, negation, and no preference;
- overrides in the same slot and across different slots;
- soft preferences absent from metadata and products with missing fields;
- experiment tables, ablations, latency, and memory.

In addition to Hit Rate, MRR, and MTTC, report:

```text
Target Survival Rate
  = fraction of evaluated turns where the labeled target remains recoverable

False Elimination Rate
  = fraction of sessions where filtering removes the target before a hit
```

Also record candidate count before/after every constraint and which constraint
caused a large reduction. A 99% public score with poor target survival is a
fragile system.

Target paths: `scripts/`, `data/unseen_eval/`, `tests/fixtures/`, evaluation
tests, and experiment reports. Generated outputs remain ignored.

## 5. Integration, output, and release

Owns the official surface and prevents merge conflicts:

- `Agent.reset`/`Agent.respond` compatibility and module wiring;
- shared contracts and conversation-state lifecycle;
- simple natural-language response templates and explanations;
- CI, Makefile, dependencies, README, demo, and submission packaging;
- final benchmark, merge coordination, and release checks;
- the one organizer-public run after candidate winners and settings are frozen.

Only this owner resolves changes to `starter/agent.py`. Output NLP is light:
`ask_attribute` drives the simulator, so clear templates are enough.

Target paths: `starter/agent.py`, `starter/contracts.py`,
`starter/response.py`, Makefile, CI, and docs.

## Shared module contract

Agree on this boundary before splitting the monolithic baseline:

```python
events = parser.parse(user_message, state)
state = state_manager.apply(state, events)

match_result = matcher.match(
    constraints=state.active_constraints,
)
# per-constraint/product scores, routes, fields, and evidence

search_result = search_engine.decide(
    state=state,
    match_result=match_result,
    turn=turn,
    requested_top_k=top_k,
    allow_recovery=True,
)
# ranked ASINs, tiers, applied/relaxed constraints, next question

response = renderer.render(search_result)
```

The evaluator never exposes whether a revealed value came from its hidden
`hard_constraints` or `soft_preferences` list. The parser records wording and
confidence, the matcher measures product compatibility, and the core search
owner makes a reversible ranking/filtering decision.

## Implementation order

1. Freeze shared generated/NLP fixtures and preserve current behavior in unit tests.
2. Agree on `ParsedConstraint`, `ConstraintMatch`, and `SearchResult` schemas.
3. Build parser, semantic matcher, and adversarial fixtures in parallel.
4. Have the core search owner consume match scores without changing policy first.
5. Compare exact-only, semantic-score, tiered, and relaxed-filter variants.
6. Tune `other` and information-gain policy only after target survival is safe.

Candidate owners never use the organizer public 200 for tuning or selection.
After steps 1–6 choose the winners on the independent NLP 100 and generated-dev;
then role 5 runs the public set only as a frozen integration/protocol check.

This keeps three people on meaningful algorithm work without duplicating the
friend's existing filter/ranker/policy implementation.
