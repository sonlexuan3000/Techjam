# Final submission checklist

Use this list once, in order, before the Devpost deadline. Items marked
**manual** cannot be completed by repository code.

Current official deadline: **September 1, 2026 at 12:00 PM SGT**. Recheck the
[official Devpost rules](https://tiktoktechjam2026.devpost.com/rules) immediately
before submission in case the organizer posts an amendment.

## 1. Freeze the repository

- [ ] Confirm `submission/agent.py` is the intended competition entrypoint.
- [ ] Run `git status` and review every tracked change.
- [ ] Run the release commands below and keep their output.
- [ ] Commit the final state and record the full commit SHA.
- [ ] **Manual:** make the GitHub repository public and verify the clone command
  works in a signed-out browser.
- [ ] **Manual:** do not change Agent code, prompts, indexes, prior, or model
  configuration after the organizer releases the final package.

## 2. Release commands

```bash
make setup
make test
make integration-check
python3 submission/smoke.py --catalog data/catalog.jsonl
make submission-archive
shasum -a 256 dist/shopping-copilot-submission.zip
```

Expected release test count: **75** total — 54 shared
state/parser/contract/frontend tests and 21 selected inverse-DP core tests.
The public-development evaluator should report HR@10 `1.0000`, MRR `1.000000`,
MTTC `1.8400`, and Technical Score `0.983200`.

## 3. Inspect the package

- [ ] Extract the ZIP into a clean temporary directory and run its documented
  smoke command against the organizer catalog.
- [ ] Confirm the ZIP contains `submission/agent.py`, `README.md`, `REPORT.md`,
  `requirements.txt`, source modules, and `data/review_prior.tsv`.
- [ ] Confirm it excludes catalogs, public/generated sessions, evaluator output,
  raw reviews, credentials, `.venv`, bytecode, and the optional frontend.
- [ ] Record the final ZIP SHA-256 next to the submitted commit SHA.

## 4. Devpost and team fields

- [ ] **Manual:** enter the project title **InverseCart**.
- [ ] **Manual:** paste and final-edit `docs/DEVPOST_SUBMISSION.md`.
- [ ] **Manual:** add the public GitHub URL.
- [ ] **Manual:** add the public YouTube demo URL in the form and project
  description.
- [ ] **Manual:** confirm all required collaborator/invite/eligibility fields on
  Devpost.
- [ ] Confirm every non-English repository/submission document has an English
  counterpart; `TEAM_HANDOFF_VI.md` is paired with `TEAM_HANDOFF_EN.md`.

## 5. Video and presentation

- [ ] Show at least one complete multi-turn session. `public_0120` is the
  recommended main recording; `public_0080` and `public_0112` are backups.
- [ ] It is also fine to show the genuine turn-one hit `public_0001`; explain that
  exact hypothesis narrowing plus the review prior produced it.
- [ ] Keep the “Leakage-safe evaluation view” banner visible long enough to read.
- [ ] State that target highlighting is an evaluator overlay added after
  `Agent.respond`.
- [ ] State that DP chooses recommendation depth for a fixed ranking and that the
  final Agent always asks structured `other`.
- [ ] Call all 200/2,000/800 reported results development fixtures, not final or
  private scores.
- [ ] Disclose the public-set prior selection and generated-holdout regression.

## 6. Final evaluator after deadline

- [ ] Use the frozen submitted commit and unmodified official evaluator.
- [ ] Save the final `results.json`.
- [ ] Save the commit SHA, Python version, hardware/environment details, command,
  runtime, and relevant logs with that result.
- [ ] Do not retune the Agent after inspecting the released final sessions.

The authoritative policy snapshot is
[`final_evaluation_faq.md`](final_evaluation_faq.md).
