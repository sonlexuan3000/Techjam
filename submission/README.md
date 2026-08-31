# Shopping Copilot submission backend

This directory is the self-contained competition bundle. It exports the
required `Agent.reset` and `Agent.respond` interface, runs fully offline, and
uses only Python's standard library.

## Environment

- Python 3.11 recommended; code supports Python 3.10 or newer.
- No third-party package is required at runtime.
- No API key, network connection, model download, environment variable, or GPU
  is required.
- The organizer catalog must be available as `data/catalog.jsonl`, or its path
  must be passed to `Agent(...)`.

No installation step is required. `requirements.txt` is intentionally empty
apart from its explanatory comment.

Import the official entrypoint:

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

## Reproduce

The runtime source in this directory is self-contained; the catalog and scoring
harness are organizer inputs. To smoke-test only this bundle with a catalog:

```bash
python3 submission/smoke.py --catalog data/catalog.jsonl
```

The full repository adds test generation and evaluator tooling. From its root:

```bash
make setup
make test
make evaluate-unseen-dev
make demo
make submission-archive
```

`make evaluate-unseen-dev` uses 2,000 deterministic catalog targets that do not
overlap the organizer's public 200. Do not use the public set for tuning.
After the release is frozen, the one-command official-compatible integration
run is `make integration-check`; this intentionally runs the organizer public
200 and must not be used to choose or tune a candidate.

## Architecture

1. Reconstruct the same small hard/soft intent card that visible evaluator code
   can reveal for every catalog product.
2. Parse exact protocol messages deterministically; normalize recognized wrapper
   paraphrases while retaining their provenance.
3. Keep products that could have generated the conversation in a focus tier.
   When language is uncertain, retain a trusted recovery universe instead of
   permanently deleting the target.
4. Ask `other` so the simulator can reveal up to two remaining constraints.
5. Use a finite-horizon dynamic program to select how many ranked products to
   return now versus preserving the opportunity to clarify.

The inverse-DP belief prior is uniform. Within uncertain NLP recovery only,
catalog `rating_number` remains a relevance tie-break between otherwise equal
matches; it never decides eligibility or hard filtering. A global
`rating_number` inverse-DP prior was benchmarked but produced lower MRR and
Technical Score on generated-dev.

## Verified generated-dev result

| Sessions | Hit Rate@10 | MRR | MTTC | Technical Score |
|---:|---:|---:|---:|---:|
| 2,000 | 0.9935 | 0.977300 | 2.6255 | 0.957430 |

After code was frozen, the shared 800-session second split scored HR@10
`0.9975`, MRR `0.980420`, MTTC `2.5850`, and Technical Score `0.961176`.
That split is generated from a public repository seed, so it is a regression
check rather than an organizer-private estimate.

Measured on an Apple M4 with 50,000 products, startup was `5.75 s` with maximum
RSS around `199 MiB`. Across 500 turns from 200 generated-dev sessions, response
latency was `30.045 ms` mean, `2.368 ms` median, `136.585 ms` p95, and
`847.916 ms` maximum. Runtime model/API token use and estimated model cost are
both zero. Timing varies with hardware and candidate-pool size.

## Limitations

- The score gain relies on the released intent-card construction, disclosure
  order, scenario behavior, metric, and ten-turn horizon. Changed private
  mechanics may reduce it.
- The lightweight NLP handles many wrapper changes while keeping exact catalog
  values intact, but it is not a general semantic model. For example,
  `not wet in rain` is not guaranteed to match `waterproof`.
- On the independent 100-case language diagnostic, only `1/35` semantic-value
  paraphrases grounded successfully and only `1/100` complete cases passed.
  The recovery tier limits damage from these misses; it does not solve them.
- `user_profile` is stored per session but is not yet used in ranking.
- One Agent instance supports multiple sequential sessions. It is not designed
  for concurrent calls without an external lock.

## Files

```text
submission/
  agent.py                         required competition entry file
  smoke.py                         standalone bundle smoke test
  requirements.txt                standard-library-only dependency declaration
  README.md                        setup, architecture, metrics, limitations
  REPORT.md                        method, tools, cost, latency, contributions
  src/shopping_copilot/core.py     inverse filtering, recovery, ranking, DP
  src/shopping_copilot/parser.py   message-to-event parsing
  src/shopping_copilot/intent_tracker.py conflict-aware evidence state
  src/shopping_copilot/preprocessing.py wrapper normalization
```
