# TechJam Conversational E-Commerce Search Challenge

Build an AI shopping agent that asks useful follow-up questions and recommends the customer's hidden target product within at most 10 turns.

This is the team's Track 4 repository. The previous Track 1 code is preserved on
`archive/track1-before-track4-20260828`; `main` now contains only the Shopping
Copilot participant kit, the current deterministic agent, and shared evaluation
tooling.

## Team Quick Start

Python 3.10 or newer is recommended. No API key is required for the current
baseline.

```bash
make setup
make test
make unseen-data
```

Use the same generated tests on every teammate's machine:

```bash
# Current shared baseline
make evaluate-unseen-dev
make human-stress

# Isolated candidates under experiments/
make evaluate-candidate-dev ENTRYPOINT=experiments/algo/<owner>-<approach>/entrypoint.py
make human-stress ENTRYPOINT=experiments/nlp/<owner>-<approach>/entrypoint.py
```

Do **not** use `data/public_set.jsonl` or `make evaluate` to tune code, compare
candidates, or choose a winner. NLP candidates are selected on the independent
100-case human-style fixture; algorithm candidates are selected on the 2,000
generated-dev sessions. Only the integration owner runs the organizer public
200 after both winners are frozen, as a final protocol/regression check.

`make unseen-data` deterministically builds 2,000 shared dev sessions and 800
shared regression sessions from official catalog products that are not public-set
targets. Generated files stay ignored; the committed generator and fixed seed
make them reproducible. They are robustness tests, not leaked or predicted
organizer-private data. Read [data/unseen_eval/README.md](data/unseen_eval/README.md)
before using the second split.

Team ownership, module boundaries, and PR rules are in
[docs/TEAM_ROLES.md](docs/TEAM_ROLES.md) and [CONTRIBUTING.md](CONTRIBUTING.md).
Competing NLP and algorithm variants belong under `experiments/`; use
[docs/EXPERIMENT_WORKFLOW.md](docs/EXPERIMENT_WORKFLOW.md) so every candidate can
be compared without replacing the official Agent.

## Selected Backend

The production `starter.agent.Agent` now uses Tung Lam Nguyen's data-safe
inverse-card reconstruction plus finite-horizon Top-K policy with a uniform
product prior. It is packaged independently under `submission/` and requires no
network, API key, model download, or third-party runtime dependency.

Verified on the shared generated-dev split on 31 August 2026:

| Variant | Sessions | Hit Rate@10 | MRR | MTTC | Score |
|---|---:|---:|---:|---:|---:|
| Previous exact-evidence backend | 2,000 | 0.9865 | 0.852769 | 2.7010 | 0.915061 |
| Selected uniform inverse-DP | 2,000 | 0.9935 | 0.977300 | 2.6255 | 0.957430 |
| Catalog `rating_number` ablation | 2,000 | 0.9935 | 0.975782 | 2.6860 | 0.955765 |

No organizer-public session was used to select these variants. The selected
backend preserves a recovery universe whenever NLP is uncertain, so a parser
mistake can narrow the active focus without permanently deleting every fallback
candidate. See [docs/TEAM_BASELINE.md](docs/TEAM_BASELINE.md) and
[submission/README.md](submission/README.md).

Unknown wrappers use catalog-guided exact-span fallback and are recorded as
`catalog_fallback`; that evidence affects ranking but cannot destructively
intersect the candidate pool. Explicit requirement wrappers remain strong
evidence. The next NLP problem is value-level semantics such as
`not wet in rain -> waterproof`, which this parser intentionally does not guess.
The ownership and future matcher contract are documented in
[docs/TEAM_ROLES.md](docs/TEAM_ROLES.md).

## Lightweight Input NLP

`starter/parser.py` uses only Python's standard library. It recognizes families
of category, requirement, preference, no-preference, negation, and override
messages; normalizes smart punctuation; and preserves the raw constraint span
for catalog matching. Explicit disclosure is parsed before generic negation so
metadata such as `holds effectively without wiggling` is not corrupted.

If a private message changes only the surrounding prose, the Agent can recover
exact one-word or multi-word catalog atoms without an LLM call. It also handles
two values joined by a semicolon or `and`, but does not claim semantic equivalence
between differently worded values.

On an Apple M4 with the 50,000-product catalog, the final parser averaged about
`8.7 µs` per recognized message. Normal catalog fallback averaged `0.075 ms`
with p95 `0.11 ms`. Building the full in-memory index takes about `5.3 s` once
at process startup.

## What You Receive

- A frozen catalog of 50,000 products from the `Clothing_Shoes_and_Jewelry` category of Amazon Reviews 2023.
- 200 labeled public sessions for local development.
- A weak BM25 starter agent and deterministic local evaluator.
- The Agent API contract and scoring rules.

The organizer keeps 800 additional sessions private for final evaluation.

## Task

