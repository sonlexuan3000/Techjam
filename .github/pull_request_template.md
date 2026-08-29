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
| Independent human-style 100 (NLP) | | | |
| Generated-dev 2,000 (algorithm) | | | |
| Relevant robustness benchmark | | | |
| Organizer public 200 (integration PR only) | n/a | n/a | n/a |

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
- [ ] I did not use or inspect organizer-public per-case results to tune or
      select this candidate.
- [ ] `make test` passes.
- [ ] `make human-stress ENTRYPOINT=...` was run for an NLP experiment.
- [ ] `make evaluate-candidate-dev ENTRYPOINT=...` was run for an algorithm experiment.
- [ ] `make integration-check` was run only if this is the frozen winner-integration PR.
