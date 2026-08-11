from __future__ import annotations

import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .biology import (
    cell_suitability, migrate_species_schema,
    normalize_range, store_range, territory_target, trophic_role,
)
from .branching import compare_repositories, contact_worlds, ensure_branch
from .constants import CHECKPOINT_INTERVAL, EVENT_PRIORITY, GRID_COLS, GRID_ROWS, SCHEMA_VERSION
from .disease import migrate_pathogen_schema
from .observation import build_changes, capture_observation
from .soma import ensure_soma_schema, finalize_soma_generation, prepare_soma_generation, validate_soma_state
from .paleon import ensure_paleon_state, finalize_paleon_generation, validate_paleon_state
from .nerve import ensure_nerve_schema, finalize_nerve_generation, prepare_nerve_generation, validate_nerve_state
from .techne import ensure_techne_schema, ensure_world_techne, finalize_techne_generation, prepare_techne_generation, validate_techne_state, validate_techne_world
from .socius import ensure_socius_schema, ensure_world_socius, finalize_socius_generation, prepare_socius_generation, validate_socius_state, validate_socius_world
from .vivarium import advance_vivarium, ensure_vivarium_state, load_vivarium_state, reconcile_vivarium_lineages, validate_vivarium_state
from .planet import climate_at, initialize_plates, region_name
from .storage import (
    ATLAS_HISTORY_PATH, BRANCH_PATH, CHANGES_PATH, CHECKPOINT_DIR, ENV_PATH, EVENTS_PATH, HISTORY_PATH, INTERACTIONS_PATH,
    PATHOGENS_PATH, PLATES_PATH, README_PATH, ROOT, SNAPSHOT_DIR, SPECIES_FOSSIL_DIR,
    append_ndjson, atomic_json, backup_state, load_extended, load_json, load_state,
    read_ndjson, save_extended, write_checkpoint,
)
from .utils import clamp, deterministic_rng, fingerprint, mean

__all__ = [
    "GRID_COLS", "GRID_ROWS", "deterministic_rng", "env_at", "suitability",
    "_normalize_range", "_territory_target", "_region_name", "load_state",
    "evolve_one", "commit_message", "migrate_current_state", "validate_state",
]


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_range(sp: dict[str, Any]):
    return normalize_range(sp)


def _territory_target(sp: dict[str, Any]) -> int:
    return territory_target(sp)


def _region_name(cell: tuple[int, int]) -> str:
    return region_name(cell)


def env_at(environment: dict[str, Any], x: float, y: float, seed: int) -> tuple[float, float, float]:
    plates = initialize_plates(seed, environment)
    return climate_at(environment, plates, x, y, seed)


def suitability(sp: dict[str, Any], local: tuple[float, float, float]) -> float:
    t,m,r=local
    traits=sp.get("genome",sp.get("traits",{}))
    td=abs(t-float(traits.get("temp_pref",0.5))); md=abs(m-float(traits.get("moisture_pref",0.5))); tol=max(0.08,float(traits.get("tolerance",0.28)))
    fit=max(0.0,1-(td+md)/(tol*2.25))
    return clamp(fit*0.7+min(r,1.0)*0.3,0,1)


def _event(generation: int, kind: str, subject: str, text: str, **extra: Any) -> dict[str, Any]:
    e={"generation":generation,"kind":kind,"subject":subject,"text":text}; e.update(extra); return e


def _ensure_world_defaults(world: dict[str, Any]) -> None:
    world.setdefault("name","PHYLUM")
    world.setdefault("generation",0)
    world.setdefault("seed",314159265)
    world.setdefault("created_utc",now_utc())
    world.setdefault("root_lineage","PHYLUM/origin")
    world.setdefault("active_lineage","local/PHYLUM")
    world.setdefault("next_species_id",1)
    world.setdefault("next_pathogen_id",1)
    world.setdefault("era",{"index":1,"name":"Origin Era","started_generation":0})
    world.setdefault("clocks",{"ecology":int(world["generation"]),"evolution":0.0,"climate":0.0,"geology":0.0})
    world.setdefault("detritus",0.0)
    world.setdefault("statistics",{})
    world["schema_version"]=SCHEMA_VERSION


