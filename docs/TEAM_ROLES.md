# Five-person team plan

The score is mainly a retrieval, ranking, and sequential-decision problem. NLP
is important at the input boundary, but the team does not need to train a large
language model. Three people own the main algorithms, one owns evaluation/data,
and one owns integration/output/release.

## 1. Input NLP and conversation state

Owns the conversion from normal user text into structured state:

- category, material, color, size, style, brand, budget, feature, and use case;
- synonyms and canonical values;
- negation, no-preference replies, compound replies, and intent overrides;
- evidence source/confidence and session isolation;
- parser/state unit tests and paraphrase robustness.

Target modules: `starter/parser.py`, `starter/state.py`, and
`tests/test_parser_state.py`.

## 2. Retrieval and ranking

Owns catalog indexing, candidate generation, and ordering:

- metadata normalization and field-aware indexes;
- exact/sparse retrieval and an optional measured semantic fallback;
- hard filtering, soft evidence, conflict handling, and score breakdowns;
- popularity tie-breaks, candidate fusion, latency, and memory.

Target modules: `starter/catalog.py`, `starter/retrieval.py`,
`starter/ranking.py`, and `tests/test_ranking.py`.

## 3. Question and recommendation policy

Owns the multi-turn decision:

- choose the attribute with the highest expected candidate reduction;
- avoid repeatedly asking an exhausted or useless attribute;
- decide when to ask, recommend, or do both;
- choose dynamic Top-K and handle already-shown products;
- compare policies by Hit Rate, MRR, MTTC, and scenario.

Target modules: `starter/policy.py` and `tests/test_policy.py`.

## 4. Evaluation, generated data, and experiments

Owns reproducibility rather than changing the ranker directly:

- the public benchmark and shared generated dev/regression suites;
- override, boundary, negation, no-preference, and paraphrase stress tests;
- experiment tables, ablations, scenario regressions, latency, and memory;
- fixed seeds and one-command reproduction for every teammate.

Target paths: `scripts/`, `data/unseen_eval/`, tests/fixtures, and experiment
reports. Generated outputs remain ignored.

## 5. Integration, output, and release

Owns the official surface and keeps the repository shippable:

- `Agent.reset`/`Agent.respond` compatibility and module wiring;
- simple natural-language response templates and explanations;
- CI, Makefile, dependencies, README, demo, and submission packaging;
- merge coordination and final benchmark/release checks.

Target paths: `starter/agent.py`, `starter/response.py`, Makefile, CI, and docs.

## Module contract

Agree on this boundary before splitting the monolithic baseline:

```python
events = parser.parse(user_message, state)
state = state_manager.apply(state, events)

rank_result = ranker.rank(state)
# ranked ASINs, candidate_count, facet statistics, score breakdown

decision = policy.decide(
    state=state,
    rank_result=rank_result,
    turn=turn,
    requested_top_k=top_k,
)

response = renderer.render(decision, rank_result)
```

Useful parser events:

```python
ConstraintAdded(slot, value, source, confidence)
ConstraintRemoved(slot, value)
PreferenceOverridden(slot, old_value, new_value)
NoPreference(attribute)
CategoryDetected(value)
```

The agent never sees the evaluator's hidden `hard_constraints` or
`soft_preferences` labels. State should record active/negative/superseded
evidence, source, and confidence; the ranker chooses how strongly to use it.

## How much NLP is actually needed?

Input NLP is P0 because users can phrase the same constraint in different ways.
The current deterministic baseline is strong on the official fixed wrappers but
brittle under the committed paraphrase stress test.

Start with normalization, an attribute ontology, regex/state rules, synonyms,
negation, and override tests. Then benchmark a small embedding or classifier as
a fallback for low-confidence text. Use an external LLM-to-JSON call only if it
measurably helps and the final runtime permits network access; always keep an
offline fallback.

Output NLP is light: `ask_attribute` is the structured control that drives the
simulator, so clear templates are enough. Do not spend an algorithm owner on a
general chatbot or generative response model before retrieval and policy are
strong.
