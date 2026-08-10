# PHYLUM

**An evolutionary simulation written into Git history.**

PHYLUM is a small artificial biosphere that advances itself inside a Git repository. Every generation mutates the persistent world state, redraws the habitat, records important events, and becomes a commit.

Git is not just where PHYLUM's source code lives. **Git is its fossil record.**

![Current PHYLUM world](renders/current.svg?gen=000013)

<!-- PHYLUM:STATE:START -->
**Generation:** `13`  
**Era:** `Origin Era`  
**Living lineages:** `3`  
**Extinct lineages:** `0`  
**Population:** `1,010`  
**Occupied cells:** `38` / `1440`  
**Active pathogens:** `0`  
**Predator/prey links:** `0`  
**Dominant lineage:** `pale filament`  
**Last generation Δ:** `-2` organisms · `+0` occupied cells  
**Latest fossil:** The biosphere advances through generation 13.
<!-- PHYLUM:STATE:END -->


## Living phylogeny

![PHYLUM phylogeny](renders/phylogeny.svg?gen=000013)

## Living food web

![PHYLUM food web](renders/foodweb.svg?gen=000013)

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
│   ├── planet.py                   # climate, geography and tectonics
│   ├── render.py                   # atlas, phylogeny, food web and Observatory
│   └── ...
├── renders/
│   ├── current.svg                 # World Atlas
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


## Current model — WITNESS

PHYLUM currently runs **DEEP TIME** as its biological and planetary simulation, with **WITNESS** as the observation layer that records what changed between generations. **DEEP TIME governs the world. WITNESS records the evidence.**

DEEP TIME includes population genetics and sexual reproduction; genetic diversity, recombination, bottlenecks and inbreeding; inherited morphology and behavior; ecological niches, competition and predator/prey food webs; evolving pathogens and immunity; migration and isolation-driven speciation; generated geography, biomes, rivers, climate and tectonic drift; disasters and rare unscripted mass extinctions; explicit extinction causes, fossils and phylogeny; deep-time atlas snapshots; fork identity, branch comparison and biological branch-contact rules.

WITNESS adds persistent `world/changes.json` generation deltas, per-lineage population/range/movement/infection changes, current-generation event markers, migration history, predator/prey contact zones, disease overlays, the World Atlas Generation Delta panel, the Observatory **CHANGES** tab, and the `python -m phylum changes` report.

Nothing is scheduled to happen at a specific generation. PHYLUM creates conditions and lets history emerge from them.


## Observatory

Every generation regenerates a static Observatory in `docs/`. The layered World Atlas exposes biomes, tectonics, relief, rivers, territories, migration, ecology, predator/prey contact zones, disease, current-generation events, fossils, scars, population density, biodiversity, genetics and climate.

WITNESS also adds a **CHANGES** view for generation-to-generation population, range, lineage, pathogen, predation, movement and infection deltas. The Observatory retains lineage and fossil browsers, branch ancestry/contact history, event timelines and deep-time atlas snapshots. Enable GitHub Pages from the repository's `docs/` folder to turn it into a live observation station.

Branch tools: `python -m phylum compare ../OTHER-PHYLUM` and `python -m phylum contact ../OTHER-PHYLUM`. See `PHYLUM_MERGE.md` for the biological contact rule.


## License

MIT.
