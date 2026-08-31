# Conservative Dynamic-K candidate

This directory contains only the highest-scoring validated `vinh-greedy`
candidate. It inherits the shared `starter.Agent` parser and ranking unchanged,
then uses a frozen target-independent policy artifact to choose how many of the
baseline-ranked unseen products to emit.

Runtime files:

- `entrypoint.py`: required `build_agent(catalog_path)` contract.
- `agent.py`: exactly-once parsing, inherited baseline ranking, Dynamic K, and
  the fixed `ask_attribute = "other"` question policy.
- `k_policy.py`: observable state encoding and conservative artifact lookup.
- `k_policy.json`: frozen accepted policy artifact.

Rejected SIGMA, Pareto, training, oracle, and unused model artifacts were
removed after dev ablation. The final measured results are:

| Dataset | HR@10 | MRR | MTTC | Efficiency | Technical |
|---|---:|---:|---:|---:|---:|
| generated dev (2,000) | 0.986500 | 0.860010 | 2.715500 | 0.828450 | **0.916943** |
| public (200) | 0.995000 | 0.957131 | 2.080000 | 0.892000 | **0.963039** |

Reproduce without writing result files into the repository:

```bash
PYTHONDONTWRITEBYTECODE=1 make test
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -v \
  -s experiments/algo/vinh-greedy/tests
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/evaluate_candidate.py \
  --entrypoint experiments/algo/vinh-greedy/entrypoint.py \
  --catalog data/catalog.jsonl \
  --dataset data/unseen_eval/dev_set.jsonl \
  --output /tmp/vinh-greedy-dev.json
```
