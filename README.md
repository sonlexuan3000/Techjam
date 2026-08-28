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
make evaluate
```

Generate the same target-disjoint test suites on every teammate's machine:

```bash
make unseen-data
make evaluate-unseen-dev
make stress
```

`make unseen-data` deterministically builds 2,000 shared dev sessions and 800
shared regression sessions from official catalog products that are not public-set
targets. Generated files stay ignored; the committed generator and fixed seed
make them reproducible. They are robustness tests, not leaked or predicted
organizer-private data. Read [data/unseen_eval/README.md](data/unseen_eval/README.md)
before using the second split.

Team ownership, module boundaries, and PR rules are in
[docs/TEAM_ROLES.md](docs/TEAM_ROLES.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

## Current Working Baseline

Verified locally on 28 August 2026:

| Suite | Sessions | Hit Rate@10 | MRR | MTTC | Score |
|---|---:|---:|---:|---:|---:|
| Official public | 200 | 0.995 | 0.952548 | 2.0700 | 0.961864 |
| Shared synthetic dev | 2,000 | 0.987 | 0.853885 | 2.7005 | 0.915655 |
| Paraphrase stress | 200 | 0.230 | 0.065052 | 9.8650 | 0.157216 |

The synthetic-dev result suggests the retrieval/ranking strategy transfers to
new catalog targets. The large paraphrase drop shows that input parsing is the
current P0 weakness. Stress results are diagnostics, not a claim about private
test wording. See [docs/TEAM_BASELINE.md](docs/TEAM_BASELINE.md).

The current architecture priority is not more destructive filtering. Parser
output must carry confidence, soft or uncertain constraints should affect
scores, and retrieval must keep a recovery path so one NLP mistake cannot remove
the true product permanently. The revised ownership and contract are documented
in [docs/TEAM_ROLES.md](docs/TEAM_ROLES.md).

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
current `starter/agent.py` is the team's stronger deterministic working baseline,
so run `make evaluate` for its current score.

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
scripts/build_unseen_official_sessions.py deterministic shared test generator
scripts/run_paraphrase_stress_eval.py      input-language robustness test
starter/agent.py                  official interface and current team baseline
evaluator/local_evaluator.py      public-set simulator and scorer
```

## Judging and Submission Policy

- Participant submission requirements: `docs/submission_rules.md`
- Event rules and working checklist: `TECHJAM_PLAN.md`
- Team workflow: `CONTRIBUTING.md`

## Data Source

The catalog and sessions are derived from Amazon Reviews 2023 by McAuley Lab, UCSD. See `DATA_ATTRIBUTION.md` before using or redistributing the data.
Sessions are sampled deterministically from the official Clothing 5-core leave-last-out split and joined to the frozen catalog.
