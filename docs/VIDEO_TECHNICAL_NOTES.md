# Internal technical notes for the demo video

This is a production handoff for the teammate recording the public demo. It is
not Devpost body copy. The complete background, glossary, judge Q&A, and source
map are available in [English](TEAM_HANDOFF_EN.md) and
[Vietnamese](TEAM_HANDOFF_VI.md).

## Recording setup

Pre-warm the backend before recording so the one-time catalog indexing delay is
not part of the demo:

```bash
make setup
make frontend
```

Open <http://localhost:8787>. Keep the frontend's default behavior unchanged.
Use the session picker to search for `public_0120`, select it, and use **Step**
mode so narration remains synchronized with the conversation.

The viewer is an evaluator-side visualization. It knows the target in order to
score and highlight the outcome, but the production Agent receives only the
profile, user message, turn, and Top-K. Put this short caption on screen when the
target badge first appears:

> Ground-truth highlighting is evaluator-side only; it is never an Agent input.

The picker endpoint deliberately omits ground truth and hidden intent fields.
The viewer uses the same customer policy, override timing, hit rules, and
ten-turn limit as the released local evaluator.

## Primary session: `public_0120`

This is the recommended recording because it visibly shows the complete
multi-turn narrowing flow requested by the organizer. The genuine turn-one
behavior remains available and unchanged in the default session.

- Scenario: Browsing, difficulty medium.
- Product family: Card Cases & Money Organizers / Wallets.
- Target: `B08GPGX2QG`, SENDEFN women's leather wallet.
- Production outcome: turn 3, rank 1.

Deterministic flow:

1. The customer is browsing for a wallet with no initial detail.
2. The first `other` reply discloses `leather` and `color: red`.
3. The next reply discloses `Leather lining` and `Snap closure`; the target is
   returned at rank 1.

Suggested narration over the session:

> The first message identifies only a broad wallet category. InverseCart keeps
> products whose reconstructed intent cards can explain the dialogue. After the
> first clarification, leather and red eliminate many hypotheses. The second
> reply separates the remaining wallets, and the target reaches rank one on
> turn three.

## Backup sessions

### `public_0080` — Intent Override

- Difficulty hard.
- Target `B0BPRQY4CF`, IZOD men's polo.
- Valid hit at turn 4, rank 1.

Use this case to explain that recommendations before the replacement intent are
not scoreable. The state machine preserves provisional recommendations and
repairs that history when the override arrives.

### `public_0112` — Boundary

- Difficulty medium.
- Target `B086ZNJY8K`, Nautica men's walking sneaker.
- The customer first returns no preference, then reveals `leather` and
  `Leather sole`.
- Hit at turn 3, rank 1.

Use this only if the video needs to show that a no-preference reply does not
break the session.

## Recommended three-minute cut

This timing is an editorial recommendation, **not an additional organizer
rule**. Verify current event-level requirements on the official Devpost page.

| Time | Story | Screen |
|---|---|---|
| 0:00–0:15 | Hook | Title and one-line idea |
| 0:15–0:35 | Why fixed Top 10 is insufficient | Hit Rate/MRR/MTTC trade-off |
| 0:35–1:20 | Live proof | `public_0120` in Step mode |
| 1:20–2:05 | Technical flow | Hypotheses → focus/recovery → DP |
| 2:05–2:40 | Evidence | Public ablation plus honest holdout caption |
| 2:40–3:00 | Practicality and close | Offline, zero tokens, limitation |

### 0:00–0:15 — Hook

Suggested line:

> Normal search asks which product looks similar to the latest query.
> InverseCart asks which product could have generated the entire conversation.

### 0:15–0:35 — Score tension

Explain only the intuition:

- more results improve immediate coverage;
- fewer results protect reciprocal rank;
- another clarification costs a turn;
- the first valid hit ends the session.

Do not spend video time deriving the full metric formula. It can appear briefly
on screen or in the report.

### 0:35–1:20 — Live proof

Play `public_0120` one turn at a time. Point out the newly disclosed values and
changing recommendation. Do not claim the displayed user profile influenced
ranking: production stores it but does not use it in the selected policy.

