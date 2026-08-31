# Development provenance

The shipped runtime combines the organizer-supplied catalog with one disclosed
offline aggregate: `verified_reviews_365d` for each of the same 50,000
`parent_asin` values. The final belief weight is count plus one.

The aggregate was derived from McAuley Lab Amazon Reviews 2023,
`Clothing_Shoes_and_Jewelry`. Extraction scanned the full source file, joined
records by `parent_asin`, retained verified records in the 365 days ending at
the exclusive `2023-10-01` cutoff, and exported only the per-product count. The
runtime TSV has 50,000 data rows and SHA-256
`45bc7fa2053e55c2bdef7454c2461886a02ef25d0d25339d5d51a5affaafcfd6`.

The bundled asset contains no user identifier, review text, timestamp, image,
individual review row, public-session mapping, or private organizer label. It
is loaded locally at Agent startup; runtime makes no network request.

The extraction uses the full disclosed source file before the stated cutoff.
Consequently, the aggregate may include events from periods the organizer later
treats as held out. That limitation is explicit: this is a predictive
popularity prior, not a causal estimate or a claim of temporal leakage-free
evaluation.

The inverse-DP algorithm was selected on generated development. After the team
confirmed with judges that external data was permitted, the final review prior
was selected on the organizer-labeled public development set. Its public gain
and generated-holdout regression are both reported in `EVALUATION.md`; no
organizer-private session or label was available or used.

The minimal offline-runtime artifact is built with:

```bash
make submission-archive
```

The archive includes the compact `submission/data/review_prior.tsv` required by
the offline Agent and excludes Git history, catalogs, generated datasets,
evaluation outputs, raw review records, bytecode, and virtual environments.
Extraction code and checksums remain in the repository for auditability.