def _ensure_environment(env: dict[str, Any], species: list[dict[str, Any]]) -> None:
    env.setdefault("width",160); env.setdefault("height",100); env.setdefault("temperature",0.55); env.setdefault("moisture",0.53); env.setdefault("resources",0.69); env.setdefault("scars",[]); env.setdefault("season_phase",0.0)
    if "ancestral_refugia" not in env:
        refugia=[]
        for sp in species[:12]:
            refugia.append({"species_id":sp.get("id"),"x":round(float(sp.get("x",80)),3),"y":round(float(sp.get("y",50)),3),"radius":13})
        env["ancestral_refugia"]=refugia


def _ensure_ranges(species: list[dict[str, Any]], env: dict[str, Any]) -> None:
    for sp in species:
        if sp.get("extinct_generation") is not None:
            continue
        cells=normalize_range(sp)
        if not cells:
            gx=int(clamp(float(sp.get("x",80))/float(env["width"])*GRID_COLS,0,GRID_COLS-1)); gy=int(clamp(float(sp.get("y",50))/float(env["height"])*GRID_ROWS,0,GRID_ROWS-1))
            cells={(gx,gy)}; store_range(sp,cells)


def ensure_schema(lineage: str | None = None, save: bool = False) -> tuple[dict[str,Any],list[dict[str,Any]],dict[str,Any],list[dict[str,Any]],dict[str,Any],dict[str,Any],list[dict[str,Any]]]:
    world,species,env,pathogens,plates,branch,interactions=load_extended()
    _ensure_world_defaults(world); _ensure_environment(env,species); _ensure_ranges(species,env)
    seed=int(world["seed"])
    for sp in species: migrate_species_schema(sp,seed,int(world["generation"]))
    species_by_id={str(s.get("id")):s for s in species if s.get("id")}
    for sp in species: ensure_soma_schema(sp,seed,int(world["generation"]),species_by_id)
    for sp in species: ensure_nerve_schema(sp,seed,int(world["generation"]),species_by_id)
    ensure_world_techne(world)
    for sp in species: ensure_techne_schema(sp,seed,int(world["generation"]),species_by_id)
    ensure_world_socius(world)
    for sp in species: ensure_socius_schema(sp,seed,int(world["generation"]),species_by_id)
    migrate_pathogen_schema(pathogens)
    if not plates or not plates.get("plates"): plates=initialize_plates(seed,env)
    ensure_paleon_state(world,env,plates,species)
    # VIVARIUM is the living substrate. Existing worlds are migrated into explicit
    # organisms + bounded cohorts without consuming simulation time.
    ensure_vivarium_state(world,species,env,plates,save=save)
    lineage=lineage or os.getenv("GITHUB_REPOSITORY") or world.get("active_lineage") or "local/PHYLUM"
    ensure_branch(world,branch,lineage)
    world["next_species_id"]=max(int(world.get("next_species_id",1)),max([int(str(s.get("id","sp-0")).split("-")[-1]) for s in species if str(s.get("id","")).startswith("sp-")] or [0])+1)
    world["next_pathogen_id"]=max(int(world.get("next_pathogen_id",1)),max([int(str(p.get("id","pa-0")).split("-")[-1]) for p in pathogens if str(p.get("id","")).startswith("pa-")] or [0])+1)
    _update_statistics(world,species,pathogens,interactions)
    if save: save_extended(world,species,env,pathogens,plates,branch,interactions)
    return world,species,env,pathogens,plates,branch,interactions


