import copy
import unittest

from phylum.core import deterministic_rng, env_at, suitability


class PhylumTests(unittest.TestCase):
    def test_rng_is_lineage_deterministic(self):
        a = deterministic_rng(123, 9, "a/repo").random()
        b = deterministic_rng(123, 9, "a/repo").random()
        c = deterministic_rng(123, 9, "b/repo").random()
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_environment_values_are_bounded(self):
        env = {"width": 160, "height": 100, "temperature": 0.5, "moisture": 0.5, "resources": 0.7}
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


if __name__ == "__main__":
    unittest.main()
