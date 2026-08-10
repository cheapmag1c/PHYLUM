import json
import random
import tempfile
import unittest
from pathlib import Path

from phylum.biology import (
    behavior_profile, build_food_web, migrate_species_schema, morphology,
    normalize_range, territory_target, trophic_role,
)
from phylum.branching import compare_repositories, contact_worlds, ensure_branch
from phylum.constants import GRID_COLS, GRID_ROWS, SCHEMA_VERSION
from phylum.core import deterministic_rng, env_at, suitability, validate_state
from phylum.disease import migrate_pathogen_schema
from phylum.planet import biome_at, geography_at, initialize_plates, region_name
from phylum.observation import build_changes, capture_observation, format_change_report
from phylum.soma import ensure_soma_schema


class PhylumTests(unittest.TestCase):
    def test_rng_is_lineage_deterministic(self):
        a=deterministic_rng(123,9,"a/repo").random(); b=deterministic_rng(123,9,"a/repo").random(); c=deterministic_rng(123,9,"b/repo").random()
        self.assertEqual(a,b); self.assertNotEqual(a,c)

    def test_environment_values_are_bounded(self):
        env={"width":160,"height":100,"temperature":0.5,"moisture":0.5,"resources":0.7,"scars":[]}
        t,m,r=env_at(env,50,50,42)
        self.assertTrue(0<=t<=1 and 0<=m<=1 and r>0)

    def test_suitability_is_bounded(self):
        sp={"traits":{"temp_pref":0.5,"moisture_pref":0.5,"tolerance":0.25}}
        self.assertTrue(0<=suitability(sp,(0.5,0.5,0.8))<=1)

    def test_range_normalization_drops_bad_cells(self):
        sp={"range":[[0,0],[0,0],[GRID_COLS-1,GRID_ROWS-1],[-1,4],[999,2]]}
        self.assertEqual(normalize_range(sp),{(0,0),(GRID_COLS-1,GRID_ROWS-1)})

    def test_territory_target_scales_with_population(self):
        small={"population":20,"traits":{"body_size":1.0,"mobility":0.2}}
        big={"population":2000,"traits":{"body_size":1.0,"mobility":0.2}}
        self.assertGreater(territory_target(big),territory_target(small))

    def test_regions_have_stable_names(self):
        self.assertIn("western",region_name((0,GRID_ROWS//2))); self.assertIn("eastern",region_name((GRID_COLS-1,GRID_ROWS//2)))

    def test_plate_world_is_deterministic(self):
        env={"width":160,"height":100,"temperature":0.5,"moisture":0.5,"resources":0.7,"scars":[]}
        a=initialize_plates(42,env); b=initialize_plates(42,env)
        self.assertEqual(a,b); self.assertEqual(len(a["plates"]),7)
        self.assertEqual(geography_at(env,a,70,40,42),geography_at(env,b,70,40,42))
        self.assertIn(biome_at(env,a,70,40,42),{"abyss","shelf","ice","tundra","alpine","desert","steppe","temperate","wetland","rainforest","barren"})

    def test_legacy_species_gets_full_genome(self):
        sp={"id":"sp-00001","name":"pale filament","population":100,"traits":{"temp_pref":0.5,"moisture_pref":0.6,"tolerance":0.3,"mobility":0.2,"fecundity":0.4,"body_size":0.7},"range":[[1,1]],"born_generation":0,"extinct_generation":None}
        migrate_species_schema(sp,314159,5)
        for locus in ("sexuality","recombination","immune","carnivory","autotrophy","complexity","engineering"):
            self.assertIn(locus,sp["genome"])
        self.assertGreater(sp["genetic_diversity"],0)

    def test_food_web_can_form_predator_prey_link(self):
        prey={"id":"p","name":"prey","population":300,"extinct_generation":None,"range":[[5,5],[6,5]],"genome":{"temp_pref":.5,"moisture_pref":.5,"autotrophy":.9,"herbivory":.1,"carnivory":0,"detritivory":0,"attack":.1,"speed":.2,"sensory":.2,"defense":.1,"armor":.1,"body_size":.5}}
        pred={"id":"q","name":"pred","population":80,"extinct_generation":None,"range":[[5,5],[6,5]],"genome":{"temp_pref":.5,"moisture_pref":.5,"autotrophy":0,"herbivory":.1,"carnivory":.9,"detritivory":0,"attack":.9,"speed":.8,"sensory":.8,"defense":.2,"armor":.1,"body_size":.7}}
        interactions,loss,gain,comp=build_food_web([prey,pred])
        self.assertTrue(any(i["type"]=="predation" and i["source"]=="q" for i in interactions))
        self.assertGreater(loss.get("p",0),0); self.assertGreater(gain.get("q",0),0)

    def test_morphology_and_behavior_are_derived(self):
        sp={"id":"x","traits":{"body_size":1},"genome":{"body_size":1,"complexity":.8,"armor":.8,"mobility":.7,"sensory":.8,"sociality":.8,"aggression":.7,"burrowing":.7,"nocturnal":.7,"autotrophy":0,"herbivory":0,"carnivory":.9,"detritivory":0}}
        self.assertEqual(trophic_role(sp),"predator")
        self.assertEqual(morphology(sp)["armor"],"heavy")
        self.assertIn("social",behavior_profile(sp)); self.assertIn("migratory",behavior_profile(sp))

    def test_pathogen_schema_backfills_fields(self):
        p=[{"id":"pa-1","name":"test"}]; migrate_pathogen_schema(p)
        self.assertIn("transmissibility",p[0]); self.assertIn("hosts",p[0])

    def test_branch_identity_detects_fork(self):
        world={"seed":1,"created_utc":"x","root_lineage":"PHYLUM/origin","generation":7,"active_lineage":"a/PHYLUM"}; b={}
        ensure_branch(world,b,"a/PHYLUM"); ensure_branch(world,b,"b/PHYLUM")
        self.assertEqual(b["parent_lineage"],"a/PHYLUM"); self.assertEqual(b["diverged_generation"],7); self.assertEqual(b["lineage"],"b/PHYLUM")

    def test_branch_comparison_recognizes_shared_root(self):
        with tempfile.TemporaryDirectory() as td:
            a=Path(td)/"a"; b=Path(td)/"b"
            for root,lineage,pop in ((a,"a/P",100),(b,"b/P",120)):
                (root/"world").mkdir(parents=True)
                (root/"world/current.json").write_text(json.dumps({"generation":5,"total_population":pop}),encoding="utf-8")
                (root/"world/species.json").write_text(json.dumps([{"name":"origin","extinct_generation":None,"genome":{"x":.2},"population":pop}]),encoding="utf-8")
                (root/"world/branch.json").write_text(json.dumps({"lineage":lineage,"root_fingerprint":"same"}),encoding="utf-8")
                (root/"world/pathogens.json").write_text("[]",encoding="utf-8")
            result=compare_repositories(a,b)
            self.assertTrue(result["same_root"]); self.assertIn("origin",result["shared_living_lineages"])

    def test_branch_contact_introduces_foreign_founder(self):
        with tempfile.TemporaryDirectory() as td:
            other=Path(td)/"other"; (other/"world").mkdir(parents=True)
            (other/"world/current.json").write_text(json.dumps({"active_lineage":"b/P","generation":20}),encoding="utf-8")
            foreign={"id":"sp-00009","name":"foreign reed","population":500,"extinct_generation":None,"range":[[10,10],[11,10]],"genome":{"body_size":1,"sexuality":.7},"infections":{}}
            (other/"world/species.json").write_text(json.dumps([foreign]),encoding="utf-8")
            (other/"world/branch.json").write_text(json.dumps({"lineage":"b/P","root_fingerprint":"root"}),encoding="utf-8")
            (other/"world/pathogens.json").write_text("[]",encoding="utf-8")
            world={"generation":20,"next_species_id":2,"next_pathogen_id":1,"active_lineage":"a/P"}; species=[]; pathogens=[]; branch={"lineage":"a/P","root_fingerprint":"root","contacts":[]}
            events=contact_worlds(world,species,pathogens,branch,other)
            self.assertEqual(len(species),1); self.assertEqual(species[0]["native_lineage"],"b/P"); self.assertEqual(events[0]["kind"],"contact")

    def test_validator_accepts_minimal_migrated_world(self):
        env={"width":160,"height":100,"temperature":.5,"moisture":.5,"resources":.7,"scars":[]}
        plates=initialize_plates(1,env)
        world={"schema_version":SCHEMA_VERSION}
        sp={"id":"sp-1","population":1,"extinct_generation":None,"genome":{"temp_pref":.5},"range":[[0,0]]}
        ensure_soma_schema(sp,1,0,{sp["id"]:sp})
        branch={"root_fingerprint":"root"}
        self.assertEqual(validate_state(world,[sp],env,[],plates,branch,[]),[])

    def test_observation_delta_tracks_population_range_and_events(self):
        world={"generation":5}
        env={"width":160,"height":100,"temperature":.5,"moisture":.5,"resources":.7,"scars":[]}
        before_sp={"id":"sp-1","name":"reed","population":100,"extinct_generation":None,"range":[[1,1],[2,1]],"genome":{"autotrophy":.8},"genetic_diversity":.4,"infections":{}}
        before=capture_observation(world,[before_sp],env,[],[])
        world2={"generation":6}
        after_sp={"id":"sp-1","name":"reed","population":125,"extinct_generation":None,"range":[[1,1],[2,1],[3,1]],"genome":{"autotrophy":.8},"genetic_diversity":.41,"infections":{}}
        changes=build_changes(before,world2,[after_sp],env,[],[],[{"generation":6,"kind":"migration","subject":"sp-1","text":"reed reaches east"}])
        self.assertEqual(changes["summary"]["population_delta"],25.0)
        self.assertEqual(changes["summary"]["occupied_delta"],1)
        self.assertEqual(changes["lineages"][0]["range_delta"],1)
        self.assertEqual(changes["markers"][0]["kind"],"migration")
        self.assertIsNotNone(changes["markers"][0]["position"])

    def test_observation_detects_new_and_extinct_lineages(self):
        env={"width":160,"height":100,"temperature":.5,"moisture":.5,"resources":.7,"scars":[]}
        old={"id":"old","name":"old reed","population":20,"extinct_generation":None,"range":[[2,2]],"genome":{"autotrophy":.8},"genetic_diversity":.3,"infections":{}}
        before=capture_observation({"generation":1},[old],env,[],[])
        dead=dict(old); dead.update({"population":0,"extinct_generation":2,"last_range":[[2,2]],"range":[[2,2]]})
        new={"id":"new","name":"new reed","population":30,"extinct_generation":None,"range":[[4,4]],"genome":{"autotrophy":.8},"genetic_diversity":.4,"infections":{}}
        changes=build_changes(before,{"generation":2},[dead,new],env,[],[],[])
        status={r["id"]:r["status"] for r in changes["lineages"]}
        self.assertEqual(status["old"],"extinct")
        self.assertEqual(status["new"],"new")

    def test_observation_tracks_new_interaction(self):
        env={"width":160,"height":100,"temperature":.5,"moisture":.5,"resources":.7,"scars":[]}
        a={"id":"a","name":"a","population":50,"extinct_generation":None,"range":[[1,1]],"genome":{"autotrophy":.8},"genetic_diversity":.4,"infections":{}}
        b={"id":"b","name":"b","population":20,"extinct_generation":None,"range":[[1,1]],"genome":{"carnivory":.8},"genetic_diversity":.4,"infections":{}}
        before=capture_observation({"generation":3},[a,b],env,[],[])
        pred={"type":"predation","source":"b","target":"a","strength":.2,"contact_cells":1}
        changes=build_changes(before,{"generation":4},[a,b],env,[],[pred],[])
        self.assertEqual(changes["summary"]["new_predation_links"],1)
        self.assertEqual(len(changes["new_interactions"]),1)

    def test_change_report_is_human_readable(self):
        report=format_change_report({"from_generation":2,"to_generation":3,"summary":{"population_before":10,"population_after":12,"population_delta":2,"living_before":1,"living_after":1,"living_delta":0,"occupied_before":2,"occupied_after":3,"occupied_delta":1,"events":1,"new_pathogens":0,"new_predation_links":0},"lineages":[]})
        self.assertIn("GEN 000002 -> 000003",report)
        self.assertIn("population",report)


if __name__=="__main__":
    unittest.main()
