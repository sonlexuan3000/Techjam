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

The last command creates a deterministic source-only ZIP. Generated datasets,
catalog files, bytecode, virtual environments, and evaluation outputs are not
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
continues through turn ten. The selected product prior is uniform.

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

The final inverse-DP candidate and uniform-prior choice were selected on
generated-development. The current backend produced this public result after
the integration freeze:

| Sessions | HR@10 | MRR | MTTC | Technical Score |
|---:|---:|---:|---:|---:|
| 200 public | 1.0000 | 0.997500 | 2.7950 | 0.963350 |

Candidate selection and post-freeze regression used catalog products with zero
public-target overlap:

| Evaluation | Sessions | HR@10 | MRR | MTTC | Technical Score |
|---|---:|---:|---:|---:|---:|
| Generated development | 2,000 | 0.9935 | 0.977300 | 2.6255 | 0.957430 |
| Generated regression | 800 | 0.9975 | 0.980420 | 2.5850 | 0.961176 |

These are public/development results, not a private-set estimate. The full
methodology and limitations are recorded in `REPORT.md`.

## Runtime profile

Measured on an Apple M4 with the 50,000-product catalog:

- startup: `5.75 s`;
- maximum resident memory: approximately `199 MiB`;
- 500-turn latency: `30.045 ms` mean, `2.368 ms` median,
  `136.585 ms` p95, `847.916 ms` maximum;
- runtime model/API calls, tokens, and marginal model cost: zero.

Timing varies with hardware and candidate-pool size.

## Files

```text
submission/
  agent.py                         competition entrypoint
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
  model, score function, and ten-turn horizon.
- General semantic-value paraphrases remain weak. Recovery prevents an
  uncertain parse from redefining eligibility but cannot guarantee early rank.
- `user_profile` is stored per session but is not used by the ranking policy.
- One Agent instance supports multiple sequential sessions; concurrent calls
  require an external lock.
