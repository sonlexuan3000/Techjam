# Data Attribution and Use

This competition package is derived from **Amazon Reviews 2023**, published by McAuley Lab at UCSD.

- Project page: https://amazon-reviews-2023.github.io/
- Selected category: `Clothing_Shoes_and_Jewelry`
- Product join key: `parent_asin`
- Competition modality: text and structured product metadata only
- Runtime catalog size: 50,000 products
- Runtime fields used: `parent_asin`, `title`, `features`, `details`,
  `description`, `categories`, `store`, `price`, `average_rating`, and
  `rating_number`
- Offline prior source: the category's Amazon Reviews 2023 raw review file,
  joined to the catalog by `parent_asin`
- Offline prior field: verified-review count in the 365 days before the
  exclusive `2023-10-01` cutoff; runtime weight is count plus one

The competition package does not contain images, videos, account credentials,
private organizer labels, or private holdout sessions.

The final InverseCart runtime bundles
`submission/data/review_prior.tsv`: 50,000 product-level aggregate counts and a
header. It contains no user identifier, review text, timestamp, individual
review row, public-session mapping, or private organizer label. Its SHA-256 is
`45bc7fa2053e55c2bdef7454c2461886a02ef25d0d25339d5d51a5affaafcfd6`.
Of the 50,000 counts, 5,777 are nonzero; Laplace smoothing assigns the remaining
products a positive weight of one.
The catalog bootstrap pins and checks the organizer archive SHA-256 before use;
the prior is loaded locally with no runtime network request.

The aggregate was computed from the full disclosed source file before the
cutoff and may therefore include events from periods the organizer later treats
as held out. Results using it are disclosed separately from uniform and
catalog-only ablations. See
[offline-prior provenance](submission/data/README.md) for the raw source
checksum, row counts, and exact reproduction commands.

Participants must follow the source dataset's applicable terms and use the data only for the competition, research, and other permitted purposes. The competition organizer does not claim ownership of the underlying Amazon review or product content.
