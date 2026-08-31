# NLP candidate: `khoa-tbd`

- Owner: Khoa
- Base commit: `c5987f514c418bed295be3be81ba0a94361323f8`
- Status: draft

## Hypothesis

TBD once the NLP approach is selected.

## Scope

- Parser/state changes: TBD
- Catalog semantic matching changes: TBD
- External model or API: None currently
- New dependencies: None currently

## Entrypoint and reproduction

`entrypoint.py` exposes `build_agent(catalog_path)` and must eventually return an
Agent with the official `reset`/`respond` interface. For the shared NLP
diagnostic, the Agent must also expose `debug_state(session_id)` and either
`debug_clue_candidates(clue)` or the baseline-compatible `_clue_candidates`.

```bash
make human-stress
make human-stress ENTRYPOINT=experiments/nlp/khoa-tbd/entrypoint.py
```

## Results

| Suite | Baseline | Candidate | Delta |
|---|---:|---:|---:|
| Independent 100 benchmark pass rate | | | |
| Content-aware fact-state pass rate | | | |
| Catalog grounding pass rate | | | |
| Polarity pass rate | | | |
| Worst scenario pass rate | | | |

- Mean/p95 message latency: TBD
- Startup time and memory: TBD
- Token/API cost: TBD

Do not run the organizer public 200 for this candidate. The integration owner
runs it only after the NLP and algorithm winners are frozen.

## Failure analysis

- False positives or false negations: TBD
- Override/no-preference failures: TBD
- Known unsupported wording: TBD

## Files

- `entrypoint.py`: Adapter from the experiment runner to the candidate Agent.
- `src/`: Candidate-specific NLP implementation.
- `tests/`: Focused tests for this candidate.
