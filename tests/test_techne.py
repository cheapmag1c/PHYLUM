from __future__ import annotations

import copy
import random
import unittest

from phylum.techne import (
    MAX_PRACTICES,
    MAX_SITES,
    ensure_techne_schema,
    ensure_world_techne,
    finalize_techne_generation,
    prepare_techne_generation,
    techne_bias_descendant_genome,
    techne_catalog,
    validate_techne_state,
    validate_techne_world,
)


def specimen(sid="sp-1", parent_id=None):
    return {
        "id": sid,
        "name": "glass mote",
        "parent_id": parent_id,
        "born_generation": 0,
        "extinct_generation": None,
        "population": 500.0,
        "range": [[10, 10], [11, 10], [11, 11]],
        "genome": {
            "complexity": 0.78, "sensory": 0.72, "sociality": 0.72, "lifespan": 0.62,
            "mobility": 0.45, "engineering": 0.68, "aggression": 0.22, "defense": 0.42,
            "aquatic": 0.12,
        },
        "ecology": {"role": "omnivore"},
        "soma": {
            "body_plan": {"senses": ["chemical", "light", "vibration"], "appendages": 8, "locomotion": ["crawling"]},
            "physiology": {"plasticity": 0.66},
            "behavior": {"communication": ["chemical", "visual-display"], "migration_tendency": 0.52, "territoriality": 0.2},
            "reproduction": {"parental_care_score": 0.55},
        },
        "nerve": {
            "architecture": {"neural_complexity": 0.80, "memory_capacity": 0.74, "learning_rate": 0.72, "planning_horizon": 0.68},
            "social": {"signal_complexity": 0.72, "teaching": 0.42, "cooperation": 0.68, "communication": ["chemical", "visual-display"]},
            "manipulation": {"score": 0.72, "tool_capability": True, "construction_capability": True},
            "temperament": {"curiosity": 0.62},
            "culture": {"transmission": 0.62, "traditions": [{"id":"tr-1","name":"river route","origin_generation":2,"strength":0.7}]},
        },
        "infections": {},
    }


class TechneTests(unittest.TestCase):
    def test_schema_is_deterministic_and_valid(self):
        a = specimen(); b = copy.deepcopy(a)
        ensure_techne_schema(a, 123, 10, {"sp-1": a})
        ensure_techne_schema(b, 123, 10, {"sp-1": b})
        self.assertEqual(a["techne"]["dialect"], b["techne"]["dialect"])
        self.assertFalse(validate_techne_state(a))

    def test_parent_can_transmit_practices_without_genetic_copying(self):
        parent = specimen("sp-1")
        ensure_techne_schema(parent, 9, 10, {"sp-1": parent})
        parent["techne"]["capacities"]["transmission"] = 0.9
        parent["techne"]["practices"].append({"id":"p-x","name":"food caching","category":"subsistence","strength":0.8,"lineage_id":"cu-1","origin_generation":4,"last_generation":10})
        child = specimen("sp-2", "sp-1")
        ensure_techne_schema(child, 9, 11, {"sp-1": parent, "sp-2": child})
        self.assertTrue(any(p.get("name") == "food caching" for p in child["techne"]["practices"]))
        self.assertNotEqual(parent["techne"], child["techne"])

    def test_prepare_builds_bounded_modifiers(self):
        sp = specimen(); ensure_techne_schema(sp, 1, 4, {"sp-1": sp})
        sp["techne"]["practices"].append({"name":"food caching","strength":0.8})
        world={"generation":5,"seed":1}; env={"temperature":0.5,"moisture":0.5,"resources":0.7}
        prepare_techne_generation(world,[sp],env,[],random.Random(2))
        self.assertIn("energy_efficiency", sp["techne"]["modifiers"])
        self.assertLessEqual(sp["techne"]["modifiers"]["energy_efficiency"], 1.14)

    def test_world_state_is_bounded(self):
        world={"generation":5,"seed":1}
        t=ensure_world_techne(world)
        t["sites"]=[{"id":f"s-{i}"} for i in range(MAX_SITES+50)]
        ensure_world_techne(world)
        self.assertLessEqual(len(world["techne"]["sites"]),MAX_SITES)
        self.assertFalse(validate_techne_world(world))

    def test_advanced_innovation_not_available_to_primitive_lineage(self):
        sp=specimen();
        sp["nerve"]["architecture"]={"neural_complexity":0.12,"memory_capacity":0.1,"learning_rate":0.1,"planning_horizon":0.0}
        sp["nerve"]["manipulation"]={"score":0.08,"tool_capability":False,"construction_capability":False}
        sp["nerve"]["social"].update({"signal_complexity":0.12,"teaching":0.0,"cooperation":0.15})
        sp["genome"]["engineering"]=0.02
        world={"generation":5,"seed":1}; env={"temperature":0.7,"moisture":0.2,"resources":0.6}
        ensure_techne_schema(sp,1,5,{"sp-1":sp})
        for k in range(500):
            world["generation"] += 1
            prepare_techne_generation(world,[sp],env,[],random.Random(k))
            finalize_techne_generation(world,[sp],env,[],random.Random(k+1000))
        names={p.get("name") for p in sp["techne"]["practices"]}
        self.assertNotIn("controlled combustion",names)
        self.assertNotIn("compound tools",names)
        self.assertNotIn("symbolic marking",names)

    def test_gene_culture_selection_is_weak(self):
        sp=specimen(); ensure_techne_schema(sp,1,5,{"sp-1":sp})
        sp["techne"]["selection_pressures"]={"culture":1,"construction":1,"communication":1}
        child={"complexity":0.5,"sociality":0.5,"engineering":0.5,"sensory":0.5,"lifespan":0.5}
        out=techne_bias_descendant_genome(sp,copy.deepcopy(child),random.Random(4))
        self.assertGreater(out["engineering"], child["engineering"])
        self.assertLess(out["engineering"]-child["engineering"],0.01)

    def test_catalog_exposes_archaeology(self):
        sp=specimen(); world={"generation":9,"seed":2}; ensure_world_techne(world); ensure_techne_schema(sp,2,9,{"sp-1":sp})
        row=techne_catalog(world,[sp])
        self.assertIn("sites",row)
        self.assertIn("cultural_lineages",row)
        self.assertIn("capacities",row["lineages"][0])

    def test_practices_are_bounded(self):
        sp=specimen(); ensure_techne_schema(sp,1,4,{"sp-1":sp})
        sp["techne"]["practices"]=[{"name":f"p{i}","strength":0.5} for i in range(MAX_PRACTICES+20)]
        ensure_techne_schema(sp,1,4,{"sp-1":sp})
        self.assertLessEqual(len(sp["techne"]["practices"]),MAX_PRACTICES)


if __name__ == "__main__":
    unittest.main()
