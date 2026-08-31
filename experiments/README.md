# Preserved experiments

This directory is development evidence, not the competition entrypoint. The
selected runtime is exported from `submission/agent.py` and mirrored through
`starter/agent.py` for the released evaluator.

The retained inverse-DP experiment records:

- the original algorithm contribution and reviewed integration;
- the shipped offline review prior plus uniform and catalog `rating_number`
  ablations;
- the public-selection and generated-distribution tradeoff;
- focused inverse-card, DP, state, and parity tests;
- commands that reproduce the pre-integration comparison.

Candidates were isolated under `experiments/` during development so they could
be benchmarked without replacing the official Agent. Reproducible candidates
retain their metrics and tests. The small `nlp/khoa-tbd` folder is explicitly
marked as an abandoned placeholder and is not runnable, selected, or part of
the submission.

For the shipped architecture and canonical metrics, use
[`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) and
[`docs/EVALUATION.md`](../docs/EVALUATION.md).