For each session, your agent receives an anonymized preference profile and a short customer message. Raw user IDs, review text, timestamps, and purchase history are never disclosed. On every turn the agent may:

- ask a natural clarification question in `message` and identify one requested field in `ask_attribute`;
- return a ranked list of up to 10 catalog `parent_asin` values;
- do both in the same response.

The session ends when the target product appears in the scored Top 10 or after turn 10. Sessions cover Buying, Browsing, Intent Override, and Boundary behavior.

## Download the Catalog

Download `catalog.jsonl.gz` from the GitHub Release attached to this repository, then run:

```bash
gzip -dk catalog.jsonl.gz
mv catalog.jsonl data/catalog.jsonl
```

Verify the downloaded file using the published `SHA256SUMS` file.

## Run the Starter

Python 3.10 or later is recommended. The starter uses only the Python standard library.

```bash
python3 -m evaluator.local_evaluator
```

Edit the team-owned modules and keep `starter/agent.py` as the official adapter.
Do not edit the evaluator or public labels when reporting a local score.
The command writes per-session results and aggregate metrics to `results.json`.

The organizer's weak starter scores Hit Rate@10 `0.125`, MRR `0.068034`, and
MTTC `9.81` on the released public set; see `docs/baseline_results.json`. The
current `starter/agent.py` is the team's selected offline inverse-DP backend.
Those public numbers are retained as historical references, not as candidate
selection metrics; `make evaluate` is reserved for the frozen integration build.

## Agent Interface

```python
class Agent:
    def reset(self, session_id: str, user_profile: dict) -> None:
        ...

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
        return {
            "message": "Do you have a material preference?",
            "ask_attribute": "material",
            "recommendations": [
                {"parent_asin": "B000..."},
                {"parent_asin": "B001..."}
            ],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30}
        }
```

`ask_attribute` is one of `category`, `material`, `color`, `size`, `style`, `brand`, `budget`, `feature`, `use_case`, `other`, or `null`. See `docs/agent_api_contract.json`.

## Technical Metrics

- **Hit Rate@10:** fraction of sessions that find the target within 10 turns.
- **MRR:** mean reciprocal rank of the target; a miss contributes zero.
- **MTTC:** mean first-hit turn; a miss is assigned turn 11.
- **Reported token usage:** prompt and completion tokens returned by the team's model client.

```text
TechnicalScore = 0.50 × HitRate@10 + 0.30 × MRR + 0.20 × Efficiency
Efficiency = clip((11 - MTTC) / 10, 0, 1)
```

`TechnicalScore` is an objective input to the `Technical Execution` assessment.
It is not a separate judging criterion and does not represent the entire
`Technical Execution` score.

Only exact `parent_asin` equality produces a hit. Core metrics are also reported by scenario.

## Model Choice and Cost

Teams may use any legally accessible LLM API or local model. Teams manage their own credentials and must never commit API keys. Model choice, estimated cost, token usage, and latency must be disclosed. Token usage is a feasibility metric, not part of the core technical score. The organizer does not provide or reimburse model API credits; teams are responsible for any costs incurred through optional external services.

## Files

```text
data/public_set.jsonl             200 labeled development sessions
data/unseen_eval/                 ignored, reproducible shared test outputs
docs/competition_specification.md participant rules and evaluation protocol
docs/agent_api_contract.json      machine-readable Agent contract
docs/evaluation_config.json       scoring configuration
docs/baseline_results.json        reproducible weak-starter reference score
docs/TEAM_BASELINE.md             verified team metrics and caveats
docs/TEAM_ROLES.md                five-person ownership and module contracts
docs/EXPERIMENT_WORKFLOW.md       isolated candidate and PR/MR rules
experiments/                      competing NLP and algorithm implementations
scripts/build_unseen_official_sessions.py deterministic shared test generator
scripts/run_paraphrase_stress_eval.py      input-language robustness test
scripts/evaluate_candidate.py              isolated generated-dev candidate runner
scripts/evaluate_independent_paraphrases.py independent 100-case NLP runner
tests/fixtures/independent_human_paraphrases.jsonl frozen human-style NLP cases
starter/agent.py                  compatibility adapter to the selected backend
starter/parser.py                 compatibility export for the input parser
submission/agent.py               self-contained competition entry file
submission/src/shopping_copilot/  parser, state, recovery, inverse filtering, DP
evaluator/local_evaluator.py      public-set simulator and scorer
```

## Judging and Submission Policy

- Participant submission requirements: `docs/submission_rules.md`
- Event rules and working checklist: `TECHJAM_PLAN.md`
- Team workflow: `CONTRIBUTING.md`

## Data Source

The catalog and sessions are derived from Amazon Reviews 2023 by McAuley Lab, UCSD. See `DATA_ATTRIBUTION.md` before using or redistributing the data.
Sessions are sampled deterministically from the official Clothing 5-core leave-last-out split and joined to the frozen catalog.
