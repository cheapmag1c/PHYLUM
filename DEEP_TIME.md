# PHYLUM 1.0 — DEEP TIME

DEEP TIME turns PHYLUM from a small territory simulation into a persistent planetary ecology while preserving the original Git fossil record.

## Living systems

- Population genetics: genome traits, heterozygosity, genetic diversity, founder effects and inbreeding.
- Reproduction: sexual/mixed reproduction, mate availability, recombination and heritable mutation.
- Speciation: migration, geographic isolation, divergence, adaptive radiation and rare compatible hybridization.
- Ecology: carrying capacity, niches, competition, trophic roles, predator/prey links and food-web pressure.
- Disease: evolving pathogens, transmission, host range, spillover, immunity, resistance and pandemic events.
- Morphology and behavior: body plan and behavioral profiles are derived from inherited traits and remain related across descendants.
- Ecosystem engineering: sufficiently capable lineages can alter local moisture/resources and therefore modify future selection pressure.
- Extinction: causes are recorded rather than treating every collapse as an anonymous event.

## Planetary systems

PHYLUM now maintains generated elevation, ocean depth, coastlines, biomes, climate fields and tectonic plates. Ecology, climate and geology use different clocks so plate drift is much slower than population change.

Environmental events include drought, flood, fire, volcanism, cooling and resource blooms. Rare mass-extinction triggers arise from current conditions and stochastic pressure; none are tied to a predetermined generation number.

## World Atlas

`renders/current.svg` is a generated 1600×1040 observation plate. The Observatory version exposes toggleable layers for:

- biomes
- tectonics
- relief/contours
- river-like drainage
- living territories and population cores
- migration
- ecological/predator-prey links
- disease outbreaks
- fossil ranges
- environmental scars
- population density
- biodiversity
- genetic diversity
- climate

The atlas is regenerated from simulation state. It is not a static background image.

## Deep-time record

PHYLUM writes append-only event/history records and periodic atlas snapshots. Major events can create historical snapshots. Extinct species receive fossil records containing ancestry, traits and final-state information.

Generated views include:

- `renders/phylogeny.svg`
- `renders/foodweb.svg`
- `docs/index.html` — static Observatory
- `docs/data.json`
- `docs/atlas-history.js`

The Observatory contains the current atlas, lineage browser, fossil browser, event timeline, deep-time scrubber and branch/contact information.

## Forks, comparison and contact

Forks retain a root fingerprint and lineage identity. Compare two local checkouts with:

```bash
python -m phylum compare ../OTHER-PHYLUM
```

When two independently evolved descendants of the same root are intentionally combined, PHYLUM uses a biological **contact** event rather than silently choosing one world state:

```bash
python -m phylum contact ../OTHER-PHYLUM
```

Foreign lineages arrive as founder populations, viable pathogen pools may transfer, and future generations resolve invasion, competition, predation, spillover and extinction under normal ecology. See `PHYLUM_MERGE.md`.

## Design rule

PHYLUM does not schedule milestones such as “predators appear at generation 100” or “mass extinction at generation 1000.” The engine creates conditions that make outcomes possible, then preserves whatever history actually emerges.
