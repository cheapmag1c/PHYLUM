from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .biology import normalize_range, store_range
from .constants import GRID_COLS, GRID_ROWS
from .storage import load_json
from .utils import clamp, fingerprint, stable_int


def ensure_branch(world: dict[str, Any], branch: dict[str, Any], lineage: str) -> dict[str, Any]:
    root = fingerprint({"seed": world.get("seed"), "created_utc": world.get("created_utc"), "root_lineage": world.get("root_lineage", "PHYLUM/origin")})[:20]
    if not branch:
        branch.update({
            "schema_version": 2,
            "lineage": world.get("active_lineage") or lineage,
            "root_fingerprint": root,
            "parent_lineage": None,
            "diverged_generation": None,
            "ancestor_fingerprint": root,
            "contacts": [],
        })
    branch.setdefault("root_fingerprint", root)
    branch.setdefault("contacts", [])
    old = branch.get("lineage") or world.get("active_lineage")
    if lineage and old and lineage != old:
        branch["parent_lineage"] = old
        branch["diverged_generation"] = int(world.get("generation", 0))
        branch["ancestor_fingerprint"] = fingerprint({"root": branch["root_fingerprint"], "generation": world.get("generation"), "species": [(s, ) for s in []]})[:20]
        branch["lineage"] = lineage
    elif lineage:
        branch["lineage"] = lineage
    world["active_lineage"] = branch.get("lineage", lineage)
    return branch


def _repo_state(repo: Path) -> dict[str, Any]:
    world = load_json(repo / "world" / "current.json", {}) or {}
    species = load_json(repo / "world" / "species.json", []) or []
    branch = load_json(repo / "world" / "branch.json", {}) or {}
    pathogens = load_json(repo / "world" / "pathogens.json", []) or []
    return {"world": world, "species": species, "branch": branch, "pathogens": pathogens}


def compare_repositories(a: Path, b: Path) -> dict[str, Any]:
    A, B = _repo_state(a), _repo_state(b)
    aw, bw = A["world"], B["world"]
    abr, bbr = A["branch"], B["branch"]
    same_root = bool(abr.get("root_fingerprint") and abr.get("root_fingerprint") == bbr.get("root_fingerprint"))
    alive_a = {s.get("name"): s for s in A["species"] if s.get("extinct_generation") is None}
    alive_b = {s.get("name"): s for s in B["species"] if s.get("extinct_generation") is None}
    shared = sorted(set(alive_a) & set(alive_b))
    only_a = sorted(set(alive_a) - set(alive_b))
    only_b = sorted(set(alive_b) - set(alive_a))
    # Approximate evolutionary distance from shared names/genomes and global state.
    genome_diffs = []
    for name in shared:
        ga, gb = alive_a[name].get("genome", {}), alive_b[name].get("genome", {})
        keys = set(ga) & set(gb)
        if keys:
            genome_diffs.append(sum(abs(float(ga[k])-float(gb[k])) for k in keys if isinstance(ga[k], (int,float)) and isinstance(gb[k], (int,float))) / max(1,len(keys)))
    distance = clamp((sum(genome_diffs)/max(1,len(genome_diffs))) + 0.025*(len(only_a)+len(only_b)) + 0.0002*abs(int(aw.get("generation",0))-int(bw.get("generation",0))), 0, 1)
    return {
        "same_root": same_root,
        "lineage_a": abr.get("lineage", aw.get("active_lineage")),
        "lineage_b": bbr.get("lineage", bw.get("active_lineage")),
        "generation_a": aw.get("generation", 0),
        "generation_b": bw.get("generation", 0),
        "shared_living_lineages": shared,
        "unique_to_a": only_a,
        "unique_to_b": only_b,
        "living_a": len(alive_a), "living_b": len(alive_b),
        "population_a": round(float(aw.get("total_population",0)),2), "population_b": round(float(bw.get("total_population",0)),2),
        "evolutionary_distance": round(distance, 5),
        "root_fingerprint": abr.get("root_fingerprint") if same_root else None,
    }


