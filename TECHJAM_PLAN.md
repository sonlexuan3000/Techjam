# Shopping Copilot — TechJam working plan

Snapshot verified on 26 August 2026 against the official participant kit.

## Event rules that matter now

- Eligibility: age 18+, currently residing in Singapore, and enrolled in a Singapore university with expected graduation in December 2026 or later.
- Solo or a team of up to five eligible people. A team must appoint one submission representative.
- Registration requires both the TikTok registration form and joining the Devpost event.
- Build/submission window: 29 August 2026, 12:00pm to 1 September 2026, 12:00pm (GMT+8/Singapore time).
- Finalists: 8 September. In-person Grand Final: 11 September, 9:00am–6:00pm at TikTok Singapore.
- Submit in English, or provide an English translation of every submission material.
- Public code repository plus README, Devpost write-up, and a public three-minute YouTube demo.
- The project must be new, or an existing project must be significantly updated after the submission period starts. Keep pre-event work to setup/boilerplate and make the substantive implementation during the 72-hour window.
- Third-party SDKs, APIs, data and open-source code are allowed only when the team is authorized and complies with their licenses.
- Do not attempt to re-identify anyone. Official rules say all used/processed data should be deleted when the competition ends.

## Goal

Build a headless, multi-turn shopping agent that finds the hidden purchased product as early as possible and ranks its exact `parent_asin` as highly as possible.

```text
TechnicalScore = 0.50 * HitRate@10 + 0.30 * MRR + 0.20 * Efficiency
Efficiency = clip((11 - MTTC) / 10, 0, 1)
```

The strongest optimization order is therefore: get the target into Top 10, move it toward rank 1, then reduce the first-hit turn.

## Hard rules

- At most 10 turns; a miss is assigned turn 11.
- Only exact, catalog-valid `parent_asin` values count.
- The 50,000-product catalog is read-only; no injected or mock ASINs.
- Text and structured metadata only; no multimodal system.
- Retrieval must be local/in-memory; no heavy external vector database.
- No full-parameter training of a foundation model.
- UI is out of scope. The official Python Agent interface is the product surface.
- The final runner may restrict CPU, memory, time, and network access.

## What the organizer provides

- Frozen 50,000-product Amazon Reviews 2023 catalog.
- 200 labeled development sessions and 800 hidden final sessions.
- Weak SQLite FTS5/BM25 starter agent.
- Deterministic evaluator, API contract, metric config, baseline and submission rules.
- No TikTok Shop API, hosted model, API key, credit, GPU, cloud service, or hosted vector DB.

## Verified local setup

- Frozen catalog SHA-256 verified and expanded to `data/catalog.jsonl`.
- Catalog count: 50,000 products.
- Public scenario mix: 80 Buying, 80 Browsing, 30 Intent Override, 10 Boundary.
- Official starter reproduced: HR@10 `0.125`, MRR `0.068034`, MTTC `9.81`, TechnicalScore `0.10671`.
- Official tests: 3/3 passing.

Commands:

```bash
make setup
make test
make unseen-data
make evaluate-unseen-dev
make human-stress
```

These are the shared candidate-development checks. Do not tune or choose a
candidate using `make evaluate`/the organizer public 200; the integration owner
runs that only after the NLP and algorithm winners are frozen.

## Recommended MVP architecture

```text
profile + new message
        |
        v
intent router + session state (slots, exclusions, overrides)
        |
        +-- candidate pool too broad --> ask one high-information attribute
        |
        v
BM25/category route + dense semantic route
        |
        v
rank fusion -> hard-constraint filtering -> lightweight reranking
        |
        v
Top 10 ASINs + next clarification action
```

Implementation order:

1. Add deterministic session state, slot extraction, override/negation handling, and a question policy.
2. Strengthen the sparse route with field-aware retrieval, accumulated-query rewriting, price/category filters, and popularity/rating tie-breakers.
3. Add an offline dense route. Benchmark direct NumPy cosine search before adding FAISS; 50,000 items may not need an approximate index.
4. Fuse routes with reciprocal-rank fusion, then rerank only a small candidate set.
5. Add a model/API only if it beats the deterministic pipeline after accounting for latency, cost, and an offline fallback.

Reasonable tools to benchmark:

- Keep: Python, SQLite FTS5, standard-library evaluator.
- Add first: NumPy and scikit-learn for analysis, sparse features, calibration, and simple local scoring.
- Dense option: Sentence Transformers with a compact retrieval model and precomputed catalog embeddings.
- Optional acceleration: FAISS `IndexFlatIP`; avoid a vector database/server.
- Quality tooling: pytest, ruff, and a small schema/contract test suite.
- Avoid as a core dependency: live-only LLM APIs, LangChain-style orchestration, FastAPI/UI, or a heavyweight local generative model unless a measured gain justifies them.

## Questions to ask at the 28 August workshop

1. Exact CPU, RAM, per-turn/session timeout, Python version, package-install and artifact-size limits.
2. Whether final evaluation has network access and how external credentials would be supplied.
3. Whether an offline model may be bundled or downloaded during setup.
4. Whether “LLM semantic ranking” is mandatory or a strong local semantic scorer satisfies the requirement.
5. Exact submission entry path/packaging command and whether catalog embeddings may be submitted.
6. The general rules mention a Stage-One check for required APIs/SDKs, but this track supplies no required API/SDK. Confirm that a fully local Agent is eligible.
7. The general rules describe four equally weighted Stage-Two criteria, while the track brief gives a different weighted rubric plus final-event presentation. Confirm which rubric selects finalists for this track.
8. The README references a participant release checklist that is absent from the public repository; ask for the intended file.

## Submission checklist

- Public repository with a working `Agent`, declared dependencies, setup and one-command reproduction.
- Devpost description: approach, tools, APIs, libraries, data/assets, cost, latency, limitations and team contributions.
- Public YouTube demo showing one end-to-end multi-turn run or result analysis; no UI is required.
- Never commit secrets, private data, generated mock ASINs, or evaluator/public-label modifications.

## Official sources

- [TikTok TechJam 2026 overview](https://tiktoktechjam2026.devpost.com/)
- [TikTok TechJam 2026 official rules](https://tiktoktechjam2026.devpost.com/rules)
- [Shopping Copilot participant repository](https://github.com/TechJam2026/techjam-conversational-search)
- [Frozen participant-kit release](https://github.com/TechJam2026/techjam-conversational-search/releases/tag/participant-kit)
- [Amazon Reviews 2023 documentation](https://amazon-reviews-2023.github.io/)
