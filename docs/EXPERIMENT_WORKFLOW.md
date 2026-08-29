# Competing implementation workflow

The team may have several NLP parsers and several search/dialogue algorithms at
the same time. Keep them isolated and comparable until the team chooses a
winner. An experiment merged under `experiments/` is a candidate, not the
official submission.

## Folder and branch names

Use one folder per candidate:

```text
experiments/
  nlp/
    <owner>-<approach>/
      README.md
      entrypoint.py
      src/
      tests/
  algo/
    <owner>-<approach>/
      README.md
      entrypoint.py
      src/
      tests/
```

Use lowercase kebab-case. Good examples are `minh-spacy-rules`,
`son-regex-catalog`, and `an-information-gain`. A person's name alone is not
enough because it does not explain the approach.

Use the same slug for the branch:

```text
exp/nlp/son-regex-catalog
exp/algo/an-information-gain
```

Do not create `nlp-son/` or `algo-an/` at repository root. Do not copy the
50,000-product catalog, generated result files, virtual environments, model
weights, or secrets into an experiment folder.

## Create an experiment PR/MR

Start from the same `main` commit as the other candidates in the comparison
round. For an NLP candidate:

```bash
git switch main
git pull --ff-only
git switch -c exp/nlp/yourname-regex-catalog
mkdir -p experiments/nlp/yourname-regex-catalog
cp experiments/nlp/_template/README.md \
  experiments/nlp/yourname-regex-catalog/README.md
cp experiments/nlp/_template/entrypoint.py \
  experiments/nlp/yourname-regex-catalog/entrypoint.py
```

Use `experiments/algo/...` and the algorithm template for an algorithm candidate.
If code already exists elsewhere, copy only the candidate source and focused
tests into this folder, then add the adapter described below.

After filling the README and running the benchmarks:

```bash
git add experiments/nlp/yourname-regex-catalog
git commit -m "exp: add yourname-regex-catalog NLP candidate"
git push -u origin exp/nlp/yourname-regex-catalog
```

Open a draft PR/MR into `main`, use the title format at the end of this document,
and complete `.github/pull_request_template.md`. Mark it ready only when another
teammate can reproduce the result from the commands in the candidate README.

## Required experiment contract

Each candidate must:

1. keep all candidate-specific implementation, tests, and dependencies inside
   its own folder;
2. include `entrypoint.py` with a `build_agent(catalog_path)` function;
3. return an object implementing the official `reset` and `respond` methods;
4. include one command, runnable from repository root, that reproduces every
   reported metric;
5. record the exact base commit, assumptions, dependencies, latency, and known
   failures in its README.

Suggested adapter shape:

```python
def build_agent(catalog_path: str):
    return MyCandidateAgent(catalog_path)
```

The returned Agent must follow `docs/agent_api_contract.json`. An NLP candidate
may wrap the current ranking policy; an algorithm candidate may wrap the current
parser. This isolates the component being compared.

The independent NLP runner also needs diagnostic-only methods so it can score
state extraction and grounding without guessing from final recommendations:

```python
def debug_state(session_id: str) -> dict:
    ...

def debug_clue_candidates(clue: str, *, category: str | None = None) -> set[str]:
    ...
```

`debug_state` uses the active baseline's category/current-intent/negative/history
shape. The grounding set should include plausible matches but must be selective;
it must contain the concrete target, cover at least 25% route-aware catalog
reference precision, and stay below 25% of the full catalog. Returning the whole
catalog or the same 100 visible targets for every clue fails. For compatibility,
the runner also accepts `_clue_candidates(clue)` returning `(set[str], route)`.

## What an experiment PR may change

An experiment PR normally changes only:

```text
experiments/<nlp-or-algo>/<owner>-<approach>/**
```

It must not directly modify:

- `starter/agent.py` or the active implementation under `starter/`;
- `evaluator/local_evaluator.py` or scoring configuration;
- public labels, catalog data, or frozen comparison fixtures;
- another candidate's folder.

If a shared adapter, runner, or fixture is missing, create it in a small separate
infrastructure PR. This keeps candidate reviews free of hidden evaluator changes.

## Fair comparison

All candidates in one comparison round use the same baseline commit, datasets,
Top-K limit, machine, and timeout. Freeze the comparison inputs before opening
the result table.

| Candidate type | Primary checks | Safety checks |
|---|---|---|
| NLP | independent 100-case category, fact-state, polarity, and grounding metrics | per-scenario failures, raw-value preservation, latency |
| Algorithm | generated-dev 2,000 Technical Score, HR, MRR, MTTC | worst scenario, target survival, false elimination, latency |

Use only these candidate-comparison commands:

```bash
# NLP: baseline, then isolated candidate
make human-stress
make human-stress ENTRYPOINT=experiments/nlp/<owner>-<approach>/entrypoint.py

# Algorithm: baseline, then isolated candidate
make evaluate-unseen-dev
make evaluate-candidate-dev ENTRYPOINT=experiments/algo/<owner>-<approach>/entrypoint.py
```

The 100 NLP cases are independent, model-generated human-style diagnostics, not
organizer data or proof of private wording. They are committed so comparisons
are reproducible; do not special-case messages or case IDs. Generated-dev is
also a visible shared development set, so an improvement still needs focused
tests and scenario-level failure analysis.

### Organizer-public firewall

Experiment owners must not run `make evaluate`, inspect public per-session
failures, or use the organizer 200 for hyperparameters, ablations, candidate
selection, or winner selection. Existing public scores are historical references
only. The integration owner runs them after both winners and their settings are
frozen.

For NLP, report wrapper-only paraphrases separately from value-level semantic
paraphrases. A parser that extracts `not wet in rain` correctly has not
necessarily matched it to `waterproof`.

For algorithms, do not select from Technical Score alone when a small gain comes
from permanently removing the target in another scenario. Include scenario-level
metrics and any target-survival regression.

## Selecting and integrating winners

1. Merge valid experiment folders so everyone can reproduce them.
2. Freeze the comparison commit and run NLP on the independent 100 and algorithms
   on generated-dev with the same commands.
3. Select one NLP candidate and one algorithm candidate using the table above.
4. The integration owner creates a new branch from `main` and adapts only the
   selected candidates into `starter/`.
5. Benchmark the combined system again. Two individually strong components can
   interact badly, especially around confidence, hard filters, and overrides.
6. Freeze the combined code and settings, then have the integration owner run
   `make integration-check` once on the organizer public 200. Use it to catch an
   Agent-contract/protocol regression, not to reopen public-driven tuning.
7. Merge the integration PR only after required checks pass. Keep losing
   candidates under `experiments/` until submission decisions are final, then
   archive them if desired.

Do not ask every teammate to resolve conflicts in `starter/agent.py`; that is the
integration owner's job after winner selection.

## PR/MR naming

Use one of these titles:

```text
[EXP][NLP] <owner>-<approach>: <short hypothesis>
[EXP][ALGO] <owner>-<approach>: <short hypothesis>
[INTEGRATION] combine <nlp-candidate> with <algo-candidate>
```

Fill in `.github/pull_request_template.md` completely. A candidate without a
reproduction command or before/after table is not ready for comparison.
