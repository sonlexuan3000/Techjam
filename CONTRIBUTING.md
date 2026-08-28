# Team workflow

## Before coding

1. Run `make setup`, `make test`, and `make evaluate`.
2. Read `docs/TEAM_ROLES.md` and stay inside the agreed module ownership.
3. Branch from `main` with a focused name such as `feat/input-parser`,
   `feat/retrieval`, `feat/question-policy`, or `test/unseen-eval`.

Do not commit directly to `main` during implementation. Use a pull request so a
second teammate can review score changes and contract compatibility.

## Protected competition inputs

Do not modify these files to improve a reported score:

- `evaluator/local_evaluator.py`
- `data/public_set.jsonl`
- `docs/evaluation_config.json`
- the downloaded `data/catalog.jsonl`

Do not commit API keys, `.env`, generated results, catalog copies, organizer
private data, or third-party datasets with unclear redistribution terms.

## Pull request checklist

Every algorithm PR should include:

- the hypothesis and files changed;
- public score before and after;
- generated-dev score before and after;
- scenario-level regressions, if any;
- unit tests for new parser/state/policy behavior;
- latency or memory impact when an index/model changes.

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

## Integration rule

Only the integration owner should resolve changes to `starter/agent.py`. Other
owners implement and test their modules behind the interfaces documented in
`docs/TEAM_ROLES.md`. A contract change needs agreement from the integration
owner and every affected module owner before merge.

The event build window starts on 29 August 2026 at 12:00 Singapore time. Keep
the migration/setup commit separate, and make substantive implementation commits
during the official window so the repository clearly demonstrates significant
post-start development.
