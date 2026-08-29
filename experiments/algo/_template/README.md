# Algorithm candidate: `<owner>-<approach>`

- Owner:
- Base commit:
- Status: draft / ready for comparison

## Hypothesis

What ranking, filtering, question, or Top-K decision should improve the score?

## Scope

- Filtering changes:
- Ranking changes:
- Question policy changes:
- Top-K schedule changes:
- New dependencies:

## Entrypoint and reproduction

`entrypoint.py` must expose `build_agent(catalog_path)` and return an Agent with
the official `reset`/`respond` interface.

```bash
# Exact commands used to reproduce every row below
```

## Results

| Suite | HR@10 | MRR | MTTC | Technical Score |
|---|---:|---:|---:|---:|
| Public baseline | | | | |
| Public candidate | | | | |
| Generated-dev baseline | | | | |
| Generated-dev candidate | | | | |

- Scenario-level regressions:
- Target Survival Rate:
- False Elimination Rate:
- Mean/p95 turn latency:
- Startup time and memory:

## Ablation

Show which individual change causes the gain. Do not bundle unrelated ranking,
filtering, and dialogue-policy changes without an ablation.

## Failure analysis

- Cases improved:
- Cases regressed:
- Recovery behavior after a wrong or conflicting constraint:

## Files

Explain the purpose of each non-trivial file in this candidate folder.