def contact_worlds(
    world: dict[str, Any], species: list[dict[str, Any]], pathogens: list[dict[str, Any]], branch: dict[str, Any], other_repo: Path,
) -> list[dict[str, Any]]:
    """Resolve an independently evolved branch encounter as a biological contact event.

    This is intentionally not an automatic Git merge driver. It is a deterministic biological
    rule users invoke while resolving a Git merge: foreign living lineages enter as low-density
    founder populations, pathogen pools are exchanged, and ancestry/source IDs are preserved.
    """
    other = _repo_state(other_repo)
    obr = other["branch"]
    if branch.get("root_fingerprint") and obr.get("root_fingerprint") and branch["root_fingerprint"] != obr["root_fingerprint"]:
        raise ValueError("The two PHYLUM worlds do not share the same root fingerprint; contact is refused.")
    source_lineage = obr.get("lineage", other["world"].get("active_lineage", "foreign/unknown"))
    if source_lineage == branch.get("lineage"):
        raise ValueError("The other repository identifies as the same PHYLUM lineage.")
    contact_id = f"contact-{int(world.get('generation',0)):06d}-{stable_int(source_lineage)%10000:04d}"
    if any(c.get("id") == contact_id for c in branch.get("contacts", [])):
        return []
    living_foreign = [s for s in other["species"] if s.get("extinct_generation") is None and float(s.get("population",0))>0]
    local_names = {s.get("name") for s in species}
    local_ids = {s.get("id") for s in species}
    next_id = int(world.get("next_species_id", 1))
    introduced = 0
    for fs in living_foreign:
        # Shared unchanged ancestral species are not duplicated unless their genomes clearly diverged.
        candidates = [s for s in species if s.get("name") == fs.get("name") and s.get("extinct_generation") is None]
        if candidates:
            lg = candidates[0].get("genome", {}); fg = fs.get("genome", {})
            keys = set(lg) & set(fg)
            div = sum(abs(float(lg[k])-float(fg[k])) for k in keys if isinstance(lg[k],(int,float)) and isinstance(fg[k],(int,float))) / max(1,len(keys))
            if div < 0.035:
                continue
        ns = json.loads(json.dumps(fs))
        ns["source_species_id"] = fs.get("id")
        ns["native_lineage"] = source_lineage
        ns["contact_origin"] = contact_id
        ns["id"] = f"sp-{next_id:05d}"; next_id += 1
        base_name = str(ns.get("name","foreign lineage"))
        name = base_name
        if name in local_names:
            name = f"{base_name} [{str(source_lineage).split('/')[-1]}]"
        ns["name"] = name; local_names.add(name)
        ns["born_generation"] = int(world.get("generation",0))
        ns["parent_id"] = None
        ns["population"] = round(max(18.0, min(float(fs.get("population",0))*0.08, 120.0)),2)
        # Founder population enters near the eastern or western frontier, preserving range shape loosely.
        old_cells = normalize_range(fs)
        if old_cells:
            minx=min(x for x,_ in old_cells); miny=min(y for _,y in old_cells)
            dx = (GRID_COLS-5-minx) if stable_int(source_lineage)%2 else (3-minx)
            dy = int(GRID_ROWS/2-miny)
            new_cells={(int(clamp(x+dx,0,GRID_COLS-1)),int(clamp(y+dy,0,GRID_ROWS-1))) for x,y in old_cells}
            store_range(ns,new_cells)
        ns["migration_trail"] = []
        ns["regions_seen"] = []
        ns["infections"] = {}
        species.append(ns); introduced += 1
    world["next_species_id"] = next_id
    # Exchange viable pathogens as low-prevalence introductions.
    local_pids={p.get("name") for p in pathogens}
    next_pid=int(world.get("next_pathogen_id",1))
    transferred=0
    for fp in other["pathogens"]:
        if fp.get("extinct_generation") is not None or fp.get("name") in local_pids:
            continue
        np=json.loads(json.dumps(fp)); np["source_pathogen_id"]=fp.get("id"); np["id"]=f"pa-{next_pid:05d}"; next_pid+=1; np["born_generation"]=int(world.get("generation",0)); np["hosts"]={}; np["reservoirs"]=[]; np["extinct_generation"]=None
        pathogens.append(np); local_pids.add(np.get("name")); transferred+=1
    world["next_pathogen_id"] = next_pid
    record={"id":contact_id,"generation":int(world.get("generation",0)),"with":source_lineage,"introduced_lineages":introduced,"pathogens_transferred":transferred}
    branch.setdefault("contacts",[]).append(record)
    world["last_contact"] = record
    return [{"generation":int(world.get("generation",0)),"kind":"contact","subject":"world","text":f"Contact with {source_lineage} introduces {introduced} foreign lineages and {transferred} pathogen strains.",**record}]
