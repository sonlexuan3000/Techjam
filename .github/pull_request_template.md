## Summary

- Problem:
- Approach:
- User-visible/runtime effect:

## Verification

```bash
make test
```

- Additional benchmark commands:
- Dataset and base commit:
- Before/after HR@10, MRR, MTTC, and Technical Score:
- Latency, memory, token, or cost change:

## Risks and limitations

- Failure modes:
- Scenario regressions:
- Recovery/target-survival impact:

## Checklist

- [ ] I preserved the required `Agent.reset` / `Agent.respond` contract.
- [ ] I did not modify evaluator inputs or scoring rules to improve results.
- [ ] I did not commit generated data, secrets, catalogs, or private labels.
- [ ] I added or updated focused tests.
- [ ] I scoped every metric claim to the dataset actually measured.
- [ ] I documented new dependencies, APIs, model usage, latency, and cost.
- [ ] `make test` passes.
