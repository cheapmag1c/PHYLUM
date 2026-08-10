# PHYLUM 1.1 — WITNESS

WITNESS does **not** change the ecological probabilities or force new biological events. It changes what PHYLUM remembers and what the observer can see.

Every generation now captures the untouched parent state, advances DEEP TIME normally, and writes a structured `world/changes.json` report describing the delta between the two generations.

## Atlas additions

- current-generation event markers
- bright current migration routes with older routes faded behind them
- predator/prey contact zones
- infected-range disease overlays with prevalence rings
- generation-delta metrics in the atlas sidebar
- most-changed-lineage readout

## Observatory additions

The static Observatory gets new **CONTACT ZONES** and **EVENTS** atlas toggles plus a dedicated **CHANGES** tab showing population, occupied-range, lineage, pathogen and interaction deltas.

## CLI

```bash
python -m phylum changes
```

prints a compact report for the most recently evolved generation.

## Design rule

WITNESS observes. It does not manufacture history. Predator emergence, pathogens, speciation, extinction and catastrophe remain consequences of the existing DEEP TIME simulation.
