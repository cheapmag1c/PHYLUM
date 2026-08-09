import unittest

from phylum.core import (
    GRID_COLS,
    GRID_ROWS,
    _normalize_range,
    _region_name,
    _territory_target,
    deterministic_rng,
    env_at,
    suitability,
)


class PhylumTests(unittest.TestCase):
    def test_rng_is_lineage_deterministic(self):
        a = deterministic_rng(123, 9, "a/repo").random()
        b = deterministic_rng(123, 9, "a/repo").random()
        c = deterministic_rng(123, 9, "b/repo").random()
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_environment_values_are_bounded(self):
        env = {
            "width": 160,
            "height": 100,
            "temperature": 0.5,
            "moisture": 0.5,
            "resources": 0.7,
            "scars": [{"kind": "drought", "x": 50, "y": 50, "radius": 20, "strength": 0.2}],
        }
        t, m, r = env_at(env, 50, 50, 42)
        self.assertGreaterEqual(t, 0)
        self.assertLessEqual(t, 1)
        self.assertGreaterEqual(m, 0)
        self.assertLessEqual(m, 1)
        self.assertGreater(r, 0)

    def test_suitability_is_bounded(self):
        sp = {"traits": {"temp_pref": 0.5, "moisture_pref": 0.5, "tolerance": 0.25}}
        value = suitability(sp, (0.5, 0.5, 0.8))
        self.assertGreaterEqual(value, 0)
        self.assertLessEqual(value, 1)

    def test_range_normalization_drops_bad_cells(self):
        sp = {"range": [[0, 0], [0, 0], [GRID_COLS - 1, GRID_ROWS - 1], [-1, 4], [999, 2]]}
        self.assertEqual(_normalize_range(sp), {(0, 0), (GRID_COLS - 1, GRID_ROWS - 1)})

    def test_territory_target_scales_with_population(self):
        small = {"population": 20, "traits": {"body_size": 1.0}}
        big = {"population": 2000, "traits": {"body_size": 1.0}}
        self.assertGreater(_territory_target(big), _territory_target(small))

    def test_regions_have_stable_names(self):
        self.assertIn("western", _region_name((0, GRID_ROWS // 2)))
        self.assertIn("eastern", _region_name((GRID_COLS - 1, GRID_ROWS // 2)))


if __name__ == "__main__":
    unittest.main()