def _update_statistics(world: dict[str,Any], species: list[dict[str,Any]], pathogens: list[dict[str,Any]], interactions: list[dict[str,Any]]) -> None:
    live=[s for s in species if s.get("extinct_generation") is None and float(s.get("population",0))>0]; dead=[s for s in species if s.get("extinct_generation") is not None]
    total=sum(float(s.get("population",0)) for s in live); occupied=len(set().union(*(normalize_range(s) for s in live))) if live else 0
    world["living_species"]=len(live); world["extinct_species"]=len(dead); world["total_population"]=round(total,2); world["occupied_cells"]=occupied
    st=world.setdefault("statistics",{})
    st["species_ever"]=len(species); st["pathogens_ever"]=len(pathogens); st["active_pathogens"]=sum(p.get("extinct_generation") is None for p in pathogens)
    st["predator_prey_links"]=sum(i.get("type")=="predation" for i in interactions); st["competition_links"]=sum(i.get("type")=="competition" for i in interactions)
    st["oldest_living_lineage"]=min(live,key=lambda s:int(s.get("born_generation",0))).get("name") if live else None
    st["largest_population_ever"]=round(max([float(s.get("peak_population",0)) for s in species] or [0]),2)
    st["largest_range_ever"]=max([int(s.get("peak_range",0)) for s in species] or [0])
    st["most_descendants"]=max(species,key=lambda s:len(s.get("offspring_lineages",[]))).get("name") if species else None


def _maybe_era(world: dict[str,Any], events: list[dict[str,Any]], rng: random.Random) -> None:
    if not events: return
    current=world.setdefault("era",{"index":1,"name":"Origin Era","started_generation":0})
    gen=int(world["generation"])
    if gen-int(current.get("started_generation",0))<10: return
    kinds={e.get("kind") for e in events}
    cause=None
    if "mass_extinction" in kinds: cause="Ash Age"
    elif "contact" in kinds: cause="Contact Age"
    elif sum(1 for e in events if e.get("kind")=="speciation")>=2: cause="Radiant Age"
    elif "tectonic" in kinds and rng.random()<0.35: cause="Rift Interval"
    elif "pandemic" in kinds and rng.random()<0.45: cause="Pale Interval"
    if cause:
        idx=int(current.get("index",1))+1; name=f"{cause} {idx-1}" if idx>2 else cause
        world["era"]={"index":idx,"name":name,"started_generation":gen,"cause":cause}
        events.append(_event(gen,"era","world",f"The {name} begins."))


def _write_fossils(species: list[dict[str,Any]], generation: int) -> None:
    SPECIES_FOSSIL_DIR.mkdir(parents=True,exist_ok=True)
    for sp in species:
        if sp.get("extinct_generation")!=generation: continue
        path=SPECIES_FOSSIL_DIR/f"{sp['id']}-{str(sp.get('name','lineage')).replace(' ','-')}.json"
        if not path.exists(): atomic_json(path,sp)


def _history_summary(world: dict[str,Any], species: list[dict[str,Any]], env: dict[str,Any], pathogens: list[dict[str,Any]], interactions: list[dict[str,Any]], events: list[dict[str,Any]]) -> dict[str,Any]:
    live=[s for s in species if s.get("extinct_generation") is None]
    return {"generation":int(world["generation"]),"era":world.get("era",{}).get("name"),"living":len(live),"extinct":sum(s.get("extinct_generation") is not None for s in species),"population":round(sum(float(s.get("population",0)) for s in live),2),"occupied_cells":len(set().union(*(normalize_range(s) for s in live))) if live else 0,"temperature":env.get("temperature"),"moisture":env.get("moisture"),"resources":env.get("resources"),"pathogens":sum(p.get("extinct_generation") is None for p in pathogens),"predation_links":sum(i.get("type")=="predation" for i in interactions),"events":[e.get("kind") for e in events]}


