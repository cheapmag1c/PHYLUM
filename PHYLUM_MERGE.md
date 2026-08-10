# PHYLUM branch contact protocol

PHYLUM treats Git forks as independently evolving biospheres. A normal source-code merge is not enough to combine two evolved world states, because choosing `ours` or `theirs` would erase one history.

The biological rule is **contact**:

1. Both repositories must descend from the same PHYLUM root fingerprint.
2. Compare the timelines:

   ```bash
   python -m phylum compare ../OTHER-PHYLUM
   ```

3. Resolve the biological encounter before merging world files:

   ```bash
   python -m phylum contact ../OTHER-PHYLUM
   ```

4. PHYLUM introduces foreign living lineages as founder populations, preserves their source lineage and original species IDs, transfers viable pathogen pools, and records a permanent `contact` event.
5. The next normal generation determines invasive success, competition, predation, disease spillover, hybrid-like divergence, or extinction using the same ecology rules as the rest of the simulation.

PHYLUM refuses contact between worlds with different root fingerprints. That prevents unrelated simulations from being silently fused.

## Why this is not an automatic Git merge driver

Git merge drivers operate file-by-file, while PHYLUM contact requires the complete state of both biospheres at once: species, genomes, pathogens, ranges, branch ancestry, and world metadata. The explicit `contact` command is therefore the canonical merge rule.
