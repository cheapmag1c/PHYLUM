# PHYLUM changelog

## 1.1.1 — README SYNC

Documentation-only synchronization for WITNESS. No biological generation is consumed and no simulation rules change.

- README generator now identifies the active model as WITNESS instead of reverting to DEEP TIME
- Anatomy tree now reflects the current DEEP TIME + WITNESS repository structure
- Observatory documentation now lists WITNESS layers and the CHANGES view
- README regeneration remains automatic on every future generation

## 1.1.0 — WITNESS

A generation-observation layer that makes ecological change visible without altering the underlying DEEP TIME rules.

- persistent `world/changes.json` delta report generated every generation
- before/after population, range, lineage, pathogen, genetics and environment tracking
- per-lineage population/range/movement/infection deltas
- new/ended predator-prey and competition link tracking
- current-generation atlas event markers for migration, speciation, extinction, disease, disasters, contact and mass extinction
- migration trails now distinguish the newest movement from older routes
- predator/prey contact-zone rendering
- disease overlays cover infected ranges and display prevalence
- World Atlas sidebar now includes a Generation Delta panel and "most changed" lineage
- Observatory adds CONTACT ZONES and EVENTS atlas layers
- Observatory adds a CHANGES tab with generation metrics and lineage deltas
- README state block includes the latest population/range delta
- new `python -m phylum changes` CLI report
- GitHub Action prints the generation delta after every run
- test suite expanded to 19 invariant/observation tests

## 1.0.0 — DEEP TIME

A single integrated expansion of the original autonomous biosphere.

- population genetics, recombination, sexual reproduction, diversity and inbreeding
- inherited morphology and behavior
- ecological niches and dynamic trophic roles
- predator/prey food webs, competition, carrying capacity and detritus
- evolving pathogens, spillover, immunity and pandemics
- procedural continents, ocean depth, biomes, elevation, rivers and tectonic plates
- continental drift on a geology clock independent of ecology
- droughts, floods, fire, volcanism, cooling events and resource blooms
- rare unscripted mass extinctions and post-collapse adaptive-radiation pressure
- migration, founder populations and isolation-driven speciation
- extinction causes, fossil species files, event chronology and major-event snapshots
- generated phylogenetic tree and food-web renders
- full World Atlas render with ecology, disease, fossils, tectonics and analytical layers
- generated static Observatory with atlas toggles, fossil browser, lineage browser, timeline and deep-time snapshots
- fork identity, branch comparison and biological branch-contact/merge semantics
- schema migration from the original Generation 0–5 world without resetting history
- expanded validation and test suite
