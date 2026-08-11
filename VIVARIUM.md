# PHYLUM 2.0 — VIVARIUM

> **Life is no longer advanced. It happens.**

VIVARIUM replaces PHYLUM's species-level demographic substrate with a continuous-time living-world engine. The previous layers remain part of the simulation, but they now operate around populations that are represented by explicit organisms and bounded cohorts.

## The engine rule

PHYLUM 2.0 does not directly instruct a species to evolve. Organisms and cohorts feed, age, move, reproduce, inherit, mutate, become infected and die. Species-level population, range, genome and diversity values are measured back from those living populations.

A Git commit is an **observation checkpoint**, not a biological generation. By default one checkpoint resolves fourteen simulated days through daily microsteps. PALEON's deep planetary state advances on slower simulated-year boundaries; NERVE/TECHNE/SOCIUS macrostate is sampled seasonally while individual memory and cultural encounters can occur during daily life.

## Living state

`world/organisms.json` contains a bounded high-fidelity sample of actual organisms. Each living organism can carry age, life stage, sex, position, energy, health, inherited genes, phenotype, parents, bounded memories, bounded social familiarity, cultural information and infection state.

`world/cohorts.json` compresses the rest of large populations into local cohorts. Cohorts retain count, location, mean age, energy, health, allele means and pathogen prevalence. This level-of-detail split makes populations much larger than the explicit-agent budget possible without making GitHub Actions unbounded.

`world/ecosystem.json` stores local cell ecology: climate, productivity, producer biomass, detritus, nutrients, water and elevation. Food and environmental state are local rather than a single species-wide carrying-capacity multiplier.

`world/vivarium.json` stores the continuous simulation clock and bounded engine metadata. Pre-2.0 generations are preserved as legacy observations; VIVARIUM simulated day zero begins at migration because the old generation counter never represented a physical duration.

## Selection and heredity

Sexual reproduction recombines parental loci and applies small bounded mutations. Offspring carry parent IDs. Cohort allele means experience weak local selection and drift. The public species genome is a weighted measurement of the living population, not an independently mutated template.

Speciation is classification after sustained isolation and genetic divergence. There is no fixed observation number at which a lineage is told to split.

## Ecology and mortality

Energy is the currency connecting metabolism, movement, cognition and reproduction. Autotrophs use local productivity, moisture and nutrients; grazers consume finite producer biomass; detritivores consume detritus; predators must encounter prey. Death can emerge from age, starvation, predation, disease, weather and environmental mismatch.

Pathogens transmit through local host contact and prevalence. Host immunity and pathogen traits influence transmission and mortality. Population changes therefore have attributable demographic causes instead of being unexplained species-level multipliers.

## Existing layers under VIVARIUM

- **PALEON** — planet, climate, hydrology, geology and deep-time environmental feedback.
- **SOMA** — inherited body plan, physiology, development and life history.
- **NERVE** — perception, memory, learning and individual behavior.
- **TECHNE** — cultural inheritance, material practices and persistent knowledge.
- **SOCIUS** — social groups, relationships, norms and group history.
- **WITNESS + ORRERY** — evidence, history and visualization.

VIVARIUM is the substrate joining them rather than a replacement for their identities.

## Observation surface

`python -m phylum vivarium` reports continuous engine state. `renders/vivarium.svg` and `docs/vivarium.html` expose explicit organisms, bounded cohorts, births, deaths, death causes, local positions and simulated time. The existing ORRERY remains the planetary overview.

## Bounds and determinism

The engine caps explicit agents, cohort count, individual memory, social links and retained dead-agent samples. Stable seeded random streams determine biology. Real observation timestamps may differ between runs, but biological state is driven by the repository lineage, observation index and inherited world state rather than wall-clock time.

## Migration

The 2.0 migration does not consume a checkpoint and does not rewrite old fossil history. Existing aggregate population is converted exactly into explicit founders plus cohorts. The MOURNINGSTAR Source License remains unchanged.
