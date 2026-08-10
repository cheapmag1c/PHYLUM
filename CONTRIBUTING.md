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

## Contribution licensing

PHYLUM is distributed under the **MOURNINGSTAR Source License v1.0**, not MIT.
Submitting a contribution to the official repository grants MOURNINGSTAR the
contribution rights described in Section 4 of [`LICENSE`](LICENSE). Forks and
contributions do not waive MOURNINGSTAR's ownership or the license restrictions.