def validate_state(world: dict[str,Any], species: list[dict[str,Any]], env: dict[str,Any], pathogens: list[dict[str,Any]], plates: dict[str,Any], branch: dict[str,Any], interactions: list[dict[str,Any]]) -> list[str]:
    errors=[]
    if int(world.get("schema_version",0))!=SCHEMA_VERSION: errors.append("schema_version mismatch")
    ids=[s.get("id") for s in species]
    if len(ids)!=len(set(ids)): errors.append("duplicate species ids")
    if not 0<=float(env.get("temperature",0.5))<=1: errors.append("temperature out of bounds")
    if not 0<=float(env.get("moisture",0.5))<=1: errors.append("moisture out of bounds")
    if not plates.get("plates"): errors.append("no tectonic plates")
    errors.extend(validate_paleon_state(world,env,plates))
    errors.extend(validate_techne_world(world))
    errors.extend(validate_socius_world(world))
    if world.get("engine") == "VIVARIUM": errors.extend(validate_vivarium_state(world,species))
    for sp in species:
        pop=float(sp.get("population",0))
        if pop<0 or pop>1e10: errors.append(f"invalid population {sp.get('id')}")
        for x,y in normalize_range(sp):
            if not(0<=x<GRID_COLS and 0<=y<GRID_ROWS): errors.append(f"bad range {sp.get('id')}")
        if sp.get("extinct_generation") is None and not sp.get("genome"): errors.append(f"missing genome {sp.get('id')}")
        errors.extend(validate_soma_state(sp))
        errors.extend(validate_nerve_state(sp))
        errors.extend(validate_techne_state(sp))
        errors.extend(validate_socius_state(sp))
    pids=[p.get("id") for p in pathogens]
    if len(pids)!=len(set(pids)): errors.append("duplicate pathogen ids")
    if not branch.get("root_fingerprint"): errors.append("missing branch root fingerprint")
    return errors


def _snapshot_if_major(world: dict[str,Any], species: list[dict[str,Any]], env: dict[str,Any], pathogens: list[dict[str,Any]], events: list[dict[str,Any]]) -> None:
    major=any(EVENT_PRIORITY.get(str(e.get("kind")),0)>=90 for e in events)
    if not major: return
    SNAPSHOT_DIR.mkdir(parents=True,exist_ok=True)
    atomic_json(SNAPSHOT_DIR/f"gen-{int(world['generation']):06d}.json",{"world":world,"environment":env,"species":species,"pathogens":pathogens,"events":events})



def _atlas_snapshot(world: dict[str,Any], species: list[dict[str,Any]], env: dict[str,Any], plates: dict[str,Any]) -> dict[str,Any]:
    return {
        "generation": int(world.get("generation",0)),
        "era": world.get("era",{}).get("name"),
        "environment": {k: env.get(k) for k in ("temperature","moisture","resources")},
        "species": [
            {"id":s.get("id"),"name":s.get("name"),"population":round(float(s.get("population",0)),2),"extinct":s.get("extinct_generation") is not None,"range":s.get("range",[]) if s.get("extinct_generation") is None else s.get("last_range",[])}
            for s in species
        ],
        "plates": [{"id":p.get("id"),"cx":p.get("cx"),"cy":p.get("cy")} for p in plates.get("plates",[])],
        "scars": env.get("scars",[])[-12:],
    }

def _append_atlas_snapshot_if_needed(world: dict[str,Any], species: list[dict[str,Any]], env: dict[str,Any], plates: dict[str,Any], events: list[dict[str,Any]] | None = None, force: bool=False) -> None:
    gen=int(world.get("generation",0)); major=any(EVENT_PRIORITY.get(str(e.get("kind")),0)>=90 for e in (events or []))
    existing=read_ndjson(ATLAS_HISTORY_PATH,1)
    already=bool(existing and int(existing[-1].get("generation",-1))==gen)
    if already: return
    if force or gen % 25 == 0 or major:
        append_ndjson(ATLAS_HISTORY_PATH,[_atlas_snapshot(world,species,env,plates)])

def migrate_current_state(lineage: str | None = None, render: bool = True) -> dict[str,Any]:
    state=ensure_schema(lineage,save=False)
    world,species,env,pathogens,plates,branch,interactions=state
    ensure_vivarium_state(world,species,env,plates,save=True)
    errors=validate_state(*state)
    if errors: raise ValueError("PHYLUM migration validation failed: "+"; ".join(errors))
    save_extended(*state)
    _append_atlas_snapshot_if_needed(world,species,env,plates,force=True)
    if render:
        from .render import render_all
        render_all(*state)
    return {"world":world,"species":species,"environment":env,"pathogens":pathogens,"plates":plates,"branch":branch,"interactions":interactions}


