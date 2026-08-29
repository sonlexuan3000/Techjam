# NLP candidate: `<owner>-<approach>`

- Owner:
- Base commit:
- Status: draft / ready for comparison

## Hypothesis

What wording failure should this parser or matcher solve?

## Scope

- Parser/state changes:
- Catalog semantic matching changes:
- External model or API:
- New dependencies:

## Entrypoint and reproduction

`entrypoint.py` must expose `build_agent(catalog_path)` and return an Agent with
the official `reset`/`respond` interface. For the shared NLP diagnostic it must
also expose `debug_state(session_id)` and either
`debug_clue_candidates(clue)` or the baseline-compatible `_clue_candidates`.

```bash
make human-stress
make human-stress ENTRYPOINT=experiments/nlp/<owner>-<approach>/entrypoint.py
```

## Results

| Suite | Baseline | Candidate | Delta |
|---|---:|---:|---:|
| Independent 100 benchmark pass rate | | | |
| Content-aware fact-state pass rate | | | |
| Catalog grounding pass rate | | | |
| Polarity pass rate | | | |
| Worst scenario pass rate | | | |

- Mean/p95 message latency:
- Startup time and memory:
- Token/API cost:

Do not run the organizer public 200 for this candidate. The integration owner
runs it only after the NLP and algorithm winners are frozen.

## Failure analysis

- False positives or false negations:
- Override/no-preference failures:
- Known unsupported wording:

## Files

Explain the purpose of each non-trivial file in this candidate folder.
