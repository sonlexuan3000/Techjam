# Offline review-count prior

`review_prior.tsv` contains one aggregate number for each of the 50,000
catalog products: the count of verified Amazon Reviews 2023 review records in
the 365-day window ending at the exclusive `2023-10-01` cutoff.

The runtime converts each count `r` into the smoothed belief weight `r + 1`.
The extra one keeps products with no observed review possible. The file stores
no user identifier, review text, timestamp, image, or individual review row.

## Provenance

- Source: McAuley Lab Amazon Reviews 2023
- Category: `Clothing_Shoes_and_Jewelry`
- Source file size: `27,810,080,533` bytes
- Source SHA-256:
  `150eb2a9e88f61cd5a89c5337cde437dc71308c47f22899a72d9e1dad60b7356`
- Raw rows scanned: `66,033,346`
- Reviews joined to the frozen 50,000-product catalog: `1,623,039`
- Products with at least one review anywhere in the full raw file: `49,992`
- Products with a nonzero verified count inside the final 365-day window:
  `5,777`
- Malformed source rows: `0`
- Runtime TSV SHA-256:
  `45bc7fa2053e55c2bdef7454c2461886a02ef25d0d25339d5d51a5affaafcfd6`

This popularity signal is an offline prior, not a private-session label or a
target lookup. The aggregate was computed from the full source review file up
to the stated cutoff, so results that use it are disclosed separately from the
uniform and organizer-catalog-only ablations.

Because the full source is aggregated before one fixed cutoff, it may contain
events from periods the organizer later treats as held out. The asset therefore
supports a predictive popularity assumption, not a causal or temporally
leakage-free claim. After external data was confirmed permitted, the final prior
was selected on the organizer-labeled public development set. It uses no
unreleased final-evaluation session or label.

## Reproduction

The extraction scripts are retained in `scripts/review_prior/`. Reproducing
the asset downloads and scans the 27.8 GB source file:

```bash
clang -O3 -std=c11 \
  scripts/review_prior/review_range_aggregate.c \
  -o /tmp/review_range_aggregate

python3 scripts/review_prior/aggregate_review_features_ranges.py \
  --chunks 128 \
  --workers 8 \
  --scanner-binary /tmp/review_range_aggregate \
  --catalog data/catalog.jsonl \
  --output /tmp/review_features.jsonl

python3 scripts/review_prior/export_review_prior.py \
  --input /tmp/review_features.jsonl \
  --output /tmp/review_prior.tsv

shasum -a 256 /tmp/review_prior.tsv
```

The source dataset's applicable terms and the attribution in
`DATA_ATTRIBUTION.md` apply.

From the full repository, verify the committed asset's checksum, schema, and
exact catalog-ASIN coverage with:

```bash
python3 scripts/verify_review_prior.py \
  --catalog data/catalog.jsonl \
  --prior submission/data/review_prior.tsv
```
