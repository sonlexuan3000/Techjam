# Conversation viewer

The local viewer turns one of the evaluation session definitions into an
animated shopping dialogue. It uses the same customer policy, override timing,
hit rules, and ten-turn limit as `evaluator/local_evaluator.py`. It is an
optional demo adapter, not part of the submitted Agent or official scoring.

## Run it

From the repository root:

```bash
make frontend
```

Then open <http://localhost:8787>. The first startup takes several seconds
because the selected candidate builds its 50,000-product search index once.

The default adapter uses the same selected review-prior inverse-DP core and
configuration as `submission/agent.py`, loaded through the historical experiment
entrypoint
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
  catalog-enriched recommendation cards, and a compact target-free candidate
  funnel for every turn: previous pool, remaining candidates, products shown,
  and up to two matched grounded evidence values. NLP recovery and an active
  intent-override phase receive a small badge; deeper diagnostics stay in the
  technical documentation instead of crowding the video view.
- Playback shows a left-aligned customer typing indicator before each message,
  followed by short reading and reply pauses scaled to the selected speed.
- The browser can auto-play, pause, step through, replay, filter sessions, pick
  a random session, and copy the completed transcript.

## Target and Agent boundary

The viewer reads labeled sessions because it must operate the deterministic
customer and score the replay. The Agent itself receives only:

```text
reset(session_id, user_profile)
respond(session_id, user_message, turn, top_k)
```

Ground truth, hidden intent cards, behavior fields, scenario labels, difficulty,
and `sample_id` are never passed into the Agent. The server captures the
target-free trace immediately after `respond`, then separately compares the
returned ASINs with evaluator ground truth. “Target found” badges and outcome
cards are therefore evaluator-side visualization added after the decision.

The default first session is intentionally not hidden even though it is a
turn-one hit. That behavior comes from exact hypothesis narrowing plus the
review prior. For a video that visibly shows three turns of narrowing, select
`public_0120`; useful backup cases are `public_0080` (Intent Override) and
`public_0112` (Boundary).

The viewer is not included in the deterministic `submission.zip`; that archive
contains only the competition runtime under `submission/`.

The server uses Python's standard library and the frontend has no build step or
external runtime dependency.
