## Type

- [ ] NLP experiment
- [ ] Algorithm experiment
- [ ] Shared evaluation/infrastructure
- [ ] Winner integration

Experiment folder (if applicable): `experiments/...`

## Hypothesis and scope

- Base commit used for comparison:
- Hypothesis:
- Files/components changed:
- Files/components intentionally unchanged:

## Reproduce

```bash
# Paste exact commands from repository root.
```

## Results

| Suite | Baseline | This PR | Delta |
|---|---:|---:|---:|
| Public Technical Score | | | |
| Generated-dev Technical Score | | | |
| Relevant robustness benchmark | | | |

- Scenario regressions:
- Target survival / false elimination, if filtering changed:
- Mean and p95 latency:
- Startup time / memory:
- Token or external API cost:

## Failures and trade-offs

List known failures, ambiguous cases, and every metric that became worse.

## Checklist

- [ ] My candidate is isolated under one `experiments/nlp/...` or
      `experiments/algo/...` folder, or this is explicitly an integration PR.
- [ ] I did not modify protected evaluator inputs or scoring rules.
- [ ] I did not directly replace `starter/agent.py` in an experiment PR.
- [ ] I added focused tests for the changed behavior.
- [ ] I used the same frozen inputs and base commit as competing candidates.
- [ ] I reported regressions and did not tune on a claimed unseen set.
- [ ] `make test` passes.
- [ ] `make evaluate` passes.
- [ ] `make evaluate-unseen-dev` was run for an algorithm change.
- [ ] `make stress` was run for an NLP change.
