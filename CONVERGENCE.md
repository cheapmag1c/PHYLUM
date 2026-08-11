# PHYLUM 2.0.1 — CONVERGENCE

**One world. One observatory. One hierarchy.**

CONVERGENCE is a presentation and architecture-cleanup patch for PHYLUM 2.0.
It does not alter biological rules, populations, continuous simulated time, fossil
history, or the MOURNINGSTAR Source License.

The hierarchy is now explicit:

```text
VIVARIUM = living-world engine
ORRERY   = observatory / interface
PALEON   = planet
SOMA     = body
NERVE    = behavior and learning
TECHNE   = culture and material knowledge
SOCIUS   = persistent social organization
WITNESS  = history and evidence
```

The old VIVARIUM dashboard is no longer presented as a parallel observatory.
ORRERY owns the interface and exposes VIVARIUM through a canonical **LIFE** view.
`docs/vivarium.html` remains only as a compatibility redirect to `docs/life.html`.

## Observable changes

- ORRERY is the sole top-level Observatory identity.
- `WORLD` remains the planetary composite.
- `LIFE` is the organism/cohort view powered by VIVARIUM.
- Module names are presented as conceptual views: BODY, BEHAVIOR, CULTURE,
  SOCIETY, and PLANET.
- ORRERY shows simulated day/year and VIVARIUM engine status.
- README no longer renders a second VIVARIUM hero image.
- `renders/life.svg`, `docs/life.svg`, `docs/life.html`, and
  `docs/life-data.json` are canonical LIFE outputs.
- Historical `vivarium.*` outputs remain compatibility aliases where needed.
