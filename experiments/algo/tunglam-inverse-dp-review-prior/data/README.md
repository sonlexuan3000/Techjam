# Offline Review Prior

`review_prior.tsv` contains one non-sensitive aggregate per frozen catalog
product: the count of verified Amazon Reviews 2023 review records in the
365-day window ending at the exclusive cutoff `2023-10-01`.

## Provenance

- Source dataset: McAuley Lab Amazon Reviews 2023
- Category: `Clothing_Shoes_and_Jewelry`
- Source file size: `27,810,080,533` bytes (uncompressed JSONL)
- Source SHA-256: `150eb2a9e88f61cd5a89c5337cde437dc71308c47f22899a72d9e1dad60b7356`
- Raw rows scanned: `66,033,346`
- Reviews joined to the 50,000-product catalog: `1,623,039`
- Products with at least one raw review: `49,992`
- Malformed source rows: `0`
- Runtime TSV SHA-256: `45bc7fa2053e55c2bdef7454c2461886a02ef25d0d25339d5d51a5affaafcfd6`

No user IDs, timestamps, review text, images, or individual review records are
stored in the asset. The runtime agent applies Laplace smoothing of `+1` before
normalizing weights inside each candidate set.

## Reproduction

```bash
clang -O3 -std=c11 \
  experiments/algo/tunglam-inverse-dp-review-prior/tools/review_prior/review_range_aggregate.c \
  -o /tmp/review_range_aggregate
python3 experiments/algo/tunglam-inverse-dp-review-prior/tools/review_prior/aggregate_review_features_ranges.py \
  --chunks 128 \
  --workers 8 \
  --scanner-binary /tmp/review_range_aggregate \
  --catalog data/catalog.jsonl \
  --output /tmp/review_features.jsonl
python3 experiments/algo/tunglam-inverse-dp-review-prior/tools/review_prior/export_review_prior.py \
  --input /tmp/review_features.jsonl \
  --output /tmp/review_prior.tsv
shasum -a 256 /tmp/review_prior.tsv
```

The extraction downloads and scans the 27.8 GB source. The compact committed
TSV is the only review-derived runtime asset; individual review records and the
large intermediate are not committed.
