# PHYLUM

**An autonomous artificial biosphere written into Git history.**

PHYLUM is an autonomous artificial biosphere that lives inside a Git repository. Every observation checkpoint resolves continuous simulated time, redraws the habitat, records important evidence, and becomes a commit.

Git is not just where PHYLUM's source code lives. **Git is its fossil record.**

![Current PHYLUM world](renders/current.svg?gen=000055)

<!-- PHYLUM:STATE:START -->
**Observation:** `55`  
**Simulated time:** `day 476` / `year 1.32`  
**Era:** `Origin Era`  
**Living lineages:** `3`  
**Extinct lineages:** `0`  
**Population:** `902`  
**Occupied cells:** `81` / `1440`  
**Active pathogens:** `1`  
**Predator/prey links:** `0`  
**Dominant lineage:** `pale filament`  
**Last checkpoint Δ:** `-1` organisms · `+0` occupied cells  
**Latest fossil:** VIVARIUM advances 14 simulated days to year 1.32.
<!-- PHYLUM:STATE:END -->


## Living phylogeny

![PHYLUM phylogeny](renders/phylogeny.svg?gen=000055)

## Living food web

![PHYLUM food web](renders/foodweb.svg?gen=000055)

## Persistent groups — SOCIUS

![PHYLUM SOCIUS social lineage record](renders/socius.svg?gen=000055)

## Living cultures — TECHNE

![PHYLUM TECHNE cultural record](renders/techne.svg?gen=000055)

## Living minds — NERVE

![PHYLUM NERVE ethogram](renders/nerve.svg?gen=000055)

## Planetary system — PALEON

![PHYLUM PALEON planetary system](renders/paleon.svg?gen=000055)

## Living organisms — SOMA

![PHYLUM SOMA field guide](renders/soma.svg?gen=000055)

## The idea

A scheduled GitHub Action wakes up every six hours and advances one observation checkpoint. Inside that checkpoint VIVARIUM resolves daily life: organisms feed, move, age, reproduce, learn, transmit infection and die while slower planetary and cultural clocks advance on their own simulated timescales.

Each run changes files such as:

```text
world/current.json
world/species.json
world/environment.json
renders/current.svg
fossils/events.ndjson
```

The Action then commits those changes. A repository's commit history therefore becomes a sequence of observations from the biosphere's continuous history.

```text
world 000041 — pale filament diverges from glass mote
world 000104 — A prolonged dry phase begins
world 000139 — rust bell becomes extinct
world 000207 — silt frond is the most abundant lineage
```

Check out an old commit and you have literally checked out an extinct version of the world.

## Forks are alternate evolutionary timelines

PHYLUM salts its random stream with the GitHub repository identity. When another person forks the project, that fork inherits the same ancestry but begins producing different biological outcomes on its next observation checkpoint.

Two forks from the same observation can therefore become two different biospheres.

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
4. Run **Evolve PHYLUM** manually once with `workflow_dispatch` to verify that the bot can create an observation commit.
5. Leave it alone. The included schedule attempts one observation checkpoint every six hours.

Scheduled Actions are not guaranteed to execute at the exact scheduled minute. VIVARIUM therefore advances its own deterministic simulated clock inside each checkpoint instead of treating wall-clock delay as biological time.

## Anatomy

```text
PHYLUM/
├── .github/workflows/evolve.yml   # autonomous evolution
├── docs/                           # generated Observatory / GitHub Pages
├── fossils/
│   ├── events.ndjson               # append-only event chronology
│   ├── history.ndjson              # observation summaries
│   ├── atlas-history.ndjson        # deep-time atlas snapshots
│   ├── species/                    # extinct-lineage records
│   └── checkpoints/                # periodic recovery state
├── phylum/
│   ├── biology.py                  # genetics, reproduction, ecology, speciation
│   ├── branching.py                # fork identity, comparison and contact
│   ├── disease.py                  # pathogens and immunity
│   ├── observation.py              # WITNESS checkpoint deltas
│   ├── soma.py                     # organismal biology, development and field guide
│   ├── paleon.py                   # DEEP TIME 2.0 coupled planetary engine
│   ├── nerve.py                    # cognition, memory, learning and culture
│   ├── techne.py                   # cultural inheritance, material practices and archaeology
│   ├── socius.py                   # persistent groups, norms and social lineages
│   ├── orrery.py                   # ORRERY atlas and Observatory renderer
│   ├── planet.py                   # compatibility surface delegated to PALEON
│   ├── render.py                   # atlas, phylogeny, food web and Observatory
│   └── ...
├── renders/
│   ├── current.svg                 # World Atlas
│   ├── soma.svg                    # SOMA organism field guide
│   ├── paleon.svg                  # PALEON planetary systems plate
│   ├── nerve.svg                   # NERVE ethogram / living minds plate
│   ├── techne.svg                  # TECHNE cultural / archaeological record
│   ├── socius.svg                  # SOCIUS social-lineage record
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
    └── changes.json                # most recent checkpoint delta
```


## Current architecture — VIVARIUM + CORTEX + ORRERY

**VIVARIUM is the engine. ORRERY is the interface.**

VIVARIUM resolves PHYLUM's continuous living state: explicit organisms and bounded cohorts feed, age, move, reproduce, inherit genes, learn, transmit infection and die. CORTEX gives resolved organisms bounded inherited neural controllers with lifetime plasticity; learned plastic changes die with the organism while neural architecture and innate weights can recombine and mutate in offspring. Species statistics are measurements of that living substrate rather than a second independently evolving population number.

ORRERY is the single observatory shell for the world. Its **WORLD** view presents the planetary composite; **LIFE** exposes VIVARIUM's organism/cohort state; **BODY**, **BEHAVIOR**, **CULTURE**, **SOCIETY**, and **PLANET** expose SOMA, NERVE, TECHNE, SOCIUS, and PALEON without pretending they are separate products. WITNESS remains the evidence/history layer.


## Living engine — VIVARIUM

Continuous time: **day 476 / year 1.32** at observation **55**. Open [`docs/life.html`](docs/life.html) for the ORRERY **LIFE** view.

The historical `docs/vivarium.html` URL now redirects to LIFE so there is only one observatory hierarchy.

## Observatory

### System hierarchy

```text
VIVARIUM = living-world engine
CORTEX   = evolving neural controllers / lifetime learning
ORRERY   = observatory / interface
PALEON   = planet
SOMA     = body
NERVE    = behavior and learning
TECHNE   = culture and material knowledge
SOCIUS   = persistent social organization
WITNESS  = history and evidence
```


Every observation checkpoint regenerates a static Observatory in `docs/`. The layered World Atlas exposes biomes, tectonics, relief, rivers, territories, migration, ecology, predator/prey contact zones, disease, current-checkpoint events, fossils, scars, population density, biodiversity, genetics and climate.

WITNESS also adds a **CHANGES** view for checkpoint-to-checkpoint population, range, lineage, pathogen, predation, movement and infection deltas. The Observatory retains lineage and fossil browsers, branch ancestry/contact history, event timelines and deep-time atlas snapshots. Enable GitHub Pages from the repository's `docs/` folder to turn it into a live observation station.

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
