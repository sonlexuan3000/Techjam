# InverseCart competition backend

This directory is the self-contained TikTok TechJam 2026 Track 4 submission. It
exports the required `Agent.reset` and `Agent.respond` interface and runs fully
offline using only the Python standard library.

## Runtime contract

- Python 3.10 or newer; Python 3.11 recommended.
- Third-party runtime packages: none.
- API key, model download, GPU, vector database, and network access: not needed.
- Runtime prompt/completion tokens: `0 / 0`.
- Organizer input: `data/catalog.jsonl`, or an explicit path passed to `Agent`.
- Bundled input: `submission/data/review_prior.tsv`, containing one aggregate
  verified-review count for each catalog product.

`requirements.txt` is intentionally empty apart from an explanatory comment.

## Validate an extracted bundle

After extracting the submission ZIP, pass the organizer catalog by absolute or
relative path:

```bash
python3 submission/smoke.py --catalog /absolute/path/to/catalog.jsonl
```

The command imports the competition entrypoint, builds the 50,000-product index,
resets a session, performs one turn, and validates the response shape.

## Validate from the full repository

From the full repository root:

```bash
make setup
make test
make demo
python3 submission/smoke.py --catalog data/catalog.jsonl
make submission-archive
```

The last command creates a deterministic offline-runtime ZIP. It includes the
compact prior required by the Agent; generated datasets, catalog files, raw
review rows, bytecode, virtual environments, and evaluation outputs are not
included.

## Use the entrypoint

```python
from submission.agent import Agent

agent = Agent("data/catalog.jsonl")
agent.reset(
    "session-1",
    user_profile={
        "purchase_frequency": "occasional",
        "average_prior_rating": 4.2,
        "rating_style": "balanced",
        "preference_tags": ["practical"],
        "summary": "Prefers practical products.",
    },
)

response = agent.respond(
    "session-1",
    "I'm looking for Shoes, but I'm still exploring.",
    turn=1,
    top_k=10,
)
```

The entry file also supports harnesses that load `submission/agent.py` directly
by filesystem path.

## Core idea

InverseCart does not issue a new search query on every turn. It reconstructs the
released intent card for every catalog product and treats the product as a
hypothesis about the conversation that would occur if it were the hidden target.

The runtime then:

1. parses the incoming message into a state transition;
2. keeps product cards capable of generating the observed transcript;
3. protects a trusted recovery universe when NLP is uncertain;
4. asks `other`, which can reveal up to two remaining card values;
5. uses finite-horizon DP to choose the recommendation prefix length for a
   fixed candidate ordering.

For a target at rank `r` on turn `t`, the recurrence uses the released
per-session reward:

```text
0.50 + 0.30 / r + 0.02 × (11 - t)
```

If the prefix misses, those products are rejected. Remaining hypotheses are
partitioned by the next `other` response each product would generate, and the DP
continues through turn ten. Product probability and fixed candidate order use
the bundled `verified_reviews_365d + 1` belief; that prior affects ranking and
planning but never constraint eligibility.

## Safe language boundary

Released wrappers with catalog-grounded values use exact inverse filtering.
Recognized paraphrased wrappers can create a focus tier while retaining the
recovery universe. Exact catalog phrases inside otherwise unknown prose become
non-destructive `catalog_fallback` ranking evidence and matter only when the
focus is exhausted. If uncertain NLP produces no focus candidates, the agent
uses a conservative `1 / 2 / up to 10` recommendation schedule instead of
applying DP to an unreliable ordering.

The parser recognizes supported category, requirement, preference, disclosure,
no-preference, negation, and override families. It is not a general semantic
model; a rewrite such as `not wet in rain -> waterproof` is not guaranteed.

## Verified results

The inverse-DP algorithm was selected on generated development. After external
data was confirmed permitted, the final review prior was selected on the
organizer-labeled public development set:

| Sessions | HR@10 | MRR | MTTC | Technical Score |
|---:|---:|---:|---:|---:|
| 200 public development | 1.0000 | 1.000000 | 1.8400 | 0.983200 |

Against the identical uniform core, the prior improves public Technical Score
from `0.963350` to `0.983200`: 117 targets move to an earlier turn, 82 stay on
the same turn, and one moves later.

Generated development and holdout use catalog products with zero public-target
overlap:

| Evaluation | Sessions | HR@10 | MRR | MTTC | Technical Score |
|---|---:|---:|---:|---:|---:|
| Generated development | 2,000 | 0.9945 | 0.978687 | 2.6200 | 0.958456 |
| Generated holdout | 800 | 0.9925 | 0.976574 | 2.5950 | 0.957322 |

The review prior is `+0.001026` over uniform on generated development but
`-0.003854` on the roughly uniformly sampled generated holdout. These are
public/development results, not a final-evaluation estimate. The full methodology
and limitations are recorded in `REPORT.md`.

## Runtime profile

Measured on an Apple M4 with the final prior and 50,000-product catalog:

- startup: `6.4312 s`;
- Agent startup RSS increment: approximately `194.80 MiB`;
- 368-turn latency: `17.527 ms` mean and `74.693 ms` p95;
- runtime model/API calls, tokens, and marginal model cost: zero.

Timing varies with hardware and candidate-pool size.

## Files

```text
submission/
  agent.py                         competition entrypoint
  data/review_prior.tsv            bundled product-level popularity prior
  data/README.md                    prior provenance and reproduction
  smoke.py                         standalone catalog smoke test
  requirements.txt                zero-dependency declaration
  README.md                        setup and runtime overview
  REPORT.md                        method, evaluation, cost, limitations
  src/shopping_copilot/core.py     inverse filtering, recovery, ranking, DP
  src/shopping_copilot/parser.py   message-to-event parsing
  src/shopping_copilot/            state tracking and wrapper normalization
```

## Limitations

- The policy assumes the released card construction, disclosure order, scenario
  model, score function, review-popularity prior, and ten-turn horizon.
- The public development set was used to select the prior, and the generated
  holdout moved in the opposite direction. Neither predicts the final score.
- General semantic-value paraphrases remain weak. Recovery prevents an
  uncertain parse from redefining eligibility but cannot guarantee early rank.
- `user_profile` is stored per session but is not used by the ranking policy.
- One Agent instance supports multiple sequential sessions; concurrent calls
  require an external lock.

The organizer states that the 800-session final uses the released deterministic
templates and response policy. It is released only after the deadline and must
be run with the unmodified evaluator against the frozen submitted commit; see
`docs/final_evaluation_faq.md` in the full repository.