def evolve_one(lineage: str | None = None) -> dict[str,Any]:
    world,species,env,pathogens,plates,branch,interactions=ensure_schema(lineage,save=False)
    before_observation=capture_observation(world,species,env,pathogens,interactions)
    backup_state(f"world-{int(world.get('generation',0)):06d}")
    # `generation` remains as a compatibility observation index for the fossil
    # record and render stack. VIVARIUM advances continuous simulated days.
    world["generation"]=int(world.get("generation",0))+1; generation=int(world["generation"])
    lineage=lineage or os.getenv("GITHUB_REPOSITORY") or branch.get("lineage") or world.get("active_lineage") or "local/PHYLUM"
    ensure_branch(world,branch,lineage)
    rng=deterministic_rng(int(world["seed"]),generation,lineage,"vivarium-checkpoint")
    events=[]
    from .planet import evolve_planet
    vstate,_,_,_=load_vivarium_state(); start_day=float(vstate.get("sim_day",0)); span=float(vstate.get("checkpoint_days",14)); end_day=start_day+span
    # PALEON now follows the actual VIVARIUM clock. Daily weather belongs to the
    # living engine; the deep planetary model ticks when a simulated year boundary
    # is crossed instead of once per Git commit.
    planet_tick=int(start_day//360)!=int(end_day//360)
    culture_tick=int(start_day//90)!=int(end_day//90)
    if planet_tick:
        events.extend(evolve_planet(world,env,plates,random.Random(rng.getrandbits(64))))
    events.extend(prepare_soma_generation(world,species,env,interactions,random.Random(rng.getrandbits(64))))
    events.extend(prepare_nerve_generation(world,species,env,interactions,random.Random(rng.getrandbits(64))))
    events.extend(prepare_techne_generation(world,species,env,interactions,random.Random(rng.getrandbits(64))))
    events.extend(prepare_socius_generation(world,species,env,interactions,random.Random(rng.getrandbits(64))))
    interactions,viv_events=advance_vivarium(world,species,env,pathogens,plates,interactions,random.Random(rng.getrandbits(64))); events.extend(viv_events)
    events.extend(finalize_soma_generation(world,species,env,interactions,random.Random(rng.getrandbits(64))))
    if planet_tick:
        events.extend(finalize_paleon_generation(world,species,env,plates,interactions,random.Random(rng.getrandbits(64))))
    # Cultural/social macrostate is sampled seasonally. Individual NERVE memory and
    # peer-to-peer cultural copying still happen every simulated day in VIVARIUM.
    if culture_tick:
        events.extend(finalize_nerve_generation(world,species,env,interactions,random.Random(rng.getrandbits(64))))
        events.extend(finalize_techne_generation(world,species,env,interactions,random.Random(rng.getrandbits(64))))
        events.extend(finalize_socius_generation(world,species,env,interactions,random.Random(rng.getrandbits(64))))
    _maybe_era(world,events,random.Random(rng.getrandbits(64)))
    world["last_evolved_utc"]=now_utc()
    _update_statistics(world,species,pathogens,interactions)
    if not events:
        vd=world.get("vivarium",{}); days=int(vd.get("checkpoint_days",0)); sy=float(vd.get("sim_year",0))
        events=[_event(generation,"observation","world",f"VIVARIUM advances {days} simulated days to year {sy:.2f}.")]
    events.sort(key=lambda e:(-EVENT_PRIORITY.get(str(e.get("kind")),0),str(e.get("subject","")),str(e.get("text",""))))
    _write_fossils(species,generation); _snapshot_if_major(world,species,env,pathogens,events)
    errors=validate_state(world,species,env,pathogens,plates,branch,interactions)
    if errors: raise ValueError("PHYLUM VIVARIUM checkpoint validation failed: "+"; ".join(errors))
    save_extended(world,species,env,pathogens,plates,branch,interactions)
    changes=build_changes(before_observation,world,species,env,pathogens,interactions,events)
    atomic_json(CHANGES_PATH,changes)
    append_ndjson(EVENTS_PATH,events)
    summary=_history_summary(world,species,env,pathogens,interactions,events); summary["sim_day"]=world.get("vivarium",{}).get("sim_day"); summary["sim_year"]=world.get("vivarium",{}).get("sim_year"); append_ndjson(HISTORY_PATH,[summary])
    _append_atlas_snapshot_if_needed(world,species,env,plates,events)
    if generation%CHECKPOINT_INTERVAL==0:
        write_checkpoint(generation,{"world":world,"environment":env,"branch":branch,"species":species,"pathogens":pathogens})
    if os.getenv("PHYLUM_NO_RENDER") != "1":
        from .render import render_all
        render_all(world,species,env,pathogens,plates,branch,interactions)
    return {"world":world,"species":species,"environment":env,"pathogens":pathogens,"plates":plates,"branch":branch,"interactions":interactions,"events":events,"changes":changes}

def commit_message() -> str:
    world=load_json(ROOT/"world"/"current.json",{}) or {}; gen=int(world.get("generation",0)); rows=read_ndjson(EVENTS_PATH,80)
    current=[e for e in rows if int(e.get("generation",-1))==gen]
    prefix="world" if world.get("engine")=="VIVARIUM" else "gen"
    if not current: return f"{prefix} {gen:06d} — biosphere advances"
    best=max(current,key=lambda e:EVENT_PRIORITY.get(str(e.get("kind")),0)); text=str(best.get("text","biosphere advances")).strip().rstrip(".")
    if len(text)>72: text=text[:69].rstrip()+"…"
    return f"{prefix} {gen:06d} — {text}"


def compare(other_repo: str | Path) -> dict[str,Any]:
    return compare_repositories(ROOT,Path(other_repo).resolve())


def contact(other_repo: str | Path) -> list[dict[str,Any]]:
    world,species,env,pathogens,plates,branch,interactions=ensure_schema(save=False)
    events=contact_worlds(world,species,pathogens,branch,Path(other_repo).resolve())
    if not events: return []
    # SOMA contact backfill: foreign founders receive organismal state before validation.
    species_by_id={str(s.get("id")):s for s in species if s.get("id")}
    for sp in species: ensure_soma_schema(sp,int(world.get("seed",0)),int(world.get("generation",0)),species_by_id)
    # NERVE contact backfill: foreign founders receive cognitive state before validation.
    for sp in species: ensure_nerve_schema(sp,int(world.get("seed",0)),int(world.get("generation",0)),species_by_id)
    # TECHNE contact backfill: foreign founders receive cultural-capacity state without inventing innovations.
    ensure_world_techne(world)
    for sp in species: ensure_techne_schema(sp,int(world.get("seed",0)),int(world.get("generation",0)),species_by_id)
    # SOCIUS contact backfill: foreign founders receive social capacity but no invented group history.
    ensure_world_socius(world)
    for sp in species: ensure_socius_schema(sp,int(world.get("seed",0)),int(world.get("generation",0)),species_by_id)
    # Contact introduces aggregate founder records. VIVARIUM materializes those
    # newcomers as actual organisms/cohorts before population invariants run.
    reconcile_vivarium_lineages(world,species,env,plates,save=True)
    _update_statistics(world,species,pathogens,interactions)
    errors=validate_state(world,species,env,pathogens,plates,branch,interactions)
    if errors: raise ValueError("Contact validation failed: "+"; ".join(errors))
    save_extended(world,species,env,pathogens,plates,branch,interactions); append_ndjson(EVENTS_PATH,events)
    from .render import render_all
    render_all(world,species,env,pathogens,plates,branch,interactions)
    return events
