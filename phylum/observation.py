from __future__ import annotations

import math
from typing import Any

from .biology import normalize_range, trophic_role
from .constants import GRID_COLS, GRID_ROWS
from .utils import mean


def _centroid(sp: dict[str, Any], extinct: bool = False) -> tuple[float, float] | None:
    source = sp.get("last_range", []) if extinct else sp.get("range", [])
    cells=[]
    for item in source:
        if isinstance(item,(list,tuple)) and len(item)==2:
            x,y=int(item[0]),int(item[1])
            if 0<=x<GRID_COLS and 0<=y<GRID_ROWS: cells.append((x,y))
    if not cells and not extinct:
        cells=list(normalize_range(sp))
    if not cells: return None
    return round(mean(c[0] for c in cells),3), round(mean(c[1] for c in cells),3)


def _active_pathogen_ids(pathogens: list[dict[str, Any]]) -> set[str]:
    return {str(p.get("id")) for p in pathogens if p.get("id") and p.get("extinct_generation") is None}


def _interaction_key(item: dict[str, Any]) -> str:
    return f"{item.get('type')}:{item.get('source')}:{item.get('target')}"


def capture_observation(
    world: dict[str, Any],
    species: list[dict[str, Any]],
    env: dict[str, Any],
    pathogens: list[dict[str, Any]],
    interactions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compact, deterministic snapshot used only to describe the next generation's delta."""
    rows={}
    for sp in species:
        sid=str(sp.get("id"))
        if not sid: continue
        extinct=sp.get("extinct_generation") is not None
        cells=normalize_range(sp) if not extinct else set()
        infections={str(k):float(v) for k,v in sp.get("infections",{}).items() if float(v)>0}
        rows[sid]={
            "id":sid,
            "name":sp.get("name",sid),
            "population":round(float(sp.get("population",0)),4),
            "range_size":len(cells),
            "centroid":_centroid(sp, extinct=False),
            "extinct":extinct,
            "role":trophic_role(sp),
            "genetic_diversity":round(float(sp.get("genetic_diversity",0)),5),
            "infections":infections,
        }
    live=[x for x in rows.values() if not x["extinct"] and x["population"]>0]
    occupied=len(set().union(*(normalize_range(sp) for sp in species if sp.get("extinct_generation") is None))) if live else 0
    return {
        "generation":int(world.get("generation",0)),
        "population":round(sum(x["population"] for x in live),4),
        "living":len(live),
        "extinct":len(rows)-len(live),
        "occupied_cells":occupied,
        "environment":{
            "temperature":round(float(env.get("temperature",0)),5),
            "moisture":round(float(env.get("moisture",0)),5),
            "resources":round(float(env.get("resources",0)),5),
        },
        "species":rows,
        "active_pathogens":sorted(_active_pathogen_ids(pathogens)),
        "interactions":{_interaction_key(i):dict(i) for i in interactions},
    }


def _event_position(
    event: dict[str, Any],
    species_by_id: dict[str, dict[str, Any]],
    pathogens_by_id: dict[str, dict[str, Any]],
    env: dict[str, Any],
) -> list[float] | None:
    host=event.get("host")
    if host and str(host) in species_by_id:
        c=_centroid(species_by_id[str(host)])
        return list(c) if c else None
    subject=str(event.get("subject", ""))
    if subject in species_by_id:
        sp=species_by_id[subject]
        c=_centroid(sp, extinct=sp.get("extinct_generation") is not None)
        return list(c) if c else None
    if subject in pathogens_by_id:
        p=pathogens_by_id[subject]
        hosts=p.get("hosts",{})
        if hosts:
            sid=max(hosts,key=lambda k:float(hosts[k]))
            sp=species_by_id.get(str(sid))
            if sp:
                c=_centroid(sp)
                return list(c) if c else None
    scar_id=event.get("scar_id")
    if scar_id:
        for scar in reversed(env.get("scars",[])):
            if scar.get("id")==scar_id:
                x=float(scar.get("x",0))/max(1,float(env.get("width",160)))*GRID_COLS
                y=float(scar.get("y",0))/max(1,float(env.get("height",100)))*GRID_ROWS
                return [round(x,3),round(y,3)]
    if event.get("kind")=="mass_extinction":
        gen=int(event.get("generation",-1))
        candidates=[s for s in env.get("scars",[]) if int(s.get("generation",-2))==gen]
        if candidates:
            scar=candidates[-1]
            x=float(scar.get("x",0))/max(1,float(env.get("width",160)))*GRID_COLS
            y=float(scar.get("y",0))/max(1,float(env.get("height",100)))*GRID_ROWS
            return [round(x,3),round(y,3)]
    return None


def _safe_percent(delta: float, before: float) -> float | None:
    if abs(before)<1e-9: return None
    return round(delta/before*100,2)


def build_changes(
    before: dict[str, Any],
    world: dict[str, Any],
    species: list[dict[str, Any]],
    env: dict[str, Any],
    pathogens: list[dict[str, Any]],
    interactions: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    after=capture_observation(world,species,env,pathogens,interactions)
    before_sp=before.get("species",{})
    after_sp=after.get("species",{})
    rows=[]
    all_ids=sorted(set(before_sp)|set(after_sp))
    for sid in all_ids:
        a=before_sp.get(sid)
        b=after_sp.get(sid)
        if a is None and b is not None:
            status="new"
            pop_before=0.0; pop_after=float(b["population"])
            range_before=0; range_after=int(b["range_size"])
            c_from=None; c_to=b.get("centroid")
        elif b is None:
            status="missing"
            pop_before=float(a["population"]); pop_after=0.0
            range_before=int(a["range_size"]); range_after=0
            c_from=a.get("centroid"); c_to=None
        else:
            if not a.get("extinct") and b.get("extinct"): status="extinct"
            elif a.get("extinct") and not b.get("extinct"): status="revived"
            else: status="living" if not b.get("extinct") else "extinct"
            pop_before=float(a["population"]); pop_after=float(b["population"])
            range_before=int(a["range_size"]); range_after=int(b["range_size"])
            c_from=a.get("centroid"); c_to=b.get("centroid")
        pop_delta=round(pop_after-pop_before,2)
        range_delta=range_after-range_before
        movement=0.0
        if c_from and c_to:
            movement=round(math.dist(c_from,c_to),3)
        infections_before=a.get("infections",{}) if a else {}
        infections_after=b.get("infections",{}) if b else {}
        peak_prev_before=max([float(v) for v in infections_before.values()] or [0])
        peak_prev_after=max([float(v) for v in infections_after.values()] or [0])
        rows.append({
            "id":sid,
            "name":(b or a or {}).get("name",sid),
            "status":status,
            "role":(b or a or {}).get("role","unknown"),
            "population_before":round(pop_before,2),
            "population_after":round(pop_after,2),
            "population_delta":pop_delta,
            "population_percent":_safe_percent(pop_delta,pop_before),
            "range_before":range_before,
            "range_after":range_after,
            "range_delta":range_delta,
            "centroid_from":c_from,
            "centroid_to":c_to,
            "movement":movement,
            "genetic_diversity_before":a.get("genetic_diversity") if a else None,
            "genetic_diversity_after":b.get("genetic_diversity") if b else None,
            "infection_peak_before":round(peak_prev_before,5),
            "infection_peak_after":round(peak_prev_after,5),
        })
    before_p=set(before.get("active_pathogens",[])); after_p=set(after.get("active_pathogens",[]))
    before_i=before.get("interactions",{}); after_i=after.get("interactions",{})
    new_keys=set(after_i)-set(before_i); ended_keys=set(before_i)-set(after_i)
    byid={str(s.get("id")):s for s in species}
    pathogen_byid={str(p.get("id")):p for p in pathogens}
    markers=[]
    marker_glyph={
        "migration":"→","speciation":"◇","extinction":"†","disease":"✣","pandemic":"✣",
        "disaster":"!","mass_extinction":"☄","tectonic":"△","climate":"≈","contact":"⇄","era":"◆",
        "tool_use":"⌘","culture":"◎","communication":"∿","learning":"+","behavior":"•",
        "construction":"⌂","artifact":"▣","cultural_exchange":"⇆","knowledge_loss":"×","language":"≋",
    }
    for idx,e in enumerate(events):
        pos=_event_position(e,byid,pathogen_byid,env)
        markers.append({
            "id":f"ev-{int(world.get('generation',0)):06d}-{idx:02d}",
            "kind":str(e.get("kind","event")),
            "subject":e.get("subject"),
            "text":str(e.get("text","")),
            "position":pos,
            "glyph":marker_glyph.get(str(e.get("kind")),"•"),
        })
    pop_delta=round(float(after["population"])-float(before.get("population",0)),2)
    occ_delta=int(after["occupied_cells"])-int(before.get("occupied_cells",0))
    env_before=before.get("environment",{})
    env_after=after.get("environment",{})
    summary={
        "population_before":round(float(before.get("population",0)),2),
        "population_after":round(float(after["population"]),2),
        "population_delta":pop_delta,
        "population_percent":_safe_percent(pop_delta,float(before.get("population",0))),
        "living_before":int(before.get("living",0)),
        "living_after":int(after.get("living",0)),
        "living_delta":int(after.get("living",0))-int(before.get("living",0)),
        "occupied_before":int(before.get("occupied_cells",0)),
        "occupied_after":int(after.get("occupied_cells",0)),
        "occupied_delta":occ_delta,
        "temperature_delta":round(float(env_after.get("temperature",0))-float(env_before.get("temperature",0)),5),
        "moisture_delta":round(float(env_after.get("moisture",0))-float(env_before.get("moisture",0)),5),
        "resources_delta":round(float(env_after.get("resources",0))-float(env_before.get("resources",0)),5),
        "new_pathogens":len(after_p-before_p),
        "resolved_pathogens":len(before_p-after_p),
        "new_predation_links":sum(1 for k in new_keys if k.startswith("predation:")),
        "ended_predation_links":sum(1 for k in ended_keys if k.startswith("predation:")),
        "new_competition_links":sum(1 for k in new_keys if k.startswith("competition:")),
        "events":len(events),
    }
    # Rank by ecological importance for compact reports.
    rows.sort(key=lambda r:(r["status"] not in {"new","extinct"},-abs(float(r["population_delta"])), -abs(int(r["range_delta"])), r["name"]))
    return {
        "schema_version":1,
        "from_generation":int(before.get("generation",max(0,int(world.get("generation",0))-1))),
        "to_generation":int(world.get("generation",0)),
        "summary":summary,
        "lineages":rows,
        "new_pathogens":sorted(after_p-before_p),
        "resolved_pathogens":sorted(before_p-after_p),
        "new_interactions":[after_i[k] for k in sorted(new_keys)],
        "ended_interactions":[before_i[k] for k in sorted(ended_keys)],
        "markers":markers,
        "events":[dict(e) for e in events],
    }


def format_change_report(changes: dict[str, Any]) -> str:
    if not changes:
        return "No generation-delta report exists yet. Evolve PHYLUM once to create one."
    s=changes.get("summary",{})
    sign=lambda n: f"{n:+,}" if isinstance(n,int) else f"{n:+,.2f}"
    lines=[
        f"PHYLUM GEN {int(changes.get('from_generation',0)):06d} -> {int(changes.get('to_generation',0)):06d}",
        f"population {int(s.get('population_before',0)):,} -> {int(s.get('population_after',0)):,} ({sign(float(s.get('population_delta',0)))})",
        f"living lineages {s.get('living_before',0)} -> {s.get('living_after',0)} ({int(s.get('living_delta',0)):+d})",
        f"occupied cells {s.get('occupied_before',0)} -> {s.get('occupied_after',0)} ({int(s.get('occupied_delta',0)):+d})",
        f"events {s.get('events',0)} · new pathogens {s.get('new_pathogens',0)} · new predation links {s.get('new_predation_links',0)}",
    ]
    changed=[r for r in changes.get("lineages",[]) if r.get("status") in {"new","extinct"} or abs(float(r.get("population_delta",0)))>=1 or int(r.get("range_delta",0))!=0]
    for r in changed[:8]:
        lines.append(f"- {r.get('name')}: {r.get('status')} · pop {float(r.get('population_delta',0)):+.0f} · range {int(r.get('range_delta',0)):+d} · move {float(r.get('movement',0)):.2f}")
    return "\n".join(lines)
