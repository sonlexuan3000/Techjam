# Competition data

## Bootstrap the catalog

From the repository root:

```bash
make setup
```

The bootstrap script downloads the frozen organizer archive from the
[participant-kit release](https://github.com/TechJam2026/techjam-conversational-search/releases/tag/participant-kit),
verifies SHA-256
`07fd142631fd6b03e2b4d09988c3eb7d53720e9d57010c79db48eeaada50a8f8`,
decompresses `catalog.jsonl`, and validates exactly 50,000 rows.
The same setup target also verifies the bundled review prior's checksum and
exact catalog-ASIN coverage; its provenance is documented in
[`submission/data/README.md`](../submission/data/README.md).

The catalog and compressed archive are ignored by Git. Do not add them to the
offline-runtime submission ZIP.

## `public_set.jsonl`

The released public development set contains 200 labeled sessions: 80 Buying,
80 Browsing, 30 Intent Override, and 10 Boundary.

Each session contains a safe aggregate `user_profile` and public labels for
local development. Direct user identifiers, timestamps, free-text reviews, raw
purchase history, private intent cards, and private simulator state are not
included.

## Generated evaluation data

`data/unseen_eval/` stores ignored, deterministically reproducible development
and regression outputs. They are generated from official catalog products with
zero public-target overlap, but their seed and construction are visible. They
must not be described as organizer-private or hidden evaluation data.

Never place API keys, private evaluation data, participant secrets, or model
credentials in this directory.
