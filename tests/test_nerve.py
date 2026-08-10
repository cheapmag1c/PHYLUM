from __future__ import annotations

import copy
import random
import unittest

from phylum.nerve import (
    MAX_MEMORIES,
    ensure_nerve_schema,
    finalize_nerve_generation,
    nerve_bias_descendant_genome,
    nerve_catalog,
    prepare_nerve_generation,
    validate_nerve_state,
)


def specimen(sid="sp-1", parent_id=None):
    return {
        "id": sid,
        "name": "glass mote",
        "parent_id": parent_id,
        "born_generation": 0,
        "extinct_generation": None,
        "population": 400.0,
        "range": [[10, 10], [11, 10], [11, 11]],
        "genetic_diversity": 0.55,
        "genome": {
            "complexity": 0.62, "sensory": 0.65, "sociality": 0.60, "lifespan": 0.55,
            "mobility": 0.45, "engineering": 0.40, "aggression": 0.25, "defense": 0.45,
            "nocturnal": 0.15, "fecundity": 0.40, "attack": 0.2,
        },
        "ecology": {"role": "grazer"},
        "soma": {
            "body_plan": {"senses": ["chemical", "light", "vibration"], "appendages": 6, "locomotion": ["crawling"]},
            "physiology": {"plasticity": 0.64},
            "behavior": {"communication": ["chemical", "visual-display"], "migration_tendency": 0.55, "territoriality": 0.2},
            "reproduction": {"parental_care_score": 0.35},
        },
        "infections": {},
    }


class NerveTests(unittest.TestCase):
    def test_schema_is_deterministic(self):
        a = specimen(); b = copy.deepcopy(a)
        ensure_nerve_schema(a, 123, 10, {"sp-1": a})
        ensure_nerve_schema(b, 123, 10, {"sp-1": b})
        self.assertEqual(a["nerve"]["signature"], b["nerve"]["signature"])
        self.assertFalse(validate_nerve_state(a))

    def test_descendant_inherits_architecture_not_memory(self):
        parent = specimen("sp-1")
        ensure_nerve_schema(parent, 7, 10, {"sp-1": parent})
        parent["nerve"]["memory"] = [{"kind":"resource","position":[10,10],"strength":0.8,"generation":10,"detail":"x"}]
        child = specimen("sp-2", "sp-1")
        ensure_nerve_schema(child, 7, 11, {"sp-1": parent, "sp-2": child})
        self.assertEqual(child["nerve"]["memory"], [])
        self.assertGreater(child["nerve"]["architecture"]["neural_complexity"], 0)

    def test_prepare_builds_modifiers(self):
        sp = specimen(); ensure_nerve_schema(sp, 1, 4, {"sp-1":sp})
        world={"generation":5,"seed":1}; env={"resources":0.75}
        prepare_nerve_generation(world,[sp],env,[],random.Random(2))
        self.assertIn("energy_efficiency", sp["nerve"]["modifiers"])
        self.assertGreater(sp["nerve"]["modifiers"]["energy_efficiency"],0)

    def test_predation_can_be_remembered(self):
        sp=specimen(); sp["genome"]["complexity"]=0.95; sp["genome"]["sensory"]=0.95
        ensure_nerve_schema(sp,1,4,{"sp-1":sp})
        world={"generation":5,"seed":1}; env={"resources":0.5}
        interactions=[{"type":"predation","source":"sp-x","target":"sp-1","strength":0.8}]
        for k in range(20): prepare_nerve_generation(world,[sp],env,interactions,random.Random(k))
        self.assertTrue(any(m.get("kind")=="threat" for m in sp["nerve"]["memory"]))

    def test_memory_is_bounded(self):
        sp=specimen(); ensure_nerve_schema(sp,1,4,{"sp-1":sp})
        sp["nerve"]["memory"]=[{"kind":"x","position":[i%48,i%30],"strength":0.5,"generation":1,"detail":"x"} for i in range(100)]
        ensure_nerve_schema(sp,1,4,{"sp-1":sp})
        self.assertLessEqual(len(sp["nerve"]["memory"]),MAX_MEMORIES)

    def test_finalize_updates_experience(self):
        sp=specimen(); ensure_nerve_schema(sp,1,4,{"sp-1":sp})
        world={"generation":5,"seed":1}; env={"resources":0.5}
        before=sp["nerve"]["experience_generations"]
        finalize_nerve_generation(world,[sp],env,[],random.Random(1))
        self.assertEqual(sp["nerve"]["experience_generations"],before+1)

    def test_cognition_selection_is_weak_and_bounded(self):
        sp=specimen(); ensure_nerve_schema(sp,1,4,{"sp-1":sp})
        sp["nerve"]["selection_pressures"]={"cognition":1,"learning":1,"social":1,"manipulation":1}
        child={"complexity":0.5,"sensory":0.5,"sociality":0.5,"lifespan":0.5,"engineering":0.5,"mobility":0.3}
        out=nerve_bias_descendant_genome(sp,copy.deepcopy(child),random.Random(3))
        self.assertGreater(out["complexity"],child["complexity"])
        self.assertLess(out["complexity"]-child["complexity"],0.01)
        self.assertLessEqual(out["mobility"],0.75)

    def test_catalog_exposes_behavior_and_culture(self):
        sp=specimen(); ensure_nerve_schema(sp,1,4,{"sp-1":sp})
        row=nerve_catalog([sp])[0]
        self.assertIn("repertoire",row)
        self.assertIn("culture",row)
        self.assertIn("architecture",row)


if __name__ == "__main__":
    unittest.main()
