## 2.1.0 — CORTEX

CORTEX introduces bounded evolving neural controllers inside the VIVARIUM individual-life engine. Resolved organisms now make neural/reflex-blended decisions about rest, foraging, exploration, avoidance, social contact and mating. Innate neural weights and architecture are heritable and mutable; lifetime reward-modulated plasticity is deliberately non-heritable. Cohorts retain compressed neural phenotypes, neural computation carries an energy cost, and ORRERY / LIFE exposes current controller statistics and organism actions. An optional manual local-LLM probe is included, but canonical evolution never calls an LLM and remains deterministic/offline-capable.

## 2.0.1 — CONVERGENCE

- Unified PHYLUM's presentation around a single ORRERY Observatory shell.
- Reframed VIVARIUM as the living-world engine beneath ORRERY instead of a second dashboard.
- Added canonical ORRERY / LIFE outputs for explicit organisms, cohorts, births/deaths, and continuous time.
- Rebuilt Observatory navigation around WORLD, LIFE, PHYLOGENY, BODY, BEHAVIOR, CULTURE, SOCIETY, and PLANET.
- Added VIVARIUM simulated-time status to ORRERY.
- Removed the duplicate VIVARIUM hero from the generated README.
- Preserved historical `vivarium.*` URLs/files as compatibility aliases or redirects.
- No simulation state, fossil history, or licensing terms are changed by this patch.

## 2.0.0 — VIVARIUM

**Life is no longer advanced. It happens.**

- Replaces species-level population advancement with a continuous-time living-world substrate.
- Adds explicit organisms with age, life stage, energy, health, position, parents, inherited genes, phenotype, memory, social familiarity, culture and infections.
- Adds bounded local cohorts for scalable level-of-detail simulation and automatic cohort-to-agent re-resolution without changing population.
- Adds local ecosystem biomass, detritus, nutrients, productivity, organism-driven habitat engineering and deterministic seasons/weather resolved through daily microsteps.
- Adds individual/cohort births, mortality, feeding, movement, predation, pathogen transmission, recombination, mutation and local selection.
- Makes species population, range, genome and diversity measured outputs of the living population rather than independently advanced values.
- Reclassifies Git commits as observation checkpoints and starts VIVARIUM continuous time at day zero without inventing durations for pre-2.0 generations.
- Ticks PALEON on simulated-year boundaries and NERVE/TECHNE/SOCIUS macrostate seasonally instead of once per Git commit.
- Adds condition-based isolation/speciation classification and VIVARIUM-aware branch-contact founders.
- Adds `python -m phylum vivarium`, `renders/vivarium.svg`, `docs/vivarium.html` and persistent living-world state files.
- Preserves PALEON, SOMA, NERVE, TECHNE, SOCIUS, WITNESS, ORRERY and the MOURNINGSTAR Source License.

## 1.6.0 — SOCIUS + ORRERY

**Knowledge endured. Now relationships can outlive the individual.**

- Adds persistent social groups distinct from species and cultural practices.
- Adds social territories, group ancestry, fission, collapse, norms, coordination styles and group-to-group relationships.
- Allows biological survival alongside social-lineage extinction.
- Adds deliberately weak social demographic feedback so ecology, disease and climate remain dominant forces.
- Adds ORRERY, a major graphical overhaul of the world atlas, phylogeny and static Observatory.
- Adds relief/biome cartography, fossil ghost ranges, social territories, relationship arcs, TECHNE site markers, disease and event layers.
- Rebuilds GitHub Pages with layer controls and dedicated SOCIUS navigation.
- Adds `python -m phylum socius`, SOCIUS tests and WITNESS social-event glyphs.
- Fixes duplicate PALEON finalization in patched stacks where it remained from the 1.3.1 migration chain.
- Preserves the MOURNINGSTAR Source License and does not add governments, wars, settlements or scripted civilization milestones.

## 1.5.0 — TECHNE

**Life learned. Now knowledge can outlive the organism.**

- Adds cultural inheritance as population-level state distinct from genes.
- Adds persistent practices, cultural lineage ancestry, dialect drift and cross-species cultural exchange.
- Adds aggregate archaeological sites that can remain as ruins after their creators disappear.
- Adds opportunity-gated nesting, caching, route marking, object use, construction, resource tending and rarer advanced material practices.
- Adds explicit knowledge loss after weak transmission, population bottlenecks and disease pressure.
- Adds very weak gene-culture coevolution without turning culture into a forced biological progression.
- Adds TECHNE cultural record render, static browser and CLI command.
- WITNESS recognizes construction, artifact, cultural-exchange, knowledge-loss and language events.
- Preserves the MOURNINGSTAR license and never schedules civilization or technology milestones.

## 1.4.0 — NERVE

**Organisms lived. Now they learn.**

- Adds persistent NERVE cognition state to every lineage: nervous architecture, perception, memory, learning, temperament and social cognition.
- Adds learned behavioral repertoires, spatial/resource/threat memories and bounded memory decay.
- Adds persistent cultural traditions and social transmission without treating culture as genetic inheritance.
- Adds communication complexity, cooperation, recognition, reciprocity and rare teaching behavior.
- Adds costly cognition and demographic feedback into DEEP TIME/SOMA ecology.
- Adds weak cognition-related natural selection without scripted intelligence milestones.
- Adds a rare, anatomy-gated path to object-assisted foraging/tool use.
- Adds NERVE ethogram render, static browser and CLI status command.
- WITNESS recognizes behavioral, cultural, learning, communication and tool-use events.
- Hardens GitHub Actions against queued scheduled/manual runs starting from stale event SHAs.

## 1.3.1 — PALEON / DEEP TIME 2.0

- Coupled atmosphere, ocean, cryosphere, hydrology, soil, nutrient and carbon-cycle state.
- Dynamic tectonic boundary mechanics, sea level, ecological succession and climate extremes.
- SOMA-aware life → planet feedback and planet → ecology feedback.
- Generated PALEON planetary systems plate and dossier.
- No generation is consumed during migration.

## 1.2.0 — SOMA

- Adds population-aggregate life stages, aging, maturity and lifespan.
- Adds mating systems, sexual selection, reproductive strategies and parental care.
- Adds inherited body plans, development, metamorphosis, locomotion, feeding structures, defenses and sensory systems.
- Adds metabolism, thermoregulation, respiration, dormancy, energy allocation and microbiome traits.
- Adds social organization, communication, territoriality and phenotypic variation.
- Couples SOMA life history back into DEEP TIME births, mortality, carrying capacity, predation and disease.
- Adds persistent selection-pressure tracking and emergent symbiosis.
- Adds deterministic organism illustrations, `renders/soma.svg`, per-lineage organism plates and `docs/soma.html`.
- Migration preserves the current generation and all prior fossil / Git history.

## Licensing — MOURNINGSTAR Source License v1.0

- Replaced the MIT License.
- Copyright notice is now held under MOURNINGSTAR.
- Source remains publicly viewable and usable for permitted non-commercial purposes.
- Commercial use, sale, sublicensing, repackaging, and unauthorized redistribution are prohibited.
- GitHub-native forks remain permitted for non-commercial PHYLUM experimentation and contribution.

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
