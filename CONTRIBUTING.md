# Team workflow

## Before coding

1. Run `make setup`, `make test`, and `make evaluate`.
2. Read `docs/TEAM_ROLES.md` and stay inside the agreed module ownership.
3. For a competing implementation, branch from `main` as
   `exp/nlp/<owner>-<approach>` or `exp/algo/<owner>-<approach>`. Use a normal
   `feat/...` or `test/...` branch only for shared infrastructure.

Do not commit directly to `main` during implementation. Use a pull request so a
second teammate can review score changes and contract compatibility.

## Competing NLP and algorithm implementations

Do not add top-level folders such as `nlp-alice/` or `algo-bob/`, and do not
replace the official baseline in an experiment PR. Use this layout instead:

```text
experiments/
  nlp/<owner>-<approach>/
  algo/<owner>-<approach>/
```

For example: `experiments/nlp/son-regex-catalog/` or
`experiments/algo/an-information-gain/`. Including both owner and approach makes
the folder understandable after team roles change.

Copy the matching `_template/README.md`, keep all variant-specific code and
tests inside that one folder, and expose the official `reset`/`respond` Agent
contract through an adapter. An experiment PR may not edit `starter/agent.py`,
the active `starter/parser.py`, shared evaluator files, or another person's
experiment. If shared infrastructure must change, open a separate PR first.

Detailed layout, comparison rules, and the winner-selection process are in
[`docs/EXPERIMENT_WORKFLOW.md`](docs/EXPERIMENT_WORKFLOW.md). GitHub calls the
review item a pull request; the same rules apply if the team calls it an MR.

## Protected competition inputs

Do not modify these files to improve a reported score:

- `evaluator/local_evaluator.py`
- `data/public_set.jsonl`
- `docs/evaluation_config.json`
- the downloaded `data/catalog.jsonl`

Do not commit API keys, `.env`, generated results, catalog copies, organizer
private data, or third-party datasets with unclear redistribution terms.

## Pull request checklist

Every NLP or algorithm experiment PR should include:

- experiment type and folder path;
- the exact baseline commit used for comparison;
- the hypothesis and files changed;
- public score before and after;
- generated-dev score before and after;
- scenario-level regressions, if any;
- Target Survival Rate and False Elimination Rate for filtering changes;
- candidate-pool size before/after each newly applied constraint;
- unit tests for new parser/state/policy behavior;
- latency or memory impact when an index/model changes.

Use the repository PR template. Report regressions as well as improvements;
do not tune an implementation after seeing a sealed comparison set and then
report that same set as unseen.

Run at least:

```bash
make test
make evaluate
make evaluate-unseen-dev
```

Use `make stress` for any input-parser change. The committed seed is visible, so
the generated 800-row split is only a shared regression check, not a truly hidden
holdout. If the team wants one internal sealed check, the evaluation owner should
generate it with a separate uncommitted seed and report only aggregate metrics.

Any PR that turns an inferred or soft constraint into a permanent hard deletion
must explain why the target remains recoverable when parsing or metadata is
wrong. An empty-pool fallback alone is insufficient because a wrong filter can
leave a non-empty pool that no longer contains the target.

## Integration rule

Only the integration owner should resolve changes to `starter/agent.py`. Other
owners implement and test their modules behind the interfaces documented in
`docs/TEAM_ROLES.md`. A contract change needs agreement from the integration
owner and every affected module owner before merge.

Merging an experiment folder makes it available for comparison; it does not make
that implementation the official Agent. After the comparison is frozen, the
integration owner opens a separate integration PR for the selected NLP variant,
the selected algorithm variant, and then benchmarks their combination.

The event build window starts on 29 August 2026 at 12:00 Singapore time. Keep
the migration/setup commit separate, and make substantive implementation commits
during the official window so the repository clearly demonstrates significant
post-start development.
