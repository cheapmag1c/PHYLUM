from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import commit_message, compare, contact, evolve_one, load_state, migrate_current_state
from .observation import format_change_report
from .soma import soma_catalog
from .paleon import paleon_summary
from .nerve import nerve_catalog
from .techne import techne_catalog
from .socius import socius_catalog
from .vivarium import vivarium_summary, load_vivarium_state
from .cortex import population_summary as cortex_population_summary, local_llm_status, probe_local_llm
from .storage import CHANGES_PATH, load_extended, load_json


def main() -> None:
    parser=argparse.ArgumentParser(prog="phylum",description="A living world whose fossil record is Git history.")
    sub=parser.add_subparsers(dest="command",required=True)
    e=sub.add_parser("evolve",help="Advance the biosphere"); e.add_argument("--steps",type=int,default=1); e.add_argument("--lineage",default=None)
    sub.add_parser("status",help="Print current state")
    sub.add_parser("commit-message",help="Print the canonical generation commit message")
    sub.add_parser("changes",help="Print what changed in the most recent generation")
    sub.add_parser("soma",help="Print organism-level SOMA profiles for living lineages")
    sub.add_parser("paleon",help="Print DEEP TIME 2.0 planetary-system state")
    sub.add_parser("nerve",help="Print NERVE cognition, memory, behavior and culture profiles")
    sub.add_parser("techne",help="Print TECHNE cultural inheritance, practices and archaeology")
    sub.add_parser("socius",help="Print SOCIUS persistent groups, norms and social relationships")
    sub.add_parser("vivarium",help="Print VIVARIUM continuous-time engine state")
    cx=sub.add_parser("cortex",help="Print CORTEX evolving neural-controller state"); cx.add_argument("--probe-llm",action="store_true",help="Manually probe an optional local OpenAI-compatible LLM endpoint")
    m=sub.add_parser("migrate",help="Upgrade the current world schema without advancing a generation"); m.add_argument("--lineage",default=None)
    c=sub.add_parser("compare",help="Compare this PHYLUM timeline with another checkout"); c.add_argument("other_repo")
    ct=sub.add_parser("contact",help="Resolve a branch encounter as a biological contact event"); ct.add_argument("other_repo")
    args=parser.parse_args()
    if args.command=="evolve":
        result=None
        for _ in range(max(1,args.steps)): result=evolve_one(args.lineage)
        w=result["world"]; vd=w.get('vivarium',{}); print(f"PHYLUM world {w['generation']} · year {float(vd.get('sim_year',0)):.2f} · {w['living_species']} living lineages · {int(w['total_population'])} organisms")
        for ev in result["events"]: print(f"- {ev['text']}")
    elif args.command=="status":
        w,s,e,p,plates,b,i=load_extended(); live=sorted((x for x in s if x.get("extinct_generation") is None),key=lambda x:x.get("population",0),reverse=True)
        print(json.dumps({"generation":w.get("generation"),"era":w.get("era",{}).get("name"),"lineage":b.get("lineage",w.get("active_lineage")),"living_species":len(live),"extinct_species":sum(x.get("extinct_generation") is not None for x in s),"population":int(sum(float(x.get("population",0)) for x in live)),"dominant":live[0].get("name") if live else None,"active_pathogens":sum(x.get("extinct_generation") is None for x in p),"plates":len(plates.get("plates",[])),"predator_prey_links":sum(x.get("type")=="predation" for x in i)},indent=2))
    elif args.command=="commit-message": print(commit_message())
    elif args.command=="changes": print(format_change_report(load_json(CHANGES_PATH,{}) or {}))
    elif args.command=="soma":
        w,s,e,p,plates,b,i=load_extended(); live=[x for x in soma_catalog(s) if x.get("extinct_generation") is None]; print(json.dumps({"generation":w.get("generation"),"lineages":live},indent=2))
    elif args.command=="paleon":
        w,s,e,p,plates,b,i=load_extended(); print(json.dumps(paleon_summary(w,e,plates),indent=2))
    elif args.command=="nerve":
        w,s,e,p,plates,b,i=load_extended(); live=[x for x in nerve_catalog(s) if x.get("extinct_generation") is None]; print(json.dumps({"generation":w.get("generation"),"lineages":live},indent=2))
    elif args.command=="techne":
        w,s,e,p,plates,b,i=load_extended(); print(json.dumps(techne_catalog(w,s),indent=2))
    elif args.command=="socius":
        w,s,e,p,plates,b,i=load_extended(); print(json.dumps(socius_catalog(w,s),indent=2))
    elif args.command=="vivarium":
        w,s,e,p,plates,b,i=load_extended(); print(json.dumps(vivarium_summary(w,s),indent=2))
    elif args.command=="cortex":
        w,s,e,p,plates,b,i=load_extended(); state,agents,cohorts,eco=load_vivarium_state(); report={"observation":w.get("generation"),"sim_day":state.get("sim_day"),"cortex":cortex_population_summary(agents,cohorts),"local_llm":local_llm_status()}
        if args.probe_llm: report["llm_probe"]=probe_local_llm()
        print(json.dumps(report,indent=2))
    elif args.command=="migrate":
        result=migrate_current_state(args.lineage,True); print(f"Migrated PHYLUM generation {result['world']['generation']} to schema {result['world']['schema_version']} without advancing time.")
    elif args.command=="compare": print(json.dumps(compare(args.other_repo),indent=2))
    elif args.command=="contact":
        events=contact(args.other_repo); print("\n".join(e["text"] for e in events) if events else "No new contact event was required.")

if __name__=="__main__": main()
