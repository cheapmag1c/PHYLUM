# PHYLUM

**An evolutionary simulation written into Git history.**

PHYLUM is a small artificial biosphere that advances itself inside a Git repository. Every generation mutates the persistent world state, redraws the habitat, records important events, and becomes a commit.

Git is not just where PHYLUM's source code lives. **Git is its fossil record.**

![Current PHYLUM world](renders/current.svg?gen=000016)

<!-- PHYLUM:STATE:START -->
**Generation:** `16`  
**Era:** `Origin Era`  
**Living lineages:** `3`  
**Extinct lineages:** `0`  
**Population:** `976`  
**Occupied cells:** `38` / `1440`  
**Active pathogens:** `1`  
**Predator/prey links:** `0`  
**Dominant lineage:** `pale filament`  
**Last generation Δ:** `-15` organisms · `+0` occupied cells  
**Latest fossil:** The biosphere advances through generation 16.
<!-- PHYLUM:STATE:END -->


## Living phylogeny

![PHYLUM phylogeny](renders/phylogeny.svg?gen=000016)

## Living food web

![PHYLUM food web](renders/foodweb.svg?gen=000016)

## Living minds — NERVE

![PHYLUM NERVE ethogram](renders/nerve.svg?gen=000016)

## Planetary system — PALEON

![PHYLUM PALEON planetary system](renders/paleon.svg?gen=000016)

## Living organisms — SOMA

![PHYLUM SOMA field guide](renders/soma.svg?gen=000016)

## The idea

A scheduled GitHub Action wakes up every six hours and runs one generation of the simulation. Organisms move toward suitable habitats, populations rise and collapse, the climate drifts, lineages split, and extinction events accumulate.

Each run changes files such as:

```text
world/current.json
world/species.json
world/environment.json
renders/current.svg
fossils/events.ndjson
```

The Action then commits those changes. A repository's commit history therefore becomes the chronological history of its biosphere.

```text
gen 000041 — pale filament diverges from glass mote
gen 000104 — A prolonged dry phase begins
gen 000139 — rust bell becomes extinct
gen 000207 — silt frond is the most abundant lineage
```

Check out an old commit and you have literally checked out an extinct version of the world.

## Forks are alternate evolutionary timelines

PHYLUM salts its random stream with the GitHub repository identity. When another person forks the project, that fork inherits the same ancestry but begins producing different evolutionary outcomes on its next generation.

Two forks from the same generation can therefore become two different biospheres.

## Run it locally

PHYLUM has no third-party Python dependencies.

```bash
python -m phylum status
python -m phylum evolve
python -m phylum evolve --steps 100 --lineage local/experiment-a
```

Run the tests:

```bash
python -m unittest discover -s tests -v
```

## Turn on autonomous evolution on GitHub

1. Create a new repository and push this project to its default branch.
2. In **Settings → Actions → General → Workflow permissions**, allow GitHub Actions to have read and write permissions if your repository policy does not already allow it.
3. Open the **Actions** tab and enable workflows if GitHub asks you to.
4. Run **Evolve PHYLUM** manually once with `workflow_dispatch` to verify that the bot can create a generation commit.
5. Leave it alone. The included schedule attempts one generation every six hours.

Scheduled Actions are not guaranteed to execute at the exact scheduled minute, so PHYLUM treats a run as a generation rather than using wall-clock time as biological time.

## Anatomy

