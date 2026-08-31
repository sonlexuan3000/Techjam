# Development provenance

The current runtime tree and deterministic `submission/` archive use only
organizer-supplied catalog fields. They contain no external review-history or
purchase-history asset.

An earlier development experiment evaluated a derived review prior. Review
found that its redistribution terms were unclear and that its measured gain over
the uniform catalog-only prior was too small to justify the data risk. The asset,
extractor, and runtime support were removed before production integration.

The selected entrypoint uses a uniform inverse-DP belief. The only popularity
signal that remains is the organizer catalog's `rating_number`, used as a late
tie-break inside uncertain NLP recovery and retained as a controlled ablation.

The source-only release artifact is built with:

```bash
make submission-archive
```

That command excludes Git history, catalogs, generated datasets, evaluation
outputs, bytecode, and virtual environments. The removed prior is not part of
the submitted system.
