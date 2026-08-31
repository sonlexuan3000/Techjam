# Contributing

InverseCart's competition backend is frozen under `submission/`. Changes should
preserve the official Agent contract, reproducibility, and the distinction
between generated development data and organizer evaluation data.

## Local setup

```bash
make setup
make test
make demo
```

## Change guidelines

- Keep the competition entrypoint at `submission/agent.py` and the local-harness
  adapter at `starter/agent.py` compatible.
- Do not modify the released evaluator, scoring configuration, public labels,
  or catalog to improve a reported result.
- Do not commit catalogs, generated sessions/results, virtual environments,
  model weights, credentials, or private evaluation data.
- Use generated-development data for algorithm comparisons. Treat the organizer
  public 200 as an integration check, not a hyperparameter source.
- Add focused tests for state transitions, filtering, recovery, overrides, and
  response-contract changes.
- Report every metric regression and keep claims scoped to the dataset and
  protocol actually measured.
- Preserve the standard-library-only runtime unless a new dependency has a
  measured benefit and is declared in `submission/requirements.txt`.

## Pull-request checklist

```bash
make test
make evaluate-unseen-dev
make human-stress
python3 submission/smoke.py --catalog data/catalog.jsonl
```

If the implementation is already frozen, also verify the deterministic bundle:

```bash
make submission-archive
```

Document the base commit, exact reproduction commands, before/after metrics,
latency/cost changes, and known limitations in the pull request.
