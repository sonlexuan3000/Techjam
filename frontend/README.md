# Conversation viewer

The local viewer turns an evaluation session definition into an animated
shopping dialogue. By default the picker includes all 200 organizer-public
development sessions plus a deterministic 20-session preview from the shared
2,000-session generated-development split. It uses the same customer policy,
override timing, hit rules, and ten-turn limit as
`evaluator/local_evaluator.py`.

## Run it

From the repository root:

```bash
make frontend
```

Then open <http://localhost:8787>. The first startup takes several seconds
because the selected candidate builds its 50,000-product search index once.
`make frontend` also creates the reproducible generated split when it is not
already present. Generated-dev entries are visibly labeled and can be isolated
with the dataset filter.

The default is the selected production backend,
`experiments/algo/tunglam-inverse-dp-review-prior/entrypoint.py`. It uses the
offline review-prior inverse-DP configuration that scored `0.958456` on the
2,000-session generated-dev split. To preview another experiment:

```bash
.venv/bin/python frontend/server.py \
  --entrypoint experiments/algo/<owner>-<approach>/entrypoint.py
```

Optional flags are `--host`, `--port`, `--catalog`, `--dataset`,
`--generated-dataset`, and `--generated-limit`. Set `--generated-limit 0` to
show only the primary dataset, or raise it to preview more than the default 20.

## How it works

- `GET /api/sessions` returns safe chooser metadata with public/generated source
  labels. Ground truth and generated intent fields are deliberately omitted.
- `POST /api/simulate` accepts a public ID such as `public_0001` or a generated
  ID such as `unseen_dev_00001`, then runs the chosen candidate against the
  canonical simulated customer.
- The returned transcript contains the assistant's text, requested attribute,
  and catalog-enriched recommendation cards for every turn.
- Between each customer message and agent reply, a right-aligned calculation
  card shows target-free algorithm diagnostics: surviving hypotheses, evaluated
  finite-horizon DP states, selected Top-K, retrieval route, prior, and runtime.
  It switches to “Calculation complete” and remains in the transcript for that
  turn.
- The browser can auto-play, pause, step through, replay, filter sessions, pick
  a random session, and copy the completed transcript.

The server uses Python's standard library and the frontend has no build step or
external runtime dependency.

The generated-development split is a visible, deterministic robustness fixture;
it is not organizer-private test data or an estimate of the private target set.
