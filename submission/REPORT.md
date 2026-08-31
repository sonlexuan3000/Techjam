# Shopping Copilot technical report

## Method

The submitted backend is a deterministic, offline conversational retrieval
agent. It reconstructs the participant-visible four-value intent card for every
catalog product, treats each surviving product as a hypothesis, and eliminates
only hypotheses that conflict with trusted protocol evidence. The `other`
question partitions remaining hypotheses by the next two values the simulator
would reveal. A finite-horizon dynamic program balances immediate reciprocal
rank reward against the expected value of another clarification turn.

Recognized paraphrases are normalized by a dependency-free parser. Their
candidate matches form a high-priority focus tier, while a recovery universe is
retained so uncertain NLP cannot permanently remove the hidden target. Explicit
same-slot overrides update active intent and scored-miss history.

## Models, development tools, and cost

- Runtime language model: none.
- Retrieval database/vector service: none.
- Runtime dependencies: Python standard library only.
- Network/API credentials: none.
- Prompt/completion tokens: zero.
- Estimated marginal runtime model cost: zero.
- Data used at runtime: organizer-supplied catalog and evaluator messages only.
- Development assistance: OpenAI Codex was used for repository inspection,
  code review, refactoring, test generation, benchmark orchestration, and
  documentation. It is not imported by or called from the submitted runtime.
  Development usage was covered by the team's existing account and was not
  separately metered as a per-session competition cost.
- The independent 100-case human-style diagnostic is model-generated test data;
  it has zero organizer-public target overlap and is not used at runtime.

## Candidate selection

All variants were selected on the shared 2,000-session generated-dev split,
never on the organizer public 200.

| Variant | HR@10 | MRR | MTTC | Technical Score |
|---|---:|---:|---:|---:|
| Previous exact-evidence backend | 0.9865 | 0.852769 | 2.7010 | 0.915061 |
| Uniform inverse-DP belief prior, selected | 0.9935 | 0.977300 | 2.6255 | 0.957430 |
| Catalog `rating_number` ablation | 0.9935 | 0.975782 | 2.6860 | 0.955765 |

The uniform prior applies to trusted inverse-DP hypotheses. In uncertain NLP
recovery only, `rating_number` remains a tie-break among equally relevant
catalog matches; it does not control eligibility or hard filtering.

After the implementation was frozen at commit `f84a72e`, the shared 800-session
second split scored HR@10 `0.9975`, MRR `0.980420`, MTTC `2.5850`, and Technical
Score `0.961176`. Its seed is public, so this is a post-freeze regression check,
not a claim about organizer-private performance.

## Performance and reproducibility

The full catalog contains 50,000 products. An Apple M4 measurement showed
`5.75 s` startup and about `199 MiB` maximum RSS. Across 500 turns from 200
generated-dev sessions, response latency was `30.045 ms` mean, `2.368 ms`
median, `136.585 ms` p95, and `847.916 ms` maximum. Per-turn inference is local
and requires no model call. The exact commands are:

```bash
make setup
make test
make evaluate-unseen-dev
make demo
```

## Limitations

- General value-level semantic paraphrases remain weak; recovery prevents a
  destructive hard filter but cannot guarantee good early ranking. The frozen
  human-style diagnostic grounded `1/35` semantic-value paraphrases and passed
  `1/100` complete state-plus-grounding cases.
- The policy assumes the released card construction, disclosure order, scenario
  mixture, score function, and ten-turn horizon.
- The anonymized profile is retained but not used for ranking because no safe,
  measured personalization gain has been established.
- The in-memory Agent is intended for the evaluator's sequential execution and
  requires external synchronization if wrapped by a concurrent web server.

## Contribution record

This list contains the Track 4 contributions verifiable in the repository at
the integration freeze. Any separate off-repository contribution should be
added to the Devpost record by the team representative only after verification.

- Tung Lam Nguyen: original inverse-card filtering and finite-horizon DP
  candidate.
- Lê Xuân Sơn: Track 4 repository/evaluation setup, data-safety review, NLP
  recovery integration, winner selection, official adapter, tests, and release
  packaging.
