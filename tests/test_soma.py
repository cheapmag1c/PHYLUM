import random
import tempfile
import unittest
from pathlib import Path

from phylum.soma import (
    ensure_soma_schema,
    bias_descendant_genome,
    finalize_soma_generation,
    prepare_soma_generation,
    render_soma_svg,
    soma_modifiers,
    soma_signature,
    validate_soma_state,
)


def species_fixture(sid="sp-00001", parent_id=None, population=320.0):
    return {
        "id": sid,
        "name": "pale filament" if sid == "sp-00001" else "hollow filament",
        "parent_id": parent_id,
        "born_generation": 0 if parent_id is None else 12,
        "extinct_generation": None,
        "population": population,
        "range": [[10, 10], [11, 10], [10, 11], [11, 11]],
        "genetic_diversity": 0.42,
        "heterozygosity": 0.4,
        "inbreeding": 0.01,
        "last_births": 18.0,
        "last_deaths": 11.0,
        "last_fitness": 0.61,
        "infections": {},
        "ecology": {"role": "producer", "morphology": {"symmetry": "radial"}},
        "genome": {
            "aggression": 0.12, "aquatic": 0.08, "armor": 0.11, "attack": 0.09,
            "autotrophy": 0.88, "body_size": 0.62, "burrowing": 0.08, "carnivory": 0.02,
            "complexity": 0.12, "defense": 0.28, "detritivory": 0.06, "engineering": 0.02,
            "fecundity": 0.42, "herbivory": 0.08, "immune": 0.34, "lifespan": 0.31,
            "mobility": 0.18, "moisture_pref": 0.62, "nocturnal": 0.10,
            "recombination": 0.40, "sensory": 0.30, "sexuality": 0.72, "sociality": 0.28,
            "speed": 0.39, "temp_pref": 0.51, "tolerance": 0.29,
        },
    }


class SomaTests(unittest.TestCase):
    def test_schema_is_deterministic(self):
        a = species_fixture()
        b = species_fixture()
        ensure_soma_schema(a, 314159265, 12, {a["id"]: a})
        ensure_soma_schema(b, 314159265, 12, {b["id"]: b})
        self.assertEqual(a["soma"], b["soma"])

    def test_cohorts_sum_to_population(self):
        sp = species_fixture(population=355.5)
        ensure_soma_schema(sp, 4, 10, {sp["id"]: sp})
        total = sum(sp["soma"]["life_cycle"]["cohorts"].values())
        self.assertAlmostEqual(total, sp["population"], places=2)

    def test_energy_budget_is_normalized(self):
        sp = species_fixture()
        ensure_soma_schema(sp, 4, 10, {sp["id"]: sp})
        budget = sp["soma"]["physiology"]["energy_budget"]
        self.assertAlmostEqual(sum(budget.values()), 1.0, places=2)

    def test_modifiers_are_bounded(self):
        sp = species_fixture()
        ensure_soma_schema(sp, 4, 10, {sp["id"]: sp})
        mods = soma_modifiers(sp, {"season_phase": 0.2})
        for value in mods.values():
            self.assertGreater(value, 0.0)
            self.assertLess(value, 1.7)

    def test_prepare_does_not_change_population(self):
        sp = species_fixture()
        old = sp["population"]
        prepare_soma_generation({"seed": 4, "generation": 11}, [sp], {"season_phase": 0.2}, [], random.Random(1))
        self.assertEqual(old, sp["population"])

    def test_finalize_preserves_authoritative_population(self):
        sp = species_fixture()
        world = {"seed": 4, "generation": 12}
        prepare_soma_generation(world, [sp], {"season_phase": 0.2}, [], random.Random(1))
        old = sp["population"]
        finalize_soma_generation(world, [sp], {"season_phase": 0.2}, [], random.Random(2))
        self.assertEqual(old, sp["population"])
        total = sum(sp["soma"]["life_cycle"]["cohorts"].values())
        self.assertAlmostEqual(total, old, places=2)

    def test_descendant_inherits_ancestral_architecture(self):
        parent = species_fixture()
        ensure_soma_schema(parent, 4, 11, {parent["id"]: parent})
        child = species_fixture("sp-00004", parent_id=parent["id"], population=80.0)
        child["genome"] = dict(parent["genome"])
        child["genome"]["body_size"] = 0.70
        by_id = {parent["id"]: parent, child["id"]: child}
        ensure_soma_schema(child, 4, 12, by_id)
        ps = soma_signature(parent["soma"])
        cs = soma_signature(child["soma"])
        shared = sum(ps[k] == cs[k] for k in ps)
        self.assertGreaterEqual(shared, len(ps) - 3)

    def test_validation_accepts_migrated_species(self):
        sp = species_fixture()
        ensure_soma_schema(sp, 4, 10, {sp["id"]: sp})
        self.assertEqual(validate_soma_state(sp), [])


    def test_directional_selection_nudges_descendants(self):
        parent = species_fixture()
        ensure_soma_schema(parent, 4, 20, {parent["id"]: parent})
        parent["soma"]["selection_pressures"].update({"predation": 0.9, "disease": 0.8, "competition": 0.4, "climate": 0.5, "sexual": 0.6})
        child = dict(parent["genome"])
        before = dict(child)
        bias_descendant_genome(parent, child, random.Random(7), 1.0)
        self.assertGreaterEqual(child["defense"], before["defense"])
        self.assertGreaterEqual(child["immune"], before["immune"])
        self.assertGreaterEqual(child["sensory"], before["sensory"])

    def test_dormancy_and_symbiosis_change_demography(self):
        sp = species_fixture()
        ensure_soma_schema(sp, 4, 10, {sp["id"]: sp})
        sp["soma"]["physiology"]["dormancy"] = "stress-induced"
        stressed = soma_modifiers(sp, {"season_phase": 0.2, "resources": 0.2})
        normal = soma_modifiers(sp, {"season_phase": 0.2, "resources": 0.7})
        self.assertLess(stressed["birth"], normal["birth"])
        sp["soma"]["symbioses"] = [{"partner": "sp-2", "type": "mutualism"}]
        mutual = soma_modifiers(sp, {"season_phase": 0.2, "resources": 0.7})
        self.assertGreaterEqual(mutual["energy_efficiency"], normal["energy_efficiency"])

    def test_symbiosis_ends_when_ranges_separate(self):
        a = species_fixture("sp-00001")
        b = species_fixture("sp-00002")
        by_id = {a["id"]: a, b["id"]: b}
        ensure_soma_schema(a, 4, 10, by_id)
        ensure_soma_schema(b, 4, 10, by_id)
        a["soma"]["symbioses"] = [{"partner": b["id"], "type": "mutualism"}]
        b["soma"]["symbioses"] = [{"partner": a["id"], "type": "mutualism"}]
        b["range"] = [[30, 30], [31, 30]]
        prepare_soma_generation({"seed": 4, "generation": 11}, [a, b], {"season_phase": 0.2}, [], random.Random(1))
        self.assertEqual(a["soma"]["symbioses"], [])
        self.assertEqual(b["soma"]["symbioses"], [])

    def test_field_guide_renders(self):
        sp = species_fixture()
        ensure_soma_schema(sp, 4, 10, {sp["id"]: sp})
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "soma.svg"
            svg = render_soma_svg({"generation": 10}, [sp], path)
            self.assertTrue(path.exists())
            self.assertIn("SOMA FIELD GUIDE", svg)
            self.assertIn("PALE FILAMENT", svg)


if __name__ == "__main__":
    unittest.main()
