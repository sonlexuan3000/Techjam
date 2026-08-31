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

The competition package does not contain images, videos, account credentials, private organizer labels, or the private holdout sessions.

The final InverseCart runtime uses no external review-history or purchase-history
asset. It loads only the organizer-provided catalog and the messages/profile
passed through the competition interface. The catalog bootstrap pins and checks
the organizer archive SHA-256 before use.

Participants must follow the source dataset's applicable terms and use the data only for the competition, research, and other permitted purposes. The competition organizer does not claim ownership of the underlying Amazon review or product content.
