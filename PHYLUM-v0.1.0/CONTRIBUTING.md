# Contributing to PHYLUM

PHYLUM is intentionally small at the core. Contributions should preserve three rules:

1. The complete world must remain reconstructable from Git history.
2. Evolution must be reproducible for the same seed, generation, and lineage identifier.
3. Forks must be able to diverge without a central server.

Run the test suite before opening a pull request:

```bash
python -m unittest discover -s tests -v
```

Useful contribution areas include ecology models, visual renderers, fossil analysis, lineage comparison, and merge/collision experiments.
