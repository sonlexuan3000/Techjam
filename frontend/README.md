# Conversation viewer

The local viewer turns one of the evaluation session definitions into an
animated shopping dialogue. It uses the same customer policy, override timing,
hit rules, and ten-turn limit as `evaluator/local_evaluator.py`.

## Run it

From the repository root:

```bash
make frontend
```

Then open <http://localhost:8787>. The first startup takes several seconds
because the selected candidate builds its 50,000-product search index once.

The default is the selected production backend,
`experiments/algo/tunglam-inverse-dp-review-prior/entrypoint.py`. It uses the
offline review-prior inverse-DP configuration that scored `0.958456` on the
2,000-session generated-dev split. To preview another experiment:

```bash
.venv/bin/python frontend/server.py \
  --entrypoint experiments/algo/<owner>-<approach>/entrypoint.py
```

Optional flags are `--host`, `--port`, `--catalog`, and `--dataset`.

## How it works

- `GET /api/sessions` returns safe chooser metadata. Ground truth and generated
  intent fields are deliberately omitted.
- `POST /api/simulate` accepts `{"sample_id": "public_0001"}` and runs the
  chosen candidate against the canonical simulated customer.
- The returned transcript contains the assistant's text, requested attribute,
  and catalog-enriched recommendation cards for every turn.
- The browser can auto-play, pause, step through, replay, filter sessions, pick
  a random session, and copy the completed transcript.

The server uses Python's standard library and the frontend has no build step or
external runtime dependency.
