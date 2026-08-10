# PHYLUM 1.2 — SOMA

> **Species evolved. Now organisms live.**

SOMA is PHYLUM's organism-level biology layer. DEEP TIME still governs the planet, ecology, genetics, disease, speciation and extinction. WITNESS still records what changed. SOMA adds an intermediate biological layer between genome and population so lineages have bodies, development, life histories and demographic structure rather than existing only as a population count.

## What SOMA models

SOMA is deliberately **population-aggregate**, not an agent simulation of every organism. A lineage can contain thousands of organisms without creating thousands of Python objects.

Each lineage gains:

- **Life stages:** propagules, juveniles, reproductive adults and elders.
- **Aging and lifespan:** maturity age, lifespan and stage-specific mortality structure.
- **Reproductive biology:** sexual / mixed / clonal modes, fertilization strategy, mating systems, breeding seasonality, offspring strategy and parental care.
- **Sexual selection:** dimorphism and courtship intensity derived from the lineage's inherited biology.
- **Development:** direct development, metamorphic development, spore cycles and alternating developmental strategies.
- **Inherited body plans:** symmetry, segmentation, support system, appendages, covering, locomotion, feeding structures, defenses and sensory modalities.
- **Morphological continuity:** descendants inherit the architecture of their parent and only diverge gradually.
- **Physiology:** metabolism, respiration, thermoregulation, energy allocation, plasticity and dormancy.
- **Microbiome traits:** digestion, resilience and host dependence.
- **Behavior:** activity cycle, social organization, communication, territoriality and migration tendency.
- **Within-lineage variation:** distributions for body size, speed, fecundity, defense and sensory ability.
- **Life-history tradeoffs:** parental investment, fecundity, metabolism and adult availability modify births, deaths and carrying capacity.
- **Directional natural selection:** persistent predation, competition, disease, climate and sexual-selection pressure weakly bias descendant genomes, allowing arms races to accumulate across speciation rather than existing only as labels.
- **Predator/prey coevolution:** prey pressure favors escape, sensory and defensive traits; predator pressure can favor attack and aggression in predatory lineages.
- **Symbiosis:** overlapping compatible lineages can form mutualistic or commensal relationships; mutualisms can modestly change energy use, carrying capacity and disease resilience while contact persists.
- **Organismal innovations:** descendants can fossilize major body-plan, developmental, locomotor or physiological changes.
- **Generated organism plates:** schematic SVG reconstructions generated from inherited state, with no image model involved.
- **SOMA Field Guide:** `renders/soma.svg` plus `docs/soma.html` and per-lineage organism SVGs.

## How SOMA affects the existing simulation

SOMA does not replace DEEP TIME's population model. Instead it produces bounded modifiers that DEEP TIME consumes:

- reproductive adult share + breeding season → birth modifier
- parental care → fewer births but lower ordinary mortality
- metabolic cost → carrying-capacity and energy-efficiency modifiers
- group structure / armor / refuges → predation mortality modifier
- microbiome resilience → disease mortality modifier
- thermoregulation → survival / energetic tradeoffs
- plasticity + dormancy → bounded survival/reproduction changes under seasonal or resource stress
- accumulated selection pressure → weak directional bias in descendant genomes

The DEEP TIME population remains authoritative. SOMA's cohorts are reconciled back to that population after each generation, which prevents the two layers from drifting apart.

## Important design rule

SOMA does **not** script evolutionary milestones.

There is no generation at which flight, endothermy, parental care, metamorphosis or complex sensory systems are forced to appear. Those features are derived from inherited traits and only become different when a lineage actually diverges.

## New generated files

```text
renders/
├── soma.svg
└── organisms/
    ├── sp-00001.svg
    ├── sp-00002.svg
    └── ...

docs/
├── soma.html
├── soma.svg
└── soma-data.json
```

## New CLI

```bash
python -m phylum soma
```

Prints a compact organism-level summary of every living lineage.

## Compatibility

SOMA migrates the current PHYLUM world **without advancing a generation**. Existing lineages receive deterministic ancestral organismal states based on their already-canonical genomes and morphology. No species, population, fossil, range or Git history is reset.

The installer requires the DEEP TIME / WITNESS architecture currently used by PHYLUM and refuses to patch incompatible source rather than guessing.

## License

PHYLUM and SOMA are distributed under the **MOURNINGSTAR Source License v1.0**. Copyright (c) 2026 MOURNINGSTAR. All rights reserved. See `LICENSE` in the PHYLUM repository for complete terms.