```text
PHYLUM/
├── .github/workflows/evolve.yml   # autonomous evolution
├── docs/                           # generated Observatory / GitHub Pages
├── fossils/
│   ├── events.ndjson               # append-only event chronology
│   ├── history.ndjson              # generation summaries
│   ├── atlas-history.ndjson        # deep-time atlas snapshots
│   ├── species/                    # extinct-lineage records
│   └── checkpoints/                # periodic recovery state
├── phylum/
│   ├── biology.py                  # genetics, reproduction, ecology, speciation
│   ├── branching.py                # fork identity, comparison and contact
│   ├── disease.py                  # pathogens and immunity
│   ├── observation.py              # WITNESS generation deltas
│   ├── soma.py                     # organismal biology, development and field guide
│   ├── paleon.py                   # DEEP TIME 2.0 coupled planetary engine
│   ├── nerve.py                    # cognition, memory, learning and culture
│   ├── planet.py                   # compatibility surface delegated to PALEON
│   ├── render.py                   # atlas, phylogeny, food web and Observatory
│   └── ...
├── renders/
│   ├── current.svg                 # World Atlas
│   ├── soma.svg                    # SOMA organism field guide
│   ├── paleon.svg                  # PALEON planetary systems plate
│   ├── nerve.svg                   # NERVE ethogram / living minds plate
│   ├── organisms/                  # per-lineage schematic plates
│   ├── phylogeny.svg
│   └── foodweb.svg
├── tests/                          # invariant + observation tests
└── world/
    ├── current.json
    ├── species.json
    ├── environment.json
    ├── pathogens.json
    ├── interactions.json
    ├── plates.json
    ├── branch.json
    └── changes.json                # most recent generation delta
```


## Current model — NERVE + SOMA + PALEON

PHYLUM runs **PALEON (DEEP TIME 2.0)** as its coupled planetary engine, **SOMA** as its organismal biology layer, **NERVE** as its cognition and behavior layer, and **WITNESS** as its observation system. **PALEON gives life a changing planet. SOMA gives life bodies. NERVE gives life experience. WITNESS records the evidence.**

NERVE adds nervous-system complexity, perception, spatial and threat memory, learning, behavioral repertoires, temperament, social recognition, cooperation, communication complexity, cultural traditions, social transmission, costly cognition and the possibility of object-assisted behavior. Learned state persists inside a lineage but is not treated as genetic code; descendant lineages inherit cognitive architecture while cultural traditions only cross a split through founder transmission.

Cognition has energetic and life-history costs, and no intelligence milestone is scheduled. Tool use, teaching, complex communication and persistent culture are possibilities produced by anatomy, ecology, selection and experience rather than guaranteed progression.

The generated `renders/nerve.svg` ethogram and `docs/nerve.html` browser expose the current cognitive and behavioral state alongside the SOMA field guide and PALEON planetary dossier.


## Observatory

Every generation regenerates a static Observatory in `docs/`. The layered World Atlas exposes biomes, tectonics, relief, rivers, territories, migration, ecology, predator/prey contact zones, disease, current-generation events, fossils, scars, population density, biodiversity, genetics and climate.

WITNESS also adds a **CHANGES** view for generation-to-generation population, range, lineage, pathogen, predation, movement and infection deltas. The Observatory retains lineage and fossil browsers, branch ancestry/contact history, event timelines and deep-time atlas snapshots. Enable GitHub Pages from the repository's `docs/` folder to turn it into a live observation station.

Open the generated **SOMA Field Guide** at `docs/soma.html` for organism plates, life cycles, physiology, reproduction and behavior. Open the **PALEON planetary dossier** at `docs/paleon.html` for atmosphere, ocean, cryosphere, nutrient-cycle and hydrology state.

Branch tools: `python -m phylum compare ../OTHER-PHYLUM` and `python -m phylum contact ../OTHER-PHYLUM`. See `PHYLUM_MERGE.md` for the biological contact rule.


## License

PHYLUM is **source-available**, not MIT-licensed.

Copyright (c) 2026 **MOURNINGSTAR**. All rights reserved.

Personal, educational, research, evaluation, and other non-commercial use is
permitted under the **MOURNINGSTAR Source License v1.0**. GitHub-native forks
are permitted for non-commercial experimentation, contribution, and PHYLUM's
branch-evolution features.

**Sale, commercial use, sublicensing, repackaging, hosted commercial use, and
redistribution outside the license's limited GitHub-fork permission are
prohibited without prior written permission from MOURNINGSTAR.**

See [`LICENSE`](LICENSE) for the complete terms.
