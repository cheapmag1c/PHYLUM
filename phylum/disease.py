from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any

from .constants import MAX_PATHOGENS, PATHOGEN_NOUN, PATHOGEN_PREFIX
from .biology import normalize_range
from .utils import clamp, stable_int


def migrate_pathogen_schema(pathogens: list[dict[str, Any]]) -> None:
    for p in pathogens:
        p.setdefault("hosts", {})
        p.setdefault("reservoirs", [])
        p.setdefault("born_generation", 0)
        p.setdefault("extinct_generation", None)
        p.setdefault("mutation_rate", 0.05)
        p.setdefault("transmissibility", 0.2)
        p.setdefault("virulence", 0.15)
        p.setdefault("host_breadth", 0.2)
        p.setdefault("environmental_persistence", 0.1)


def _pathogen_name(rng: random.Random, used: set[str]) -> str:
    for _ in range(100):
        name=f"{rng.choice(PATHOGEN_PREFIX)} {rng.choice(PATHOGEN_NOUN)}"
        if name not in used:
            return name
    return f"strain-{rng.randrange(1000,9999)}"


def _contact(a: dict[str, Any], b: dict[str, Any]) -> float:
    ra, rb = normalize_range(a), normalize_range(b)
    if not ra or not rb: return 0.0
    overlap=len(ra & rb)
    if overlap: return overlap / max(1,min(len(ra),len(rb)))
    # Border contact.
    rbset=set(rb)
    border=0
    for x,y in ra:
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            if (x+dx,y+dy) in rbset:
                border+=1; break
    return border/max(1,len(ra))*0.35


def maybe_emerge(world: dict[str, Any], species: list[dict[str, Any]], pathogens: list[dict[str, Any]], rng: random.Random) -> list[dict[str, Any]]:
    living=[s for s in species if s.get("extinct_generation") is None and float(s.get("population",0))>25]
    if not living or len([p for p in pathogens if p.get("extinct_generation") is None])>=MAX_PATHOGENS:
        return []
    density=sum(float(s["population"])/max(1,len(normalize_range(s))) for s in living)/len(living)
    chance=0.002 + min(0.012,density/100000)
    if rng.random()>=chance:
        return []
    host=rng.choice(living)
    pid=f"pa-{int(world.get('next_pathogen_id',1)):05d}"
    world["next_pathogen_id"]=int(world.get("next_pathogen_id",1))+1
    used={p.get("name","") for p in pathogens}
    p={
        "id":pid,"name":_pathogen_name(rng,used),"born_generation":int(world["generation"]),"extinct_generation":None,
        "transmissibility":round(rng.uniform(0.10,0.38),4),"virulence":round(rng.uniform(0.04,0.28),4),
        "host_breadth":round(rng.uniform(0.06,0.32),4),"mutation_rate":round(rng.uniform(0.02,0.12),4),
        "environmental_persistence":round(rng.uniform(0.02,0.34),4),"hosts":{host["id"]:round(rng.uniform(0.02,0.08),4)},
        "reservoirs":[host["id"]],"peak_prevalence":0.0,
    }
    pathogens.append(p)
    host.setdefault("infections",{})[pid]=p["hosts"][host["id"]]
    return [{"generation":int(world["generation"]),"kind":"disease","subject":pid,"host":host["id"],"text":f"{p['name']} emerges in {host['name']}."}]


def evolve_diseases(world: dict[str, Any], species: list[dict[str, Any]], pathogens: list[dict[str, Any]], rng: random.Random) -> tuple[dict[str,float], list[dict[str,Any]]]:
    generation=int(world["generation"])
    living={s["id"]:s for s in species if s.get("extinct_generation") is None and float(s.get("population",0))>0}
    events=maybe_emerge(world,species,pathogens,rng)
    mortality=defaultdict(float)
    for p in pathogens:
        if p.get("extinct_generation") is not None: continue
        prng=random.Random(rng.getrandbits(64)^stable_int(p["id"]))
        hosts=dict(p.get("hosts",{}))
        # Seed infections stored on hosts but absent in pathogen state.
        for sid,sp in living.items():
            if p["id"] in sp.get("infections",{}):
                hosts.setdefault(sid,float(sp["infections"][p["id"]]))
        updated={}
        for sid,prev in hosts.items():
            sp=living.get(sid)
            if sp is None: continue
            immune=float(sp.get("genome",{}).get("immune",0.4))
            diversity=float(sp.get("genetic_diversity",0.4))
            density=float(sp["population"])/max(1,len(normalize_range(sp)))
            growth=float(p["transmissibility"])*(0.35+density/70)*(1-immune*0.62)
            recovery=0.05+immune*0.12+diversity*0.03
            new=clamp(float(prev)+(growth-recovery)*float(prev)*(1-float(prev))+prng.gauss(0,0.004),0,0.98)
            if new>0.002:
                updated[sid]=round(new,5)
                sp.setdefault("infections",{})[p["id"]]=round(new,5)
                deaths=float(sp["population"])*new*float(p["virulence"])*(0.018+0.035*(1-immune))
                mortality[sid]+=deaths
                # Selection for resistance is slow and bounded.
                if new>0.18:
                    sp["genome"]["immune"]=round(clamp(immune+prng.uniform(0.0003,0.0025)*new,0,1),5)
            else:
                sp.setdefault("infections",{}).pop(p["id"],None)
        # Spillover into contacted species.
        infectious=[living[sid] for sid,prev in updated.items() if sid in living and prev>0.03]
        for host in infectious:
            for target in living.values():
                if target["id"] in updated or target["id"]==host["id"]: continue
                c=_contact(host,target)
                if c<=0: continue
                genetic_distance=abs(float(host["genome"].get("body_size",1))-float(target["genome"].get("body_size",1)))/12
                spill=float(p["host_breadth"])*(1-genetic_distance)*c*float(p["transmissibility"])
                if prng.random()<spill*0.14:
                    updated[target["id"]]=round(prng.uniform(0.004,0.025),5)
                    target.setdefault("infections",{})[p["id"]]=updated[target["id"]]
                    events.append({"generation":generation,"kind":"disease","subject":p["id"],"host":target["id"],"text":f"{p['name']} spills into {target['name']}."})
        p["hosts"]=updated
        peak=max(updated.values(),default=0.0)
        p["peak_prevalence"]=round(max(float(p.get("peak_prevalence",0)),peak),5)
        # Pathogen evolution.
        if prng.random()<float(p.get("mutation_rate",0.05)):
            p["transmissibility"]=round(clamp(float(p["transmissibility"])+prng.gauss(0,0.008),0.02,0.78),5)
            p["virulence"]=round(clamp(float(p["virulence"])+prng.gauss(0,0.006),0.01,0.72),5)
            p["host_breadth"]=round(clamp(float(p["host_breadth"])+prng.gauss(0,0.006),0.01,0.88),5)
        if not updated:
            # Environmental persistence can keep a pathogen latent for a while.
            if prng.random()>float(p.get("environmental_persistence",0.1)):
                p["extinct_generation"]=generation
                events.append({"generation":generation,"kind":"disease","subject":p["id"],"text":f"{p['name']} disappears from the biosphere."})
        elif peak>0.48 and len(updated)>=max(2,len(living)//2):
            events.append({"generation":generation,"kind":"pandemic","subject":p["id"],"text":f"{p['name']} reaches pandemic spread across {len(updated)} lineages."})
    return dict(mortality),events
