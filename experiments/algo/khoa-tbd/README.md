# Algorithm candidate: `khoa-tbd`

- Owner: Khoa
- Base commit: `c5987f514c418bed295be3be81ba0a94361323f8`
- Status: rank-aware adaptive-K implemented and evaluated

## Hypothesis

A calibrated estimate of the target's current rank and the value of another
turn can choose `K in {1, 3, 5, 10}` to improve expected TechnicalScore over a
fixed Top-10 list. The target is used only to create offline development labels
and by the oracle; it is never an inference feature.

The requested subtraction objective is logged for audit, but is not used for
the deployed decision:

```text
Q_spec(K)    = immediate_hit_value - P(miss | K) * V_next
Q_bellman(K) = immediate_hit_value + P(miss | K) * V_next
```

For a shared non-negative `V_next`, `Q_spec` is monotone in K and selected
`K=10` on all 906 held-out decisions. The Bellman form is the meaningful
adaptive objective.

## Scope

- Retrieval/reranking formula and ordering: unchanged.
- Performance: identical consecutive score states are cached; filtering and K
  selection still run every turn.
- Top-K policy: four calibrated CDF heads estimate `P(R<=1/3/5/10)` and a
  shared lightweight head estimates `V_next`.
- Logging: CDFs, exact-rank masses, `V_next`, both Q equations, and selected K.
- Runtime dependencies: Python standard library only.
- Offline training dependency: NumPy.

## Development split and results

`data/unseen_eval/dev_set.jsonl` was scenario-stratified with seed `20260830`
into 1,400 fine-tuning, 300 calibration, and 300 untouched held-out sessions.

| Held-out policy | HR@10 | MRR | MTTC | TechnicalScore |
|---|---:|---:|---:|---:|
| Fixed K=1 | 0.913333 | 0.913333 | 3.760000 | 0.875467 |
| Fixed K=3 | 0.946667 | 0.800000 | 3.133333 | 0.870667 |
| Fixed K=5 | 0.960000 | 0.735611 | 2.913333 | 0.862417 |
| Fixed K=10 | 0.980000 | 0.670571 | 2.623333 | 0.858705 |
| Learned adaptive K | 0.973333 | 0.825575 | 3.046667 | **0.893406** |
| Target-aware oracle | 0.980000 | 0.973148 | 3.133333 | 0.939278 |

The learned policy gains `+0.034701` over fixed K=10 and `+0.017939` over the
best fixed policy. The oracle shows `+0.080573` theoretical upside over fixed
K=10. Learned choices across 906 turns were K=1: 468, K=3: 154, K=5: 75, and
K=10: 209.

Calibration means on the validation states closely matched observations:

| Event | Predicted | Observed | Brier |
|---|---:|---:|---:|
| R<=1 | 0.258713 | 0.261878 | 0.053012 |
| R<=3 | 0.360250 | 0.360589 | 0.068711 |
| R<=5 | 0.406436 | 0.405525 | 0.073208 |
| R<=10 | 0.472963 | 0.469613 | 0.088761 |

## Scenario notes

Compared with fixed K=10, adaptive K improved TechnicalScore by `+0.051333`
on boundary, `+0.037762` on browsing, and `+0.051098` on buying sessions. It
regressed by `-0.022730` on intent-override sessions, which is the main follow-up
area. Adaptive K also trades a small amount of Top-10 recall and speed versus
fixed K=10 for much higher MRR; that trade is positive under TechnicalScore.

### Override-turn K=10 guard experiment

The runtime now supports a temporary, target-free fallback on the exact
`O1_OVERRIDE` turn. If the learned action is shorter than 10 and its Bellman-Q
advantage over K=10 is at most a configured threshold, that turn is widened to
K=10. Later turns are unaffected. The base K, final K, Q margin, threshold, and
fallback reason are logged.

Thresholds `disabled, 0, .0025, .005, .01, .02, .03, .05` were compared only
on the 300-session calibration split. The disabled policy scored `0.893556`.
Thresholds through `.005` changed as many as 23 override-turn choices but had
the same score; thresholds from `.01` onward reduced MRR and TechnicalScore.
The selected setting is therefore **disabled**. The mechanism remains modular
for future models or datasets, without using the held-out split for tuning.

## Reproduction

The full run uses a reusable gzip trajectory cache:

```bash
.venv/bin/python experiments/algo/khoa-tbd/adaptive_k_experiment.py --workers 4
.venv/bin/python experiments/algo/khoa-tbd/adaptive_k_experiment.py \
  --override-guard-sweep --workers 4 \
  --output experiments/algo/khoa-tbd/adaptive_k_override_guard_validation.json
.venv/bin/python -m unittest discover -s experiments/algo/khoa-tbd/tests -v
```

Use `--workers 2` if memory is constrained. Use
`--q-mode requested-minus` only to reproduce the degenerate literal objective.
Do not run the organizer public 200 for this candidate; the integration owner
runs it only after the algorithm and NLP winners are frozen.

## Files

- `entrypoint.py`: loads the trained JSON policy when present.
- `src/agent.py`: existing retriever/reranker plus modular K selection hook.
- `src/adaptive_k.py`: target-free runtime features, calibrated model, Q values,
  and logging.
- `adaptive_k_experiment.py`: split, collection, oracle, training, calibration,
  fixed-policy comparisons, caching, and multiprocessing.
- `adaptive_k_model.json`: runtime model trained on fine-tuning/calibration data.
- `adaptive_k_results.json`: complete held-out metrics and per-turn audit logs.
- `adaptive_k_trajectories.jsonl.gz`: reusable offline labeled state cache.
- `adaptive_k_override_guard_validation.json`: validation-only guard sweep and
  selection diagnostics.
- `tests/test_adaptive_k.py`: 16 focused mathematical/runtime/integration tests.
