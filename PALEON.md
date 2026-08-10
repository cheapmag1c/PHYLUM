# PALEON — DEEP TIME 2.0

**The world becomes an evolutionary force.**

PALEON is the second-generation planetary engine for PHYLUM. It does not replace SOMA or WITNESS:

- **PALEON / DEEP TIME 2.0** — planet, climate, geology, hydrology, nutrient cycles and life↔world feedback
- **SOMA** — bodies, physiology, development, life history and behavior
- **WITNESS** — observation, generation deltas, history and evidence

## Planetary systems

PALEON adds persistent coupled state for the atmosphere, ocean, cryosphere, hydrology, soils and biogeochemical cycles. The existing `world/environment.json` remains PHYLUM's compatibility state; PALEON lives inside its `paleon` field so old history is migrated rather than restarted.

### Atmosphere

Tracks CO₂, oxygen, methane, aerosols, pressure and greenhouse forcing. Atmospheric composition changes slowly from biological productivity, respiration, decomposition and geological disturbances.

### Climate

Local climate now combines latitude, seasonal phase, relief, ocean proximity, greenhouse forcing, atmospheric oscillation, prevailing-wind/rain-shadow effects, freshwater, soil state and long-lived disturbance scars.

### Hydrology

Tracks freshwater storage, evaporation, runoff, storminess, flood pressure and drought pressure. Coarse surface cells retain freshwater and respond to succession and disturbance.

### Oceans

Tracks heat, oxygen, nutrients, acidity, circulation and anoxia. Warming, weak circulation and nutrient loading can push marine systems toward oxygen loss without a scripted generation trigger.

### Cryosphere and sea level

Ice fraction and snowline respond gradually to climate. Thermal expansion and changing ice volume alter sea level, which feeds directly into `geography_at()` and can expose or drown habitat.

### Soils and succession

A 24×15 persistent surface field tracks soil fertility, soil carbon, freshwater, sediment, ecological succession and disturbance. Fire, flood, drought, impacts and other scars can reset local succession; recovery takes time.

### Tectonics

The seven inherited PHYLUM plates now carry crust type, age, thickness, heat flux, stress and volcanism. Relative plate motion distinguishes convergent, divergent and transform boundaries. Tectonic events emerge when boundary mechanics and accumulated stress align.

## Life ↔ planet feedback

PALEON's defining rule is that life is part of the planetary system.

Autotrophic biomass can slowly draw down CO₂ and contribute oxygen. Respiration and decomposition return carbon. Detritivores affect nutrient recycling. Aquatic biomass influences marine oxygen. SOMA ecosystem engineers can alter local soil fertility, water retention and succession.

The feedback is intentionally slow. A single successful species does not rewrite a planet in one generation; persistent biological dominance across deep time can.

## Compatibility and determinism

PALEON preserves the current PHYLUM generation during installation. The old `planet.py` remains as a compatibility surface and delegates its geography, climate, biome and planet-evolution functions to `paleon.py`, so DEEP TIME ecology, SOMA and the World Atlas all receive the upgraded planet without duplicating state.

No feature is scheduled to occur at a fixed generation. Icehouse intervals, greenhouse states, anoxia, tectonic events, floods, droughts and other transitions arise from state and deterministic lineage-seeded evolution.

## Observation

Every render creates:

- `renders/paleon.svg` — planetary-system plate
- `docs/paleon.html` — static planetary dossier

Use:

```bash
python -m phylum paleon
```

to print the current planetary state as JSON.

## License

PHYLUM and PALEON are distributed under the **MOURNINGSTAR Source License v1.0**. Copyright © 2026 MOURNINGSTAR. All rights reserved. See the repository `LICENSE` file for the complete terms.
