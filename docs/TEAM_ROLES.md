# Five-person team plan: make parser errors recoverable

The current baseline already reaches about 99% Hit Rate on the official public
set. The main risk is no longer basic ranking: a parser mistake can be amplified
by a destructive filter that removes the true product permanently.

The design goal is therefore:

> A parsing mistake may lower a product's score, but must not silently kill the
> target for the rest of the session.

Three people own algorithms, one owns adversarial evaluation, and one owns
integration/release. Do not assign two people to rebuild the same public-set
ranker.

## 1. Input NLP and conversation state

Owns normal user text to structured, uncertainty-aware constraints:

- category, material, color, size, style, brand, budget, feature, and use case;
- canonical values, synonyms, paraphrases, typos, and compound replies;
- positive/negative intent, no-preference replies, and intent overrides;
- user wording strength such as `must`, `need`, `prefer`, or `ideally`;
- parser confidence, evidence source, state history, and session isolation.

The parser must not emit an unquestionable hidden `is_hard` label. It should
emit what was observed and how certain the interpretation is:

```python
ParsedConstraint(
    slot="feature",
    raw_value="not get wet in rain",
    canonical_value="waterproof",
    polarity="positive",
    strength="preference",
    confidence=0.72,
    source="user_message",
)
```

Target modules: `starter/parser.py`, `starter/state.py`, and
`tests/test_parser_state.py`.

## 2. Safe filtering and candidate recovery

Owns candidate generation and prevents uncertain evidence from deleting the
answer:

- catalog normalization and field-aware candidate indexes;
- exact/sparse retrieval plus an optional measured semantic fallback;
- soft constraints as score signals, not mandatory filters;
- reversible filtering for explicit, high-confidence constraints;
- automatic relaxation of the weakest constraint when the pool collapses;
- a recovery pool from the full relevant category;
- same-slot conflict and override handling;
- diagnostics for pool size and the reason each constraint was applied.

A useful mental model is tiered retrieval:

```text
Tier A: matches all high-confidence active constraints
Tier B: matches most constraints or misses an uncertain constraint
Tier C: category-relevant recovery candidates
```

Prefer penalties and tiers over permanent deletion. Even a high-confidence
filter must be reversible. An empty pool is not the only failure: a wrong filter
can produce a non-empty pool that excludes the target, so `if pool is empty`
alone is not a sufficient safeguard.

Target modules: `starter/catalog.py`, `starter/retrieval.py`,
`starter/filtering.py`, and `tests/test_filtering.py`.

## 3. Ranking and dialogue policy

Owns and preserves the current high-scoring baseline after receiving scored
candidates from role 2:

- ranking formula and score breakdown;
- `rating_number` as a relevance tie-break;
- `other` question schedule and later information-gain experiments;
- dynamic Top-K, currently 1 then 2 then up to 10;
- already-shown products and recommendation diversity;
- Hit Rate, MRR, and MTTC trade-offs by scenario.

This owner should not parse raw language or permanently remove candidates. Freeze
the current 99% path as a regression baseline before changing the policy.

Target modules: `starter/ranking.py`, `starter/policy.py`,
`tests/test_ranking.py`, and `tests/test_policy.py`.

## 4. Adversarial evaluation and generated data

Owns reproducibility and tries to break the full pipeline:

- public, generated-dev, second-split, and paraphrase benchmarks;
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
- the shared data contracts and conversation-state lifecycle;
- simple natural-language response templates and explanations;
- CI, Makefile, dependencies, README, demo, and submission packaging;
- final benchmark, merge coordination, and release checks.

Only this owner resolves changes to `starter/agent.py`. Output NLP is light:
`ask_attribute` drives the simulator, so clear templates are enough.

Target paths: `starter/agent.py`, `starter/contracts.py`,
`starter/response.py`, Makefile, CI, and docs.

## Shared module contract

Agree on this contract before splitting the monolithic baseline:

```python
events = parser.parse(user_message, state)
state = state_manager.apply(state, events)

candidate_result = retriever.retrieve(
    state=state,
    allow_recovery=True,
)
# tiers, candidate scores, pool sizes, applied/relaxed constraints

rank_result = ranker.rank(state, candidate_result)

decision = policy.decide(
    state=state,
    rank_result=rank_result,
    turn=turn,
    requested_top_k=top_k,
)

response = renderer.render(decision, rank_result)
```

The evaluator never exposes whether a revealed value came from its hidden
`hard_constraints` or `soft_preferences` list. The team may infer user strength
from wording, but it must preserve confidence and allow recovery instead of
turning that inference directly into permanent deletion.

## Implementation order

1. Freeze the current public/generated scores and behavior as golden tests.
2. Agree on `ParsedConstraint` and candidate-result schemas.
3. Build parser confidence, safe filtering, and adversarial tests in parallel.
4. Integrate without changing the current ranking/policy behavior first.
5. Compare exact-only, score-only, tiered, and relaxed-filter variants.
6. Tune `other` and information-gain policy only after target survival is safe.

NLP input remains P0, but one focused owner is enough. The second critical owner
is safe filtering: their job is to make imperfect NLP degrade gracefully rather
than cause an unrecoverable miss.
