from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

from phylum.socius import (
    MAX_ARCHIVE, MAX_GROUPS, MAX_NORMS, MAX_RELATIONSHIPS,
    _create_group, _territory_partition, apply_socius_feedback,
    ensure_socius_schema, ensure_world_socius, finalize_socius_generation,
    prepare_socius_generation, socius_catalog, validate_socius_state,
    validate_socius_world, render_socius_svg,
)
from phylum.orrery import render_phylogeny_orrery, render_world_orrery


def specimen(pop: float = 420.0, advanced: bool = True) -> dict:
    social = 0.82 if advanced else 0.08
    neural = 0.76 if advanced else 0.12
    return {
        "id": "sp-test", "name": "test filament", "population": pop,
        "born_generation": 0, "extinct_generation": None, "range": [[10,10],[11,10],[12,10],[10,11],[11,11],[12,11]],
        "genome": {"sociality": social, "aggression": 0.12, "complexity": neural, "lifespan": 0.72, "engineering": 0.25},
        "soma": {"behavior": {"territoriality": 0.42, "migration_tendency": 0.20}, "reproduction": {"parental_care_score": 0.62}, "physiology": {"plasticity": 0.5}, "body_plan": {"appendages": 4}},
        "nerve": {
            "architecture": {"neural_complexity": neural, "memory_capacity": neural, "planning_horizon": 0.66 if advanced else 0.0},
            "social": {"cooperation": social, "recognition": social, "reciprocity": 0.62 if advanced else 0.0, "signal_complexity": social, "teaching": 0.35 if advanced else 0.0},
            "temperament": {"sociability": social},
        },
        "techne": {"capacities": {"transmission": 0.72 if advanced else 0.0, "cultural_storage": 0.70 if advanced else 0.0}, "practices": [{"name":"persistent nesting","strength":0.7}] if advanced else []},
        "infections": {}, "peak_population": pop,
    }


def world() -> dict:
    return {"generation": 40, "seed": 1234, "schema_version": 14, "techne": {"sites": [], "archive": [], "cultural_lineages": []}}


class SociusTests(unittest.TestCase):
    def test_schema_is_deterministic_and_bounded(self):
        a, b = specimen(), specimen()
        sa = ensure_socius_schema(a, 1, 0, {a["id"]: a})
        sb = ensure_socius_schema(b, 1, 0, {b["id"]: b})
        self.assertEqual(sa["capacities"], sb["capacities"])
        self.assertFalse(validate_socius_state(a))

    def test_primitive_migration_does_not_invent_group(self):
        w = world(); sp = specimen(advanced=False)
        ensure_world_socius(w); ensure_socius_schema(sp, 1, 40, {sp["id"]: sp})
        self.assertEqual([], w["socius"]["groups"])
        self.assertLess(sp["socius"]["capacities"]["group_persistence"], 0.42)

    def test_group_creation_has_social_ancestry_fields(self):
        w = world(); sp = specimen(); ensure_world_socius(w); ensure_socius_schema(sp, 1, 40, {sp["id"]: sp})
        g = _create_group(w, sp, 40, random.Random(4))
        self.assertEqual(sp["id"], g["species_id"])
        self.assertIn(g["id"], sp["socius"]["group_ids"])
        self.assertEqual("active", g["status"])
        self.assertEqual(1, len(w["socius"]["group_lineages"]))

    def test_territory_partition_stays_inside_species_range(self):
        w = world(); sp = specimen(); ensure_world_socius(w); ensure_socius_schema(sp, 1, 40, {sp["id"]: sp})
        g1 = _create_group(w, sp, 40, random.Random(1), share=.4)
        g2 = _create_group(w, sp, 40, random.Random(2), parent_group_id=g1["id"], share=.3)
        _territory_partition(sp, [g1,g2])
        allowed = {tuple(x) for x in sp["range"]}
        got = {tuple(x) for g in (g1,g2) for x in g["territory"]}
        self.assertTrue(got <= allowed)

    def test_prepare_does_not_change_population(self):
        w = world(); sp = specimen(); ensure_world_socius(w); ensure_socius_schema(sp, 1, 40, {sp["id"]: sp}); _create_group(w, sp, 40, random.Random(1))
        before = sp["population"]
        prepare_socius_generation(w, [sp], {}, [], random.Random(2))
        self.assertEqual(before, sp["population"])
        self.assertGreaterEqual(sp["socius"]["modifiers"]["demography"], .985)
        self.assertLessEqual(sp["socius"]["modifiers"]["demography"], 1.012)

    def test_feedback_is_weak(self):
        w = world(); sp = specimen(); ensure_socius_schema(sp, 1, 40, {sp["id"]: sp})
        sp["socius"]["modifiers"]["demography"] = 1.012
        apply_socius_feedback(w, [sp])
        self.assertAlmostEqual(425.04, sp["population"], places=2)

    def test_finalize_keeps_world_bounded(self):
        w = world(); sp = specimen(); ensure_world_socius(w); ensure_socius_schema(sp, 1, 40, {sp["id"]: sp}); _create_group(w, sp, 40, random.Random(1))
        for i in range(80):
            w["generation"] += 1
            finalize_socius_generation(w, [sp], {}, [], random.Random(i))
        self.assertLessEqual(len(w["socius"]["groups"]), MAX_GROUPS)
        self.assertLessEqual(len(w["socius"]["archive"]), MAX_ARCHIVE)
        self.assertLessEqual(len(w["socius"]["relationships"]), MAX_RELATIONSHIPS)
        for g in w["socius"]["groups"]:
            self.assertLessEqual(len(g.get("norms", [])), MAX_NORMS)
        self.assertFalse(validate_socius_world(w))

    def test_catalog_exposes_groups_and_relationships(self):
        w = world(); sp = specimen(); ensure_world_socius(w); ensure_socius_schema(sp, 1, 40, {sp["id"]: sp}); _create_group(w, sp, 40, random.Random(1))
        cat = socius_catalog(w, [sp])
        self.assertEqual(1, cat["active_groups"])
        self.assertEqual("test filament", cat["groups"][0]["species_name"])

    def test_socius_svg_renders_empty_and_grouped_worlds(self):
        w = world(); sp = specimen(); ensure_world_socius(w); ensure_socius_schema(sp, 1, 40, {sp["id"]: sp})
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "socius.svg"
            text = render_socius_svg(w, [sp], p)
            self.assertIn("NO PERSISTENT SOCIAL GROUPS YET", text)
            _create_group(w, sp, 40, random.Random(1))
            text = render_socius_svg(w, [sp], p)
            self.assertIn("test filament", text)

    def test_orrery_graphics_render(self):
        w = world(); sp = specimen(); ensure_world_socius(w); ensure_socius_schema(sp, 1, 40, {sp["id"]: sp})
        # A minimal plate/environment fixture accepted by the live PALEON geometry helpers.
        env = {"width":160,"height":100,"temperature":.5,"moisture":.5,"resources":.6,"season_phase":0.0,"scars":[]}
        from phylum.planet import initialize_plates
        plates = initialize_plates(int(w["seed"]), env)
        branch = {"lineage":"test/branch"}
        with tempfile.TemporaryDirectory() as td:
            wp, pp = Path(td)/"world.svg", Path(td)/"phylo.svg"
            a = render_world_orrery(w, [sp], env, [], plates, branch, [], wp)
            b = render_phylogeny_orrery(w, [sp], pp)
            self.assertIn("ORRERY", a)
            self.assertIn('id="layer-social"', a)
            self.assertIn("PHYLOGENY", b)
            self.assertTrue(wp.exists() and pp.exists())


if __name__ == "__main__":
    unittest.main()
