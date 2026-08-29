# Frozen independent NLP fixture

`independent_human_paraphrases.jsonl` contains 100 shuffled, human-style
conversation cases created independently of the active parser and its tests.
Each case starts from one concrete `target_asin` in the generated 2,000-session
dev split. `target_category` stores its exact evaluator-derived catalog category,
while `expected.category` stores the natural category phrase actually said by
the shopper. The generator used the target's real metadata atoms for ground
truth but did not inspect parser behavior or parser output. All 100 targets are
distinct and none is a target in the organizer public 200.

The mix is frozen for candidate comparison:

- 65 `wrapper_exact_value` cases preserve the exact catalog value inside new
  natural wording;
- 35 `semantic_value_paraphrase` cases express the value with different words;
- scenarios cover buying, browsing, boundary replies, negation, intent override,
  and two-constraint compound messages;
- all messages are unique, every target atom belongs to the case's concrete
  target, and both atoms in a compound case belong to that same product.

Run the active baseline and an isolated NLP candidate from the repository root:

```bash
make human-stress
make human-stress ENTRYPOINT=experiments/nlp/<owner>-<approach>/entrypoint.py
```

The runner reports strict state, content-aware fact state, polarity, category,
catalog grounding, and a combined end-to-end pass rate. Grounding must retrieve
the concrete target, stay below 25% of the 50,000-item catalog, and keep at least
25% precision against a route-aware catalog reference set. The reference uses
exact metadata atoms except for short material/color clues, where it uses the
catalog's full-text word index. Returning every ASIN or the same 100 fixture
targets for every clue therefore fails. Compare the separate metrics and
scenario breakdown, not only the combined pass rate.

This is a visible, model-generated development diagnostic. It is not organizer
data, a human-labeled gold benchmark, or evidence of private-test wording. Do
not add case-ID/message-specific rules. Correct an objectively invalid ground
truth only in a separate evaluation-infrastructure PR with a written rationale;
never change the fixture to make one candidate look better.