### 1:20–2:05 — Technical idea

Use the README architecture diagram or an equivalent simplified animation:

```text
Catalog + offline review aggregate
               ↓
       Product intent cards
               ↓
 Message parser + session state
               ↓
 Exact candidates OR focus + recovery
               ↓
 Fixed ordering + finite-horizon DP
               ↓
     Ranked prefix + ask `other`
```

Narration must keep three boundaries clear:

1. Exact grounded protocol evidence may filter eligibility.
2. Uncertain NLP changes ranking focus but preserves recovery eligibility.
3. DP chooses prefix length for a fixed order; it does not choose the question
   type or learn a new ranking permutation.

### 2:05–2:40 — Results and ablation

Show the public-development Technical Score progression:

| Backend | Technical Score |
|---|---:|
| Released weak BM25 | 0.106710 |
| Uniform inverse-DP | 0.963350 |
| Catalog `rating_number` inverse-DP | 0.979900 |
| **Review-prior inverse-DP — shipped** | **0.983200** |

For the final backend on the labeled public 200, also show HR@10 `1.0000`, MRR
`1.000000`, and MTTC `1.8400`.

Add one honest caption rather than hiding the contrary result:

> The final prior was selected on public development. It improves the identical
> uniform core by `0.019850` there, but regresses `0.003854` on the roughly
> uniform generated holdout.

This framing shows that the large gain comes from inverse-card inference and DP;
the popularity prior is a smaller, distribution-dependent belief layer.

### 2:40–3:00 — Practicality and close

Suggested close:

> The submitted Agent is deterministic, runs offline with the Python standard
> library, and uses zero model tokens or external APIs. Its largest remaining
> limitation is value-level semantic paraphrasing; recovery limits false
> elimination but does not claim general language understanding.

## Claim guardrails

- Call the 200-session result **organizer public development**, not private,
  hidden, blind final, or expected private score.
- DP chooses recommendation depth for a fixed ordering. It does not choose the
  question type or ranking permutation.
- The structured question is always `other` in the final backend.
- The 800-session generated holdout has a public seed; never call it private.
- The public 200 was used to select the final prior after external data was
  confirmed permitted.
- The prior contains one aggregate verified-review count per catalog product,
  not review text, user data, session mapping, or unreleased organizer labels.
- Do not say the prior is temporally leakage-free. The disclosed source window
  may overlap periods later treated as held out by the organizer.
- Wrapper stress preserves exact catalog values; do not claim arbitrary
  semantic-paraphrase support.
- The anonymized profile is retained but not used for ranking.
- `TechnicalScore` is an objective input to Technical Execution, not the whole
  hackathon score.
- The newly preserved adaptive-K experiments are not the shipped production
  backend.

## Pre-record checklist

- [ ] `make test` passes the current 75 tests.
- [ ] Server is already warm before screen capture.
- [ ] Browser zoom, window size, and audio levels are fixed.
- [ ] `public_0120` is selected manually; frontend defaults remain unchanged.
- [ ] Step mode is used and each clue is readable.
- [ ] Evaluator-side target caption is present.
- [ ] No claim that profile affects ranking.
- [ ] Results slide says public development.
- [ ] Holdout regression is disclosed.
- [ ] Final video stays inside the current official duration requirement.
- [ ] Repository and video visibility satisfy the official Devpost rules.

## Verified sources

- [`TEAM_HANDOFF_EN.md`](TEAM_HANDOFF_EN.md) — complete English handoff.
- [`TEAM_HANDOFF_VI.md`](TEAM_HANDOFF_VI.md) — complete Vietnamese handoff.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — state, recovery, ranking, and DP.
- [`EVALUATION.md`](EVALUATION.md) — all evaluation numbers and limitations.
- [`final_results.json`](final_results.json) — machine-readable final metrics.
- [`frontend/README.md`](../frontend/README.md) — viewer behavior and commands.
- [`competition_specification.md`](competition_specification.md) — evaluator
  protocol and score semantics.
