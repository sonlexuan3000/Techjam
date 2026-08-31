# Release safety

The current runtime tree and `submission/` archive use only organizer-supplied
catalog fields and contain no external review-history asset. However, an older
reachable development commit (`044c2fa`) included `data/review_prior.tsv`, whose
redistribution permission was not established during review.

Therefore, do not use the existing Git history as the final required public
submission repository unless the asset's redistribution permission is confirmed
or the repository owner explicitly approves and completes a history purge.
The non-destructive safe release path is:

1. run `make submission-archive`;
2. inspect the source-only archive and its printed SHA-256;
3. initialize a fresh public repository from the reviewed current source tree or
   from the archive, without copying `.git`, generated datasets, or catalogs;
4. run the smoke test and unit suite in that fresh repository before linking it
   on Devpost.

Rewriting or force-pushing the existing shared repository is destructive and
must not be done without explicit repository-owner approval and team
coordination.
