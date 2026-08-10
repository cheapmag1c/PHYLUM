import random
import tempfile
import unittest
from pathlib import Path

from phylum.paleon import (
    COARSE_COLS,
    COARSE_ROWS,
    PALEON_SCHEMA_VERSION,
    ensure_paleon_state,
    evolve_paleon_planet,
    finalize_paleon_generation,
    paleon_biome_at,
    paleon_climate_at,
    paleon_geography_at,
    render_paleon_assets,
    validate_paleon_state,
)


def fixture():
    world = {"seed": 314159265, "generation": 14, "clocks": {"ecology": 14, "evolution": 2.5, "climate": 0.5, "geology": 0.08}}
    env = {"width": 160, "height": 100, "temperature": 0.55, "moisture": 0.53, "resources": 0.69, "scars": [], "season_phase": 0.0, "ancestral_refugia": [{"x": 50, "y": 50, "radius": 12}]}
    plates = {"sea_level": 0.47, "geology_clock": 3.0, "drift_scale": 0.22, "plates": [
        {"id": "plate-01", "cx": 32, "cy": 43, "vx": 0.035, "vy": 0.012, "phase": 0.2, "continental": True, "buoyancy": 0.08},
        {"id": "plate-02", "cx": 91, "cy": 50, "vx": -0.027, "vy": 0.009, "phase": 1.2, "continental": False, "buoyancy": -0.05},
        {"id": "plate-03", "cx": 139, "cy": 57, "vx": 0.011, "vy": -0.025, "phase": 2.1, "continental": True, "buoyancy": 0.03},
    ]}
    species = [{"id": "sp-1", "name": "pale filament", "population": 700, "extinct_generation": None, "range": [[10, 10], [11, 10], [11, 11]], "genome": {"body_size": 0.7, "autotrophy": 0.82, "herbivory": 0.08, "carnivory": 0.01, "detritivory": 0.12, "engineering": 0.19, "aquatic": 0.04, "burrowing": 0.6}, "soma": {"physiology": {"metabolism": 0.42}, "body_plan": {"defenses": ["burrow-refuge"]}}}]
    return world, env, plates, species


class PaleonTests(unittest.TestCase):
    def test_migration_preserves_generation(self):
        world, env, plates, species = fixture()
        generation = world["generation"]
        ensure_paleon_state(world, env, plates, species)
        self.assertEqual(world["generation"], generation)
        self.assertEqual(env["paleon"]["schema"], PALEON_SCHEMA_VERSION)
        self.assertEqual(len(env["paleon"]["surface"]["soil_fertility"]), COARSE_COLS * COARSE_ROWS)

    def test_geography_and_climate_are_deterministic_and_bounded(self):
        world, env, plates, species = fixture(); ensure_paleon_state(world, env, plates, species)
        a = paleon_geography_at(env, plates, 72, 42, world["seed"])
        b = paleon_geography_at(env, plates, 72, 42, world["seed"])
        self.assertEqual(a, b)
        self.assertIn(a["boundary_type"], {"interior", "passive", "convergent", "divergent", "transform"})
        c = paleon_climate_at(env, plates, 72, 42, world["seed"])
        d = paleon_climate_at(env, plates, 72, 42, world["seed"])
        self.assertEqual(c, d)
        self.assertTrue(0 <= c[0] <= 1 and 0 <= c[1] <= 1 and 0.02 <= c[2] <= 1.35)

    def test_independent_plate_instances_are_deterministic_after_env_migration(self):
        # Regression: one geography call migrates the shared environment, but a
        # separately created identical plate dictionary must still initialize its
        # own PALEON tectonic properties and return exactly the same geography.
        from phylum.planet import initialize_plates
        env = {"width": 160, "height": 100, "temperature": 0.5, "moisture": 0.5, "resources": 0.7, "scars": []}
        a = initialize_plates(42, env)
        b = initialize_plates(42, env)
        ga = paleon_geography_at(env, a, 70, 40, 42)
        gb = paleon_geography_at(env, b, 70, 40, 42)
        self.assertEqual(ga, gb)

    def test_biomes_remain_world_atlas_compatible(self):
        world, env, plates, species = fixture(); ensure_paleon_state(world, env, plates, species)
        allowed = {"abyss", "shelf", "ice", "tundra", "alpine", "desert", "steppe", "temperate", "wetland", "rainforest", "barren"}
        for y in (10, 30, 50, 70, 90):
            for x in (10, 50, 90, 130, 155):
                self.assertIn(paleon_biome_at(env, plates, x, y, world["seed"]), allowed)

    def test_planet_step_keeps_state_valid(self):
        world, env, plates, species = fixture(); ensure_paleon_state(world, env, plates, species)
        world["generation"] += 1
        evolve_paleon_planet(world, env, plates, random.Random(7))
        self.assertEqual(validate_paleon_state(world, env, plates), [])

    def test_life_feedback_does_not_directly_rewrite_population(self):
        world, env, plates, species = fixture(); ensure_paleon_state(world, env, plates, species)
        population = species[0]["population"]
        before = env["paleon"]["atmosphere"]["co2"]
        finalize_paleon_generation(world, species, env, plates, [], random.Random(11))
        self.assertEqual(species[0]["population"], population)
        self.assertNotEqual(env["paleon"]["atmosphere"]["co2"], before)
        self.assertEqual(validate_paleon_state(world, env, plates), [])

    def test_planetary_assets_render(self):
        world, env, plates, species = fixture(); ensure_paleon_state(world, env, plates, species)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            render_paleon_assets(world, species, env, plates, root)
            self.assertTrue((root / "renders" / "paleon.svg").exists())
            self.assertTrue((root / "docs" / "paleon.html").exists())
            self.assertIn("PALEON", (root / "renders" / "paleon.svg").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
