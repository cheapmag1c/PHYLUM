from __future__ import annotations

import colorsys
import html
import json
import math
import shutil
from pathlib import Path
from typing import Any

from .biology import behavior_profile, morphology, normalize_range, trophic_role
from .constants import BIOME_LABELS, GRID_COLS, GRID_ROWS, MAP_SAMPLE_COLS, MAP_SAMPLE_ROWS
from .planet import biome_at, cell_world_xy, climate_at, geography_at, plate_at
from .storage import ATLAS_HISTORY_PATH, CHANGES_PATH, DOCS_DIR, EVENTS_PATH, HISTORY_PATH, README_PATH, RENDER_DIR, load_json, read_ndjson
from .soma import render_soma_assets
from .utils import clamp, mean, stable_int

WORLD_SVG = RENDER_DIR / "current.svg"
PHYLO_SVG = RENDER_DIR / "phylogeny.svg"
FOODWEB_SVG = RENDER_DIR / "foodweb.svg"


def _esc(v: Any) -> str:
    return html.escape(str(v), quote=True)


def _species_color(sp: dict[str, Any]) -> tuple[str, str, str]:
    h = (stable_int(sp.get("id", sp.get("name", "x"))) % 360) / 360.0
    r,g,b = colorsys.hls_to_rgb(h, 0.61, 0.62)
    base=f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
    r2,g2,b2 = colorsys.hls_to_rgb(h, 0.32, 0.56)
    dark=f"#{int(r2*255):02x}{int(g2*255):02x}{int(b2*255):02x}"
    r3,g3,b3 = colorsys.hls_to_rgb(h, 0.79, 0.7)
    pale=f"#{int(r3*255):02x}{int(g3*255):02x}{int(b3*255):02x}"
    return base,dark,pale


BIOME_COLORS = {
    "abyss":"#08121b", "shelf":"#123040", "ice":"#d4e0df", "tundra":"#697876",
    "alpine":"#7c7770", "desert":"#8d7953", "steppe":"#66704b", "temperate":"#405c45",
    "wetland":"#315957", "rainforest":"#274f3f", "barren":"#615d53",
}


def _centroid(sp: dict[str, Any]) -> tuple[float,float]:
    cells=normalize_range(sp)
    if not cells: return (GRID_COLS/2,GRID_ROWS/2)
    return (mean(x for x,_ in cells),mean(y for _,y in cells))


def _map_xy(cell: tuple[float,float], mx: float,my: float,mw: float,mh: float) -> tuple[float,float]:
    return mx+(cell[0]+0.5)/GRID_COLS*mw, my+(cell[1]+0.5)/GRID_ROWS*mh


def _territory_blob(sp: dict[str, Any], mx: float,my: float,mw: float,mh: float, opacity: float=0.34, fossil: bool=False) -> str:
    cells=normalize_range(sp) if not fossil else {(int(c[0]),int(c[1])) for c in sp.get("last_range",[]) if isinstance(c,list) and len(c)==2}
    if not cells: return ""
    base,dark,pale=_species_color(sp)
    cw,ch=mw/GRID_COLS,mh/GRID_ROWS
    radius=min(cw,ch)*0.69
    connections=[]; blobs=[]
    for x,y in sorted(cells):
        cx,cy=_map_xy((x,y),mx,my,mw,mh)
        jitter=((stable_int(f"{sp.get('id')}:{x}:{y}")%100)/100-0.5)*0.16
        rr=radius*(0.88+jitter)
        # Circle as two arc segments inside one path.
        blobs.append(f"M{cx-rr:.1f},{cy:.1f}a{rr:.1f},{rr:.1f} 0 1,0 {rr*2:.1f},0a{rr:.1f},{rr:.1f} 0 1,0 {-rr*2:.1f},0")
        for n in ((x+1,y),(x,y+1)):
            if n in cells:
                x2,y2=_map_xy(n,mx,my,mw,mh); connections.append(f"M{cx:.1f},{cy:.1f}L{x2:.1f},{y2:.1f}")
    dash=' stroke-dasharray="3 3"' if fossil else ''
    conn=f'<path d="{" ".join(connections)}" fill="none" stroke="{base}" stroke-width="{radius*1.45:.2f}" stroke-linecap="round"/>' if connections else ''
    circles=f'<path d="{" ".join(blobs)}" fill="{base}" stroke="{pale if fossil else dark}" stroke-width="{0.7 if fossil else 0.45}"{dash}/>'
    return f'<g class="species-range" data-species="{_esc(sp.get("id"))}" opacity="{opacity:.3f}">{conn}{circles}</g>'

def _morph_glyph(sp: dict[str, Any], x: float,y: float,scale: float=1.0) -> str:
    m=morphology(sp); base,dark,pale=_species_color(sp)
    size=clamp(math.log1p(float(m["body_scale"]))*4.5,3.5,10)*scale
    append=int(m["appendages"])
    lines=[]
    for i in range(append):
        a=i/max(append,1)*math.tau
        length=size*(1.0+0.35*math.sin(i*1.7))
        lines.append(f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x+math.cos(a)*length:.1f}" y2="{y+math.sin(a)*length:.1f}" stroke="{pale}" stroke-width="1" stroke-linecap="round"/>')
    armor=2.1 if m["armor"]=="heavy" else 1.2 if m["armor"]=="plated" else 0.6
    return f'<g>{"".join(lines)}<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="{size:.1f}" ry="{size*0.58:.1f}" fill="{base}" stroke="{dark}" stroke-width="{armor}"/><circle cx="{x+size*0.45:.1f}" cy="{y-size*0.12:.1f}" r="{max(0.8,size*0.09):.1f}" fill="#e9f0e9"/></g>'


def render_world_svg(world: dict[str,Any], species: list[dict[str,Any]], env: dict[str,Any], pathogens: list[dict[str,Any]], plates: dict[str,Any], branch: dict[str,Any], interactions: list[dict[str,Any]]) -> str:
    RENDER_DIR.mkdir(parents=True,exist_ok=True)
    W,H=1600,1040
    mx,my,mw,mh=54,132,1080,700
    live=[s for s in species if s.get("extinct_generation") is None and float(s.get("population",0))>0]
    dead=[s for s in species if s.get("extinct_generation") is not None]
    total=int(sum(float(s.get("population",0)) for s in live))
    occupied=len(set().union(*(normalize_range(s) for s in live))) if live else 0
    gen=int(world.get("generation",0)); era=world.get("era",{}).get("name","Origin Era")
    changes=load_json(CHANGES_PATH,{}) or {}
    if int(changes.get("to_generation",-1)) != gen: changes={}
    parts=[f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="PHYLUM generation {gen} world atlas">
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#071015"/><stop offset="1" stop-color="#0c1415"/></linearGradient>
  <filter id="soft"><feGaussianBlur stdDeviation="2.4"/></filter>
  <filter id="glow"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <marker id="arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 z" fill="#b7c8c1"/></marker>
  <style>
    text{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;fill:#dce8e2}}
    .muted{{fill:#768c84}} .tiny{{font-size:10px}} .small{{font-size:12px}} .label{{font-size:13px;letter-spacing:1px}}
    .metric{{font-size:22px;font-weight:600}} .hair{{stroke:#2b3c3a;stroke-width:1}} .panel{{fill:#0b1518;stroke:#263837;stroke-width:1}}
  </style>
</defs><rect width="100%" height="100%" fill="url(#bg)"/>
<text x="54" y="52" font-size="26" letter-spacing="5">PHYLUM / WORLD ATLAS</text>
<text x="54" y="82" class="small muted">LINEAGE {_esc(branch.get('lineage',world.get('active_lineage','unknown')))} · GEN {gen:06d} · {_esc(era).upper()}</text>
<text x="1545" y="52" text-anchor="end" class="small">{len(live)} LIVING / {len(dead)} EXTINCT / {total:,} ORGANISMS</text>
<text x="1545" y="78" text-anchor="end" class="tiny muted">{occupied} OCCUPIED CELLS · {len([p for p in pathogens if p.get('extinct_generation') is None])} ACTIVE PATHOGENS · {len(plates.get('plates',[]))} PLATES</text>
<rect x="{mx}" y="{my}" width="{mw}" height="{mh}" rx="10" fill="#071013" stroke="#31423f"/>
''']
    # Terrain / biome field at double ecology resolution. Rectangles are batched into one path per biome to keep Git diffs compact.
    parts.append('<g id="layer-biomes">')
    sw,sh=mw/MAP_SAMPLE_COLS,mh/MAP_SAMPLE_ROWS
    seed=int(world.get("seed",0))
    biome_paths={k:[] for k in BIOME_COLORS}
    for gy in range(MAP_SAMPLE_ROWS):
        y=(gy+0.5)/MAP_SAMPLE_ROWS*float(env.get("height",100))
        for gx in range(MAP_SAMPLE_COLS):
            x=(gx+0.5)/MAP_SAMPLE_COLS*float(env.get("width",160))
            biome=biome_at(env,plates,x,y,seed)
            xx=mx+gx*sw; yy=my+gy*sh; ww=sw+0.5; hh=sh+0.5
            biome_paths[biome].append(f"M{xx:.1f},{yy:.1f}h{ww:.1f}v{hh:.1f}h{-ww:.1f}Z")
    for biome,d in biome_paths.items():
        if d: parts.append(f'<path d="{"".join(d)}" fill="{BIOME_COLORS[biome]}"/>')
    parts.append('</g>')
    # Survey grid + coordinate marks.
    parts.append('<g id="layer-grid" opacity="0.18">')
    for i in range(1,12):
        x=mx+i*mw/12; parts.append(f'<line x1="{x:.1f}" y1="{my}" x2="{x:.1f}" y2="{my+mh}" class="hair"/>')
    for i in range(1,8):
        y=my+i*mh/8; parts.append(f'<line x1="{mx}" y1="{y:.1f}" x2="{mx+mw}" y2="{y:.1f}" class="hair"/>')
    parts.append('</g>')
    # Plate boundaries sampled on ecology grid.
    parts.append('<g id="layer-plates" opacity="0.44">')
    cw,ch=mw/GRID_COLS,mh/GRID_ROWS
    plate_ids={}
    for gy in range(GRID_ROWS):
        for gx in range(GRID_COLS):
            x,y=cell_world_xy((gx,gy),env); plate_ids[(gx,gy)]=plate_at(plates,x,y,env)["id"]
    for gy in range(GRID_ROWS):
        for gx in range(GRID_COLS):
            pid=plate_ids[(gx,gy)]
            if gx+1<GRID_COLS and plate_ids[(gx+1,gy)]!=pid:
                xx=mx+(gx+1)*cw; yy=my+gy*ch; parts.append(f'<line x1="{xx:.1f}" y1="{yy:.1f}" x2="{xx:.1f}" y2="{yy+ch:.1f}" stroke="#b48a66" stroke-width="1" stroke-dasharray="2 4"/>')
            if gy+1<GRID_ROWS and plate_ids[(gx,gy+1)]!=pid:
                xx=mx+gx*cw; yy=my+(gy+1)*ch; parts.append(f'<line x1="{xx:.1f}" y1="{yy:.1f}" x2="{xx+cw:.1f}" y2="{yy:.1f}" stroke="#b48a66" stroke-width="1" stroke-dasharray="2 4"/>')
    parts.append('</g>')
    # Elevation contours and deterministic river-like drainage paths.
    parts.append('<g id="layer-contours" opacity="0.22" fill="none">')
    elevations={}
    for gy in range(GRID_ROWS):
        for gx in range(GRID_COLS):
            xx,yy=cell_world_xy((gx,gy),env); elevations[(gx,gy)]=geography_at(env,plates,xx,yy,seed)["elevation"]
    for gy in range(GRID_ROWS-1):
        for gx in range(GRID_COLS-1):
            v=elevations[(gx,gy)]
            for level in (0.47,0.58,0.70,0.82):
                right=elevations[(gx+1,gy)]; down=elevations[(gx,gy+1)]
                if (v-level)*(right-level)<0:
                    xx=mx+(gx+1)*cw; yy=my+(gy+.5)*ch; parts.append(f'<line x1="{xx:.1f}" y1="{yy-ch*.5:.1f}" x2="{xx:.1f}" y2="{yy+ch*.5:.1f}" stroke="#9aa79f" stroke-width="0.55"/>')
                if (v-level)*(down-level)<0:
                    xx=mx+(gx+.5)*cw; yy=my+(gy+1)*ch; parts.append(f'<line x1="{xx-cw*.5:.1f}" y1="{yy:.1f}" x2="{xx+cw*.5:.1f}" y2="{yy:.1f}" stroke="#9aa79f" stroke-width="0.55"/>')
    parts.append('</g>')
    parts.append('<g id="layer-hydrology" opacity="0.48" fill="none" stroke="#77a7b7" stroke-width="1.1">')
    # Start rivers at deterministic high cells and descend greedily.
    starts=sorted(elevations,key=lambda c:(elevations[c],stable_int(f"river:{seed}:{c}")),reverse=True)[:40]
    chosen=[]
    for st in starts:
        if all(math.dist(st,q)>7 for q in chosen): chosen.append(st)
        if len(chosen)>=9: break
    for st in chosen:
        path=[st]; cur=st; seen={st}
        for _ in range(34):
            neigh=[n for n in ((cur[0]+1,cur[1]),(cur[0]-1,cur[1]),(cur[0],cur[1]+1),(cur[0],cur[1]-1)) if n in elevations and n not in seen]
            if not neigh: break
            nxt=min(neigh,key=lambda n:elevations[n]+((stable_int(f"riverstep:{seed}:{n}")%100)/100)*0.006)
            if elevations[nxt]>elevations[cur]+0.025: break
            path.append(nxt); seen.add(nxt); cur=nxt
            xx,yy=cell_world_xy(cur,env)
            if not geography_at(env,plates,xx,yy,seed)["land"]: break
        if len(path)>4:
            pts=' '.join(f"{_map_xy(c,mx,my,mw,mh)[0]:.1f},{_map_xy(c,mx,my,mw,mh)[1]:.1f}" for c in path)
            parts.append(f'<polyline points="{pts}"/>')
    parts.append('</g>')
    # Hidden analytical overlays exposed by the Observatory.
    cell_species={}
    for sp in live:
        for c in normalize_range(sp): cell_species.setdefault(c,[]).append(sp)
    parts.append('<g id="layer-population" style="display:none" opacity="0.62">')
    maxdens=max([sum(float(q.get("population",0))/max(1,len(normalize_range(q))) for q in qs) for qs in cell_species.values()] or [1])
    for c,qs in cell_species.items():
        dens=sum(float(q.get("population",0))/max(1,len(normalize_range(q))) for q in qs); x,y=_map_xy(c,mx,my,mw,mh); a=clamp(dens/maxdens,0,1)
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{2+7*a:.1f}" fill="#f0cf8d" opacity="{0.12+0.55*a:.2f}"/>')
    parts.append('</g>')
    parts.append('<g id="layer-biodiversity" style="display:none" opacity="0.65">')
    maxbio=max([len(qs) for qs in cell_species.values()] or [1])
    for c,qs in cell_species.items():
        x,y=_map_xy(c,mx,my,mw,mh); a=len(qs)/maxbio
        parts.append(f'<rect x="{x-cw*.45:.1f}" y="{y-ch*.45:.1f}" width="{cw*.9:.1f}" height="{ch*.9:.1f}" rx="3" fill="#d9b56c" opacity="{0.12+0.5*a:.2f}"/>')
    parts.append('</g>')
    parts.append('<g id="layer-genetics" style="display:none" opacity="0.68">')
    for c,qs in cell_species.items():
        x,y=_map_xy(c,mx,my,mw,mh); a=mean(float(q.get("genetic_diversity",0)) for q in qs)
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{2+6*a:.1f}" fill="#a984c7" opacity="{0.18+0.5*a:.2f}"/>')
    parts.append('</g>')
    parts.append('<g id="layer-climate" style="display:none" opacity="0.42">')
    for gy in range(0,MAP_SAMPLE_ROWS,2):
        for gx in range(0,MAP_SAMPLE_COLS,2):
            xx=(gx+.5)/MAP_SAMPLE_COLS*float(env.get("width",160)); yy=(gy+.5)/MAP_SAMPLE_ROWS*float(env.get("height",100)); t,mo,_=climate_at(env,plates,xx,yy,seed)
            col="#c46f58" if t>0.58 else "#6a9fc0"; op=abs(t-.5)*0.7+abs(mo-.5)*0.15
            parts.append(f'<rect x="{mx+gx*sw:.1f}" y="{my+gy*sh:.1f}" width="{sw*2+1:.1f}" height="{sh*2+1:.1f}" fill="{col}" opacity="{clamp(op,0.04,0.5):.2f}"/>')
    parts.append('</g>')
    # Environmental scars.
    parts.append('<g id="layer-scars">')
    for scar in env.get("scars",[]):
        sx=mx+float(scar.get("x",0))/float(env.get("width",160))*mw; sy=my+float(scar.get("y",0))/float(env.get("height",100))*mh
        rr=float(scar.get("radius",20))/float(env.get("width",160))*mw
        kind=scar.get("kind",""); col="#c16a52" if kind in {"fire","impact","volcanic"} else "#9d8a58" if kind=="drought" else "#6a91a2"
        parts.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="{rr:.1f}" fill="{col}" opacity="{0.06+float(scar.get("strength",0.1))*0.12:.3f}" stroke="{col}" stroke-width="1" stroke-dasharray="4 5"/>')
        if float(scar.get("severity",0))>0.55: parts.append(f'<text x="{sx:.1f}" y="{sy:.1f}" class="tiny" text-anchor="middle">{_esc(kind.upper())}</text>')
    parts.append('</g>')
    # Fossil ghost ranges, only recently extinct or important.
    parts.append('<g id="layer-fossils" opacity="0.22">')
    for sp in dead[-30:]: parts.append(_territory_blob(sp,mx,my,mw,mh,0.28,True))
    parts.append('</g>')
    # Living territories.
    parts.append('<g id="layer-territory">')
    for sp in sorted(live,key=lambda s:float(s.get("population",0))):
        parts.append(_territory_blob(sp,mx,my,mw,mh,0.34,False))
        # population cores
        cells=normalize_range(sp); base,dark,pale=_species_color(sp)
        if cells:
            density=float(sp.get("population",0))/max(1,len(cells)); rr=clamp(math.sqrt(density)*0.26,1.4,5.8); cores=[]
            for x,y in cells:
                cx,cy=_map_xy((x,y),mx,my,mw,mh); cores.append(f"M{cx-rr:.1f},{cy:.1f}a{rr:.1f},{rr:.1f} 0 1,0 {rr*2:.1f},0a{rr:.1f},{rr:.1f} 0 1,0 {-rr*2:.1f},0")
            parts.append(f'<path d="{" ".join(cores)}" fill="{pale}" opacity="0.24"/>')
    parts.append('</g>')
    # Migration trails. Current-generation movement is bright; older paths fade into survey history.
    parts.append('<g id="layer-migration" fill="none" marker-end="url(#arrow)">')
    for sp in live:
        trails=sp.get("migration_trail",[])[-6:]
        for age,tr in enumerate(trails):
            a=tr.get("from"); b=tr.get("to")
            if a and b:
                x1,y1=_map_xy((float(a[0]),float(a[1])),mx,my,mw,mh); x2,y2=_map_xy((float(b[0]),float(b[1])),mx,my,mw,mh)
                current=int(tr.get("generation",-1))==gen
                opacity=0.92 if current else 0.16+0.07*(age+1); width=2.6 if current else 0.8+0.12*age
                col=_species_color(sp)[2] if current else "#9bb0a8"; lift=22 if current else 12
                parts.append(f'<path d="M{x1:.1f},{y1:.1f} Q{(x1+x2)/2:.1f},{min(y1,y2)-lift:.1f} {x2:.1f},{y2:.1f}" stroke="{col}" stroke-width="{width:.1f}" opacity="{opacity:.2f}"/>')
    parts.append('</g>')
    # Ecological interactions.
    byid={s["id"]:s for s in live}; parts.append('<g id="layer-ecology" opacity="0.7">')
    for it in sorted(interactions,key=lambda i:float(i.get("strength",0)),reverse=True)[:32]:
        a,b=byid.get(it.get("source")),byid.get(it.get("target"))
        if not a or not b: continue
        ca,cb=_centroid(a),_centroid(b); x1,y1=_map_xy(ca,mx,my,mw,mh); x2,y2=_map_xy(cb,mx,my,mw,mh)
        pred=it.get("type")=="predation"; col="#d99776" if pred else "#9caa92"
        parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{col}" stroke-width="{clamp(float(it.get("strength",0))*2,0.6,2.5):.2f}" stroke-dasharray="{'' if pred else '3 4'}" {"marker-end='url(#arrow)'" if pred else ''}/>')
    parts.append('</g>')
    # Predator/prey contact zones.
    parts.append('<g id="layer-contact-zones">')
    for it in sorted((i for i in interactions if i.get("type")=="predation"),key=lambda i:float(i.get("strength",0)),reverse=True)[:24]:
        a,b=byid.get(it.get("source")),byid.get(it.get("target"))
        if not a or not b: continue
        overlap=sorted(normalize_range(a)&normalize_range(b))
        if overlap:
            for c in overlap[:18]:
                xx,yy=_map_xy(c,mx,my,mw,mh)
                parts.append(f'<circle cx="{xx:.1f}" cy="{yy:.1f}" r="5.3" fill="#d98262" opacity="0.22" stroke="#f0ad86" stroke-width="0.8"/>')
        else:
            ca,cb=_centroid(a),_centroid(b); x1,y1=_map_xy(ca,mx,my,mw,mh); x2,y2=_map_xy(cb,mx,my,mw,mh)
            parts.append(f'<circle cx="{(x1+x2)/2:.1f}" cy="{(y1+y2)/2:.1f}" r="5" fill="none" stroke="#d98262" stroke-width="1.2" opacity="0.55"/>')
    parts.append('</g>')
    # Disease outbreaks: infected range + outbreak ring.
    parts.append('<g id="layer-disease">')
    for sp in live:
        prevalence=max([float(v) for v in sp.get("infections",{}).values()] or [0])
        if prevalence<0.005: continue
        for c in normalize_range(sp):
            xx,yy=_map_xy(c,mx,my,mw,mh); rr=clamp(2.2+prevalence*8,2.2,8.8)
            parts.append(f'<circle cx="{xx:.1f}" cy="{yy:.1f}" r="{rr:.1f}" fill="#c85e68" opacity="{0.05+prevalence*0.22:.2f}"/>')
        cx,cy=_map_xy(_centroid(sp),mx,my,mw,mh); rr=15+prevalence*38
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{rr:.1f}" fill="none" stroke="#e1747d" stroke-width="2.2" opacity="{0.30+prevalence*0.55:.2f}" stroke-dasharray="5 5"/>')
        parts.append(f'<text x="{cx:.1f}" y="{cy+rr+12:.1f}" text-anchor="middle" class="tiny" fill="#ef9ca2">INFECTION {prevalence*100:.1f}%</text>')
    parts.append('</g>')
    # Current-generation WITNESS event markers.
    parts.append('<g id="layer-events">')
    event_colors={"migration":"#b9d4c5","speciation":"#d8c080","extinction":"#a79a98","disease":"#e1747d","pandemic":"#f05d67","disaster":"#e09a66","mass_extinction":"#ff725f","tectonic":"#c99a6c","climate":"#79a9bb","contact":"#c7a5d8","era":"#e1cf8d"}
    for marker in changes.get("markers",[])[:18]:
        pos=marker.get("position")
        if not pos: continue
        ex,ey=_map_xy((float(pos[0]),float(pos[1])),mx,my,mw,mh)
        kind=str(marker.get("kind","event")); col=event_colors.get(kind,"#d8e5df"); glyph=_esc(marker.get("glyph","•")); tip=_esc(marker.get("text",""))
        parts.append(f'<g><title>{tip}</title><circle cx="{ex:.1f}" cy="{ey:.1f}" r="11" fill="#071013" stroke="{col}" stroke-width="1.6" opacity="0.94"/><text x="{ex:.1f}" y="{ey+4:.1f}" text-anchor="middle" font-size="12" fill="{col}">{glyph}</text></g>')
    parts.append('</g>')
    # Labels and organism glyphs.
    parts.append('<g id="layer-labels">')
    for i,sp in enumerate(sorted(live,key=lambda s:float(s.get("population",0)),reverse=True)[:24]):
        cx,cy=_map_xy(_centroid(sp),mx,my,mw,mh); base,dark,pale=_species_color(sp)
        side=-1 if cx>mx+mw*0.66 else 1; lx=cx+side*(28+(i%3)*5); ly=cy-18-(i%4)*6
        parts.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{lx:.1f}" y2="{ly:.1f}" stroke="{pale}" stroke-width="0.8" opacity="0.6"/>')
        parts.append(_morph_glyph(sp,cx,cy,0.72))
        anch="end" if side<0 else "start"
        parts.append(f'<text x="{lx+side*4:.1f}" y="{ly:.1f}" text-anchor="{anch}" class="small" fill="{pale}">{_esc(sp["name"])}</text><text x="{lx+side*4:.1f}" y="{ly+13:.1f}" text-anchor="{anch}" class="tiny muted">{int(sp.get("population",0)):,} · {_esc(trophic_role(sp))}</text>')
    parts.append('</g>')
    # Compass / scale.
    parts.append(f'<g transform="translate({mx+mw-38},{my+48})"><circle r="24" fill="#071013" stroke="#5b6f69"/><path d="M0,-18 L5,2 L0,-2 L-5,2 Z" fill="#d7e4de"/><text y="-29" text-anchor="middle" class="tiny">N</text></g>')
    # Sidebar.
    sx=1160; parts.append(f'<rect x="{sx}" y="132" width="386" height="700" rx="10" class="panel"/>')
    parts.append(f'<text x="{sx+24}" y="168" class="label">BIOSPHERE STATE</text>')
    metrics=[("POPULATION",f"{total:,}"),("LIVING",str(len(live))),("EXTINCT",str(len(dead))),("PATHOGENS",str(len([p for p in pathogens if p.get("extinct_generation") is None]))),("PLATES",str(len(plates.get("plates",[])))),("DIVERSITY",f"{mean(float(s.get('genetic_diversity',0)) for s in live):.2f}")]
    for j,(lab,val) in enumerate(metrics):
        col=j%2; row=j//2; x=sx+24+col*178; y=202+row*66
        parts.append(f'<text x="{x}" y="{y}" class="tiny muted">{lab}</text><text x="{x}" y="{y+27}" class="metric">{val}</text>')
    # Climate bars.
    y0=410; parts.append(f'<text x="{sx+24}" y="{y0}" class="label">PLANETARY CONDITIONS</text>')
    cond=[("TEMP",float(env.get("temperature",0))), ("MOISTURE",float(env.get("moisture",0))), ("RESOURCES",float(env.get("resources",0)))]
    for k,(lab,val) in enumerate(cond):
        y=y0+28+k*34; parts.append(f'<text x="{sx+24}" y="{y}" class="tiny muted">{lab}</text><rect x="{sx+104}" y="{y-9}" width="205" height="8" rx="4" fill="#1d2a29"/><rect x="{sx+104}" y="{y-9}" width="{205*clamp(val,0,1):.1f}" height="8" rx="4" fill="#8aa99a"/><text x="{sx+326}" y="{y}" class="tiny">{val:.2f}</text>')
    # Generation delta: explain the latest step without comparing screenshots.
    dy=535; ds=changes.get("summary",{})
    parts.append(f'<text x="{sx+24}" y="{dy}" class="label">GENERATION DELTA</text>')
    if ds:
        delta_metrics=[("POP Δ",f"{float(ds.get('population_delta',0)):+.0f}"),("RANGE Δ",f"{int(ds.get('occupied_delta',0)):+d}"),("LINEAGES Δ",f"{int(ds.get('living_delta',0)):+d}"),("EVENTS",str(int(ds.get("events",0))))]
        for j,(lab,val) in enumerate(delta_metrics):
            col=j%2; row=j//2; x=sx+24+col*178; y=dy+29+row*48
            parts.append(f'<text x="{x}" y="{y}" class="tiny muted">{lab}</text><text x="{x}" y="{y+21}" font-size="17">{_esc(val)}</text>')
        changed=[r for r in changes.get("lineages",[]) if r.get("status") in {"new","extinct"} or abs(float(r.get("population_delta",0)))>=1 or int(r.get("range_delta",0))!=0]
        if changed:
            r=changed[0]; parts.append(f'<text x="{sx+24}" y="{dy+130}" class="tiny muted">MOST CHANGED</text><text x="{sx+24}" y="{dy+149}" class="small">{_esc(r.get("name","lineage"))} · pop {float(r.get("population_delta",0)):+.0f} · range {int(r.get("range_delta",0)):+d}</text>')
    else:
        parts.append(f'<text x="{sx+24}" y="{dy+30}" class="small muted">Awaiting the next evolved generation.</text>')
    y1=705; parts.append(f'<text x="{sx+24}" y="{y1}" class="label">DOMINANT LINEAGES</text>')
    for k,sp in enumerate(sorted(live,key=lambda s:float(s.get("population",0)),reverse=True)[:2]):
        y=y1+31+k*48; base,dark,pale=_species_color(sp)
        parts.append(_morph_glyph(sp,sx+38,y+7,0.48))
        parts.append(f'<text x="{sx+58}" y="{y+3}" class="small" fill="{pale}">{_esc(sp["name"])}</text><text x="{sx+58}" y="{y+18}" class="tiny muted">{_esc(trophic_role(sp))} · fit {float(sp.get("last_fitness",0)):.2f} · range {len(normalize_range(sp))}</text><text x="{sx+340}" y="{y+4}" class="small" text-anchor="end">{int(sp.get("population",0)):,}</text>')
    # Footer event strip + legend.
    recent=read_ndjson(EVENTS_PATH,8)
    fy=874; parts.append(f'<line x1="54" y1="852" x2="1546" y2="852" class="hair"/><text x="54" y="{fy}" class="label">RECENT FOSSIL RECORD</text>')
    for k,e in enumerate(recent[-5:]):
        parts.append(f'<text x="54" y="{fy+25+k*23}" class="small"><tspan class="muted">{int(e.get("generation",0)):06d} / {_esc(str(e.get("kind","event")).upper())}</tspan><tspan dx="15">{_esc(e.get("text",""))[:150]}</tspan></text>')
    legendx=1160; legendy=874; parts.append(f'<text x="{legendx}" y="{legendy}" class="label">ATLAS LAYERS</text>')
    legend=[("BIOMES","terrain / ocean"),("PLATES","dashed boundaries"),("RANGES","living territory"),("CONTACT","predation fronts"),("DISEASE","infected ranges"),("EVENTS","current-gen markers")]
    for i,(a,b) in enumerate(legend): parts.append(f'<text x="{legendx}" y="{legendy+25+i*22}" class="tiny"><tspan fill="#bcd0c6">{a}</tspan><tspan dx="12" class="muted">{b}</tspan></text>')
    parts.append('</svg>')
    svg=''.join(parts)
    WORLD_SVG.write_text(svg,encoding='utf-8')
    return svg


def render_phylogeny_svg(world: dict[str,Any], species: list[dict[str,Any]]) -> str:
    RENDER_DIR.mkdir(parents=True,exist_ok=True)
    nodes=sorted(species,key=lambda s:(int(s.get("born_generation",0)),s.get("id","")))
    maxgen=max([int(s.get("extinct_generation") or world.get("generation",0)) for s in nodes] or [1])
    H=max(420,100+len(nodes)*46); W=1600; left=220; right=80; top=70
    row={s["id"]:top+i*44 for i,s in enumerate(nodes)}
    def gx(g:int)->float: return left+(W-left-right)*g/max(maxgen,1)
    p=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}"><rect width="100%" height="100%" fill="#091215"/><style>text{{font-family:ui-monospace,monospace;fill:#dce8e2}}.m{{fill:#71867e;font-size:11px}}</style><text x="36" y="38" font-size="20" letter-spacing="4">PHYLUM / PHYLOGENETIC RECORD</text>']
    for s in nodes:
        pid=s.get("parent_id")
        if pid in row:
            parent=next((x for x in nodes if x["id"]==pid),None)
            if parent:
                x1=gx(int(s.get("born_generation",0))); y1=row[pid]; y2=row[s["id"]]
                p.append(f'<path d="M{x1-20:.1f},{y1:.1f} C{x1-8:.1f},{y1:.1f} {x1-8:.1f},{y2:.1f} {x1:.1f},{y2:.1f}" fill="none" stroke="#526b63" stroke-width="1.2"/>')
    for s in nodes:
        born=int(s.get("born_generation",0)); end=int(s.get("extinct_generation") or world.get("generation",0)); y=row[s["id"]]; x1=gx(born); x2=gx(end); alive=s.get("extinct_generation") is None
        base,dark,pale=_species_color(s); col=base if alive else "#66706c"
        p.append(f'<line x1="{x1:.1f}" y1="{y:.1f}" x2="{x2:.1f}" y2="{y:.1f}" stroke="{col}" stroke-width="{3.5 if alive else 1.5}" {"" if alive else "stroke-dasharray=\"4 4\""}/><circle cx="{x1:.1f}" cy="{y:.1f}" r="4" fill="{col}"/>')
        p.append(f'<text x="36" y="{y+4:.1f}" font-size="12" fill="{pale if alive else '#8a9691'}">{_esc(s.get("name"))}{"" if alive else " †"}</text><text x="{x1+8:.1f}" y="{y-8:.1f}" class="m">gen {born}</text>')
    p.append(f'<text x="{gx(0):.1f}" y="{H-26}" class="m">GEN 0</text><text x="{gx(maxgen):.1f}" y="{H-26}" class="m" text-anchor="end">GEN {maxgen}</text></svg>')
    svg=''.join(p); PHYLO_SVG.write_text(svg,encoding='utf-8'); return svg


def render_foodweb_svg(world: dict[str,Any], species: list[dict[str,Any]], interactions: list[dict[str,Any]]) -> str:
    live=sorted([s for s in species if s.get("extinct_generation") is None],key=lambda s:s.get("id",""))[:80]
    W,H=1400,820; cx,cy=W/2,H/2; radius=min(W,H)*0.37; pos={}
    for i,s in enumerate(live):
        a=i/max(1,len(live))*math.tau-math.pi/2; pos[s["id"]]=(cx+math.cos(a)*radius,cy+math.sin(a)*radius)
    p=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}"><rect width="100%" height="100%" fill="#091215"/><style>text{{font-family:ui-monospace,monospace;fill:#dce8e2}}</style><defs><marker id="a" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0L7,3.5L0,7z" fill="#b87964"/></marker></defs><text x="36" y="42" font-size="20" letter-spacing="4">PHYLUM / FOOD WEB</text>']
    for it in sorted(interactions,key=lambda x:float(x.get("strength",0)),reverse=True)[:120]:
        if it.get("source") not in pos or it.get("target") not in pos: continue
        x1,y1=pos[it["source"]]; x2,y2=pos[it["target"]]; pred=it.get("type")=="predation"
        p.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{'#b87964' if pred else '#6f827a'}" stroke-width="{clamp(float(it.get("strength",0))*2,0.5,2.2):.2f}" opacity="0.55" {"marker-end=\"url(#a)\"" if pred else "stroke-dasharray=\"3 4\""}/>')
    for s in live:
        x,y=pos[s["id"]]; base,dark,pale=_species_color(s); rr=7+math.log1p(float(s.get("population",0)))*1.2
        p.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rr:.1f}" fill="{base}" stroke="{dark}"/><text x="{x:.1f}" y="{y+rr+15:.1f}" font-size="10" text-anchor="middle">{_esc(s.get("name"))}</text>')
    p.append('</svg>'); svg=''.join(p); FOODWEB_SVG.write_text(svg,encoding='utf-8'); return svg


def _fossil_catalog(species: list[dict[str,Any]]) -> list[dict[str,Any]]:
    out=[]
    for s in species:
        out.append({
            "id":s.get("id"),"name":s.get("name"),"parent_id":s.get("parent_id"),"born_generation":s.get("born_generation",0),
            "extinct_generation":s.get("extinct_generation"),"extinction_cause":s.get("extinction_cause"),"population":round(float(s.get("population",0)),2),
            "peak_population":round(float(s.get("peak_population",0)),2),"peak_range":int(s.get("peak_range",0)),"role":trophic_role(s),
            "genetic_diversity":round(float(s.get("genetic_diversity",0)),4),"native_lineage":s.get("native_lineage"),"behavior":behavior_profile(s),
            "morphology":morphology(s),"offspring_lineages":s.get("offspring_lineages",[]),"regions_seen":s.get("regions_seen",[]),
        })
    return out


def render_observatory(world: dict[str,Any], species: list[dict[str,Any]], env: dict[str,Any], pathogens: list[dict[str,Any]], plates: dict[str,Any], branch: dict[str,Any], interactions: list[dict[str,Any]], world_svg: str) -> None:
    DOCS_DIR.mkdir(parents=True,exist_ok=True)
    (DOCS_DIR/".nojekyll").write_text("",encoding="utf-8")
    # Pages publishes docs/ as an isolated root, so mirror the generated observation plates into it.
    if WORLD_SVG.exists(): shutil.copy2(WORLD_SVG,DOCS_DIR/"current.svg")
    if PHYLO_SVG.exists(): shutil.copy2(PHYLO_SVG,DOCS_DIR/"phylogeny.svg")
    if FOODWEB_SVG.exists(): shutil.copy2(FOODWEB_SVG,DOCS_DIR/"foodweb.svg")
    events=read_ndjson(EVENTS_PATH,400)
    history=read_ndjson(HISTORY_PATH,500)
    atlas_history=read_ndjson(ATLAS_HISTORY_PATH,500)
    catalog=_fossil_catalog(species)
    changes=load_json(CHANGES_PATH,{}) or {}
    data={"world":world,"environment":env,"branch":branch,"species":catalog,"pathogens":pathogens,"interactions":interactions,"events":events,"history":history,"changes":changes}
    (DOCS_DIR/"data.json").write_text(json.dumps(data,indent=2,sort_keys=True),encoding="utf-8")
    # Deep-time atlas history is split from current data so ordinary generations do not rewrite a multi-megabyte HTML file.
    (DOCS_DIR/"atlas-history.js").write_text("window.PHYLUM_ATLAS_HISTORY="+json.dumps(atlas_history,separators=(",",":"),ensure_ascii=True)+";\n",encoding="utf-8")
    data_json=json.dumps(data,separators=(",",":"),ensure_ascii=True).replace("</","<\\/")
    html_doc=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PHYLUM Observatory</title>
<style>
:root{{--bg:#071014;--panel:#0b1619;--line:#263b38;--text:#dce8e2;--muted:#748a82;--accent:#9bb8aa}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font:14px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}} header{{padding:22px 28px;border-bottom:1px solid var(--line);display:flex;gap:28px;align-items:end;flex-wrap:wrap}} h1{{font-size:20px;letter-spacing:.28em;margin:0}} .sub{{color:var(--muted)}} nav{{display:flex;gap:8px;flex-wrap:wrap;margin-left:auto}} button,input{{font:inherit}} button{{background:#0f2022;color:var(--text);border:1px solid #2e4743;padding:8px 11px;border-radius:6px;cursor:pointer}} button.active{{background:#244238;border-color:#668d7d}} main{{padding:20px 24px;max-width:1800px;margin:auto}} .tab{{display:none}} .tab.active{{display:block}} .atlas svg{{width:100%;height:auto;border:1px solid var(--line);border-radius:8px}} .layers{{display:flex;gap:7px;flex-wrap:wrap;margin:0 0 12px}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}} .card{{background:var(--panel);border:1px solid var(--line);padding:15px;border-radius:8px}} .metric{{font-size:28px;margin-top:5px}} .muted{{color:var(--muted)}} table{{width:100%;border-collapse:collapse}} th,td{{text-align:left;padding:9px;border-bottom:1px solid #1d312e}} .dead{{opacity:.62}} .event{{border-left:2px solid #4c6d62;padding:7px 12px;margin:7px 0;background:#0a1517}} input{{background:#071013;border:1px solid var(--line);color:var(--text);padding:9px;width:min(420px,100%);border-radius:6px}} .bar{{height:7px;background:#172724;border-radius:9px;overflow:hidden}} .bar i{{display:block;height:100%;background:#7eaa98}} code{{color:#b7cfc4}} @media(max-width:700px){{main{{padding:12px}}header{{padding:16px}}}}
</style></head><body><header><div><h1>PHYLUM / OBSERVATORY</h1><div class="sub">lineage {_esc(branch.get('lineage',world.get('active_lineage','unknown')))} · generation {int(world.get('generation',0)):06d} · {_esc(world.get('era',{}).get('name','Origin Era'))}</div></div><nav><button data-tab="atlas" class="active">ATLAS</button><button data-tab="changes">CHANGES</button><button data-tab="lineages">LINEAGES</button><button data-tab="fossils">FOSSILS</button><button data-tab="timeline">TIMELINE</button><button data-tab="branches">BRANCHES</button><a href="soma.html" style="background:#0f2022;color:var(--text);border:1px solid #2e4743;padding:8px 11px;border-radius:6px;text-decoration:none">SOMA</a></nav></header><main>
<section id="atlas" class="tab active"><div class="layers"><button data-layer="layer-biomes" class="active">BIOMES</button><button data-layer="layer-plates" class="active">TECTONICS</button><button data-layer="layer-contours" class="active">RELIEF</button><button data-layer="layer-hydrology" class="active">RIVERS</button><button data-layer="layer-territory" class="active">TERRITORIES</button><button data-layer="layer-migration" class="active">MIGRATION</button><button data-layer="layer-ecology" class="active">ECOLOGY</button><button data-layer="layer-contact-zones" class="active">CONTACT ZONES</button><button data-layer="layer-disease" class="active">DISEASE</button><button data-layer="layer-events" class="active">EVENTS</button><button data-layer="layer-fossils" class="active">FOSSILS</button><button data-layer="layer-scars" class="active">SCARS</button><button data-layer="layer-labels" class="active">LABELS</button><button data-layer="layer-population">POPULATION</button><button data-layer="layer-biodiversity">BIODIVERSITY</button><button data-layer="layer-genetics">GENETICS</button><button data-layer="layer-climate">CLIMATE</button></div><div class="atlas"><object id="atlasObject" type="image/svg+xml" data="current.svg?gen={int(world.get('generation',0)):06d}" style="width:100%;aspect-ratio:1600/1040;display:block"></object></div></section>
<section id="changes" class="tab"><div class="grid" id="changeMetrics"></div><h3>LINEAGE DELTAS</h3><div id="changeTable"></div></section>
<section id="lineages" class="tab"><div class="grid" id="lineageCards"></div></section>
<section id="fossils" class="tab"><p><input id="fossilSearch" placeholder="search lineage, role, cause, region"></p><div id="fossilTable"></div></section>
<section id="timeline" class="tab"><div class="card" style="margin-bottom:14px"><div class="muted">DEEP-TIME ATLAS SNAPSHOTS</div><input id="timeSlider" type="range" min="0" max="0" value="0" style="width:100%;margin:14px 0"><div id="timeLabel"></div><canvas id="timeCanvas" width="960" height="480" style="width:100%;height:auto;border:1px solid #263b38;margin-top:10px"></canvas></div><div id="timelineList"></div></section>
<section id="branches" class="tab"><div class="grid"><div class="card"><div class="muted">ACTIVE LINEAGE</div><div class="metric">{_esc(branch.get('lineage','unknown'))}</div></div><div class="card"><div class="muted">ROOT FINGERPRINT</div><div style="font-size:18px;margin-top:8px">{_esc(branch.get('root_fingerprint','unknown'))}</div></div><div class="card"><div class="muted">CONTACT EVENTS</div><div class="metric">{len(branch.get('contacts',[]))}</div></div></div><h3>CONTACT HISTORY</h3><div id="contacts"></div><p class="muted">Compare two worlds locally with <code>python -m phylum compare path/to/other/PHYLUM</code>. Resolve a branch encounter biologically with <code>python -m phylum contact path/to/other/PHYLUM</code>.</p></section>
</main><script src="atlas-history.js"></script><script>const DATA={data_json};
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
$$('[data-tab]').forEach(b=>b.addEventListener('click',()=>{{$$('[data-tab]').forEach(x=>x.classList.remove('active'));b.classList.add('active');$$('.tab').forEach(x=>x.classList.remove('active'));$('#'+b.dataset.tab).classList.add('active')}}));
$$('[data-layer]').forEach(b=>b.addEventListener('click',()=>{{const obj=$('#atlasObject');const doc=obj&&obj.contentDocument;const el=doc&&doc.getElementById(b.dataset.layer);if(!el)return;b.classList.toggle('active');el.style.display=b.classList.contains('active')?'':'none'}}));
function renderChanges(){{const c=DATA.changes||{{}},s=c.summary||{{}};const signed=n=>`${{n>=0?'+':''}}${{Number(n||0).toLocaleString()}}`;const cards=[['POPULATION Δ',signed(s.population_delta||0)],['RANGE Δ',signed(s.occupied_delta||0)],['LINEAGES Δ',signed(s.living_delta||0)],['EVENTS',String(s.events||0)],['NEW PATHOGENS',String(s.new_pathogens||0)],['NEW PREDATION',String(s.new_predation_links||0)]];$('#changeMetrics').innerHTML=cards.map(x=>`<div class="card"><div class="muted">${{x[0]}}</div><div class="metric">${{x[1]}}</div></div>`).join('');const rows=(c.lineages||[]).filter(r=>r.status==='new'||r.status==='extinct'||Math.abs(r.population_delta||0)>=1||(r.range_delta||0)!==0);$('#changeTable').innerHTML=rows.length?`<table><thead><tr><th>lineage</th><th>status</th><th>population Δ</th><th>range Δ</th><th>movement</th><th>infection</th></tr></thead><tbody>${{rows.map(r=>`<tr class="${{r.status==='extinct'?'dead':''}}"><td>${{r.name}}</td><td>${{r.status}}</td><td>${{signed(r.population_delta)}}</td><td>${{signed(r.range_delta)}}</td><td>${{Number(r.movement||0).toFixed(2)}}</td><td>${{(Number(r.infection_peak_after||0)*100).toFixed(1)}}%</td></tr>`).join('')}}</tbody></table>`:'<p class="muted">No measurable lineage changes were recorded.</p>'}}renderChanges();
function lineageCards(){{const live=DATA.species.filter(s=>s.extinct_generation===null).sort((a,b)=>b.population-a.population);$('#lineageCards').innerHTML=live.map(s=>`<div class="card"><div class="muted">${{s.id}} / ${{s.role.toUpperCase()}}</div><h3>${{s.name}}</h3><div class="metric">${{Math.round(s.population).toLocaleString()}}</div><div class="muted">organisms · peak ${{Math.round(s.peak_population).toLocaleString()}}</div><p>${{s.behavior.join(' · ')}}</p><div class="muted">GENETIC DIVERSITY ${{s.genetic_diversity.toFixed(2)}}</div><div class="bar"><i style="width:${{s.genetic_diversity*100}}%"></i></div><p class="muted">born gen ${{s.born_generation}} · peak range ${{s.peak_range}} cells</p></div>`).join('')}}lineageCards();
function fossils(q=''){{q=q.toLowerCase();const rows=DATA.species.filter(s=>JSON.stringify(s).toLowerCase().includes(q));$('#fossilTable').innerHTML=`<table><thead><tr><th>lineage</th><th>born</th><th>ended</th><th>role</th><th>peak pop.</th><th>cause</th></tr></thead><tbody>${{rows.map(s=>`<tr class="${{s.extinct_generation!==null?'dead':''}}"><td>${{s.name}}${{s.extinct_generation!==null?' †':''}}</td><td>${{s.born_generation}}</td><td>${{s.extinct_generation??'living'}}</td><td>${{s.role}}</td><td>${{Math.round(s.peak_population).toLocaleString()}}</td><td>${{s.extinction_cause??'—'}}</td></tr>`).join('')}}</tbody></table>`}}fossils();$('#fossilSearch').addEventListener('input',e=>fossils(e.target.value));
$('#timelineList').innerHTML=DATA.events.slice().reverse().map(e=>`<div class="event"><span class="muted">GEN ${{String(e.generation??0).padStart(6,'0')}} / ${{String(e.kind).toUpperCase()}}</span><br>${{e.text}}</div>`).join('')||'<p class="muted">No events recorded.</p>';
const snaps=window.PHYLUM_ATLAS_HISTORY||[];const slider=$('#timeSlider'),canvas=$('#timeCanvas'),ctx=canvas.getContext('2d');slider.max=Math.max(0,snaps.length-1);slider.value=Math.max(0,snaps.length-1);function drawSnap(){{const s=snaps[+slider.value];ctx.fillStyle='#071013';ctx.fillRect(0,0,canvas.width,canvas.height);if(!s){{$('#timeLabel').textContent='No atlas snapshots yet';return}};$('#timeLabel').textContent=`GEN ${{String(s.generation).padStart(6,'0')}} · ${{s.era||''}} · ${{s.species.filter(x=>!x.extinct).length}} living lineages`;ctx.strokeStyle='#243834';ctx.globalAlpha=.5;for(let i=1;i<12;i++){{ctx.beginPath();ctx.moveTo(i*80,0);ctx.lineTo(i*80,480);ctx.stroke()}}for(let i=1;i<6;i++){{ctx.beginPath();ctx.moveTo(0,i*80);ctx.lineTo(960,i*80);ctx.stroke()}}ctx.globalAlpha=1;(s.species||[]).filter(x=>!x.extinct).forEach((sp,idx)=>{{const hue=(idx*71+37)%360;ctx.fillStyle=`hsla(${{hue}},55%,65%,.45)`;(sp.range||[]).forEach(c=>{{ctx.beginPath();ctx.arc((c[0]+.5)/48*960,(c[1]+.5)/30*480,8,0,Math.PI*2);ctx.fill()}})}})}}slider.addEventListener('input',drawSnap);drawSnap();
$('#contacts').innerHTML=(DATA.branch.contacts||[]).map(c=>`<div class="event">GEN ${{String(c.generation).padStart(6,'0')}} / CONTACT WITH ${{c.with}} — ${{c.introduced_lineages}} lineages, ${{c.pathogens_transferred}} pathogens</div>`).join('')||'<p class="muted">No branch contact has occurred.</p>';
</script></body></html>'''
    (DOCS_DIR/"index.html").write_text(html_doc,encoding="utf-8")


def update_readme(world: dict[str,Any], species: list[dict[str,Any]], pathogens: list[dict[str,Any]], interactions: list[dict[str,Any]]) -> None:
    if README_PATH.exists(): text=README_PATH.read_text(encoding='utf-8')
    else: text="# PHYLUM\n\n**An evolutionary simulation written into Git history.**\n"
    gen=int(world.get("generation",0)); live=[s for s in species if s.get("extinct_generation") is None]; dead=[s for s in species if s.get("extinct_generation") is not None]
    total=int(sum(float(s.get("population",0)) for s in live)); occupied=len(set().union(*(normalize_range(s) for s in live))) if live else 0
    dominant=max(live,key=lambda s:float(s.get("population",0)),default=None)
    events=read_ndjson(EVENTS_PATH,1); latest=(events[-1].get("text") or events[-1].get("message") or "No fossil event yet.") if events else "No fossil event yet."
    delta=(load_json(CHANGES_PATH,{}) or {}).get("summary",{})
    block=("<!-- PHYLUM:STATE:START -->\n"
           f"**Generation:** `{gen}`  \n**Era:** `{world.get('era',{}).get('name','Origin Era')}`  \n**Living lineages:** `{len(live)}`  \n**Extinct lineages:** `{len(dead)}`  \n"
           f"**Population:** `{total:,}`  \n**Occupied cells:** `{occupied}` / `{GRID_COLS*GRID_ROWS}`  \n**Active pathogens:** `{len([p for p in pathogens if p.get('extinct_generation') is None])}`  \n"
           f"**Predator/prey links:** `{len([i for i in interactions if i.get('type')=='predation'])}`  \n**Dominant lineage:** `{dominant.get('name') if dominant else 'none'}`  \n**Last generation Δ:** `{int(delta.get('population_delta',0)):+,}` organisms · `{int(delta.get('occupied_delta',0)):+d}` occupied cells  \n**Latest fossil:** {latest}\n"
           "<!-- PHYLUM:STATE:END -->")
    import re
    if "<!-- PHYLUM:STATE:START -->" in text:
        text=re.sub(r"<!-- PHYLUM:STATE:START -->.*?<!-- PHYLUM:STATE:END -->",block,text,flags=re.S)
    else: text += "\n\n"+block+"\n"
    # Cache-bust all generated render URLs and ensure the atlas is visible near top.
    text=re.sub(r"renders/current\.svg\?gen=[^\)\s]+",f"renders/current.svg?gen={gen:06d}",text)
    text=re.sub(r"renders/phylogeny\.svg\?gen=[^\)\s]+",f"renders/phylogeny.svg?gen={gen:06d}",text)
    if "renders/foodweb.svg" not in text:
        marker="## The idea"
        insertion=f"## Living food web\n\n![PHYLUM food web](renders/foodweb.svg?gen={gen:06d})\n\n"
        text=text.replace(marker,insertion+marker) if marker in text else text+"\n"+insertion
    else:
        text=re.sub(r"renders/foodweb\.svg\?gen=[^\)\s]+",f"renders/foodweb.svg?gen={gen:06d}",text)
    if "renders/soma.svg" not in text:
        marker="## The idea"
        insertion=f"## Living organisms — SOMA\n\n![PHYLUM SOMA field guide](renders/soma.svg?gen={gen:06d})\n\n"
        text=text.replace(marker,insertion+marker) if marker in text else text+"\n"+insertion
    else:
        text=re.sub(r"renders/soma\.svg\?gen=[^\)\s]+",f"renders/soma.svg?gen={gen:06d}",text)
    # Keep the human-facing README synchronized with the currently installed model.
    anatomy=("## Anatomy\n\n"
        "```text\n"
        "PHYLUM/\n"
        "├── .github/workflows/evolve.yml   # autonomous evolution\n"
        "├── docs/                           # generated Observatory / GitHub Pages\n"
        "├── fossils/\n"
        "│   ├── events.ndjson               # append-only event chronology\n"
        "│   ├── history.ndjson              # generation summaries\n"
        "│   ├── atlas-history.ndjson        # deep-time atlas snapshots\n"
        "│   ├── species/                    # extinct-lineage records\n"
        "│   └── checkpoints/                # periodic recovery state\n"
        "├── phylum/\n"
        "│   ├── biology.py                  # genetics, reproduction, ecology, speciation\n"
        "│   ├── branching.py                # fork identity, comparison and contact\n"
        "│   ├── disease.py                  # pathogens and immunity\n"
        "│   ├── observation.py              # WITNESS generation deltas\n"
        "│   ├── soma.py                     # organismal biology, development and field guide\n"
        "│   ├── planet.py                   # climate, geography and tectonics\n"
        "│   ├── render.py                   # atlas, phylogeny, food web and Observatory\n"
        "│   └── ...\n"
        "├── renders/\n"
        "│   ├── current.svg                 # World Atlas\n"
        "│   ├── soma.svg                    # SOMA organism field guide\n"
        "│   ├── organisms/                  # per-lineage schematic plates\n"
        "│   ├── phylogeny.svg\n"
        "│   └── foodweb.svg\n"
        "├── tests/                          # invariant + observation tests\n"
        "└── world/\n"
        "    ├── current.json\n"
        "    ├── species.json\n"
        "    ├── environment.json\n"
        "    ├── pathogens.json\n"
        "    ├── interactions.json\n"
        "    ├── plates.json\n"
        "    ├── branch.json\n"
        "    └── changes.json                # most recent generation delta\n"
        "```\n")
    if re.search(r"## Anatomy\n", text):
        text=re.sub(r"## Anatomy\n.*?(?=\n## Current model|\n## Observatory|\n## License)",anatomy+"\n",text,flags=re.S)
    else:
        anchor="\n## License"
        text=text.replace(anchor,"\n"+anatomy+anchor) if anchor in text else text+"\n\n"+anatomy

    model_text=("## Current model — SOMA\n\n"
        "PHYLUM runs **DEEP TIME** as its planetary and evolutionary engine, **WITNESS** as its observation layer, and **SOMA** as its organismal biology layer. **DEEP TIME governs the world. WITNESS records the evidence. SOMA gives the lineages bodies and lives.**\n\n"
        "SOMA adds demographic life stages, aging and lifespan, reproductive and mating systems, sexual selection, parental care, development and metamorphosis, inherited body plans, locomotion, feeding structures, sensory systems, defenses, physiology, metabolism, thermoregulation, dormancy, microbiome traits, social organization, communication, phenotypic variation, predator/prey selection pressure and emergent symbiosis. Descendants inherit organismal architecture from their ancestors, so morphology remains continuous across the phylogeny.\n\n"
        "The generated `renders/soma.svg` field guide and `docs/soma.html` catalog reconstruct every lineage from deterministic inherited state. SOMA remains population-aggregate rather than simulating every individual, preserving PHYLUM\'s ability to run for deep time in GitHub Actions.\n\n"
        "Nothing is scheduled to happen at a specific generation. PHYLUM creates conditions and lets history emerge from them.\n")
    if re.search(r"## Current model(?: — [^\n]+)?\n", text):
        text=re.sub(r"## Current model(?: — [^\n]+)?\n.*?(?=\n## Observatory|\n## License)",model_text+"\n",text,flags=re.S)
    elif "## What comes next\n" in text:
        text=re.sub(r"## What comes next\n.*?(?=\n## Observatory|\n## License)",model_text+"\n",text,flags=re.S)
    else:
        anchor="\n## Observatory" if "\n## Observatory" in text else "\n## License"
        text=text.replace(anchor,"\n"+model_text+anchor) if anchor in text else text+"\n\n"+model_text

    observatory=("## Observatory\n\n"
        "Every generation regenerates a static Observatory in `docs/`. The layered World Atlas exposes biomes, tectonics, relief, rivers, territories, migration, ecology, predator/prey contact zones, disease, current-generation events, fossils, scars, population density, biodiversity, genetics and climate.\n\n"
        "WITNESS also adds a **CHANGES** view for generation-to-generation population, range, lineage, pathogen, predation, movement and infection deltas. The Observatory retains lineage and fossil browsers, branch ancestry/contact history, event timelines and deep-time atlas snapshots. Enable GitHub Pages from the repository's `docs/` folder to turn it into a live observation station.\n\n"
        "Open the generated **SOMA Field Guide** at `docs/soma.html` for organism plates, life cycles, physiology, reproduction and behavior.\n\n"
        "Branch tools: `python -m phylum compare ../OTHER-PHYLUM` and `python -m phylum contact ../OTHER-PHYLUM`. See `PHYLUM_MERGE.md` for the biological contact rule.\n")
    if "## Observatory\n" in text:
        text=re.sub(r"## Observatory\n.*?(?=\n## License)",observatory+"\n",text,flags=re.S)
    else:
        text=text.replace("\n## License","\n"+observatory+"\n## License") if "\n## License" in text else text+"\n\n"+observatory
    README_PATH.write_text(text,encoding='utf-8')


def render_all(world: dict[str,Any], species: list[dict[str,Any]], env: dict[str,Any], pathogens: list[dict[str,Any]], plates: dict[str,Any], branch: dict[str,Any], interactions: list[dict[str,Any]]) -> None:
    svg=render_world_svg(world,species,env,pathogens,plates,branch,interactions)
    render_phylogeny_svg(world,species)
    render_foodweb_svg(world,species,interactions)
    render_soma_assets(world,species,env,interactions,Path(__file__).resolve().parents[1])
    update_readme(world,species,pathogens,interactions)
    render_observatory(world,species,env,pathogens,plates,branch,interactions,svg)

# === PALEON RENDER LAYER v2 START ===
# Keep the existing World Atlas / WITNESS / SOMA render stack intact and layer
# the DEEP TIME 2.0 planetary dossier on top of it.
import re as _paleon_re
from .paleon import render_paleon_assets as _render_paleon_assets

_paleon_legacy_update_readme = update_readme

def update_readme(world, species, pathogens, interactions):
    _paleon_legacy_update_readme(world, species, pathogens, interactions)
    gen = int(world.get("generation", 0))
    text = README_PATH.read_text(encoding="utf-8")
    if "renders/paleon.svg" not in text:
        marker = "## Living organisms — SOMA"
        insertion = f"## Planetary system — PALEON\n\n![PHYLUM PALEON planetary system](renders/paleon.svg?gen={gen:06d})\n\n"
        text = text.replace(marker, insertion + marker) if marker in text else text + "\n\n" + insertion
    else:
        text = _paleon_re.sub(r"renders/paleon\.svg\?gen=[^\)\s]+", f"renders/paleon.svg?gen={gen:06d}", text)

    model = (
        "## Current model — PALEON + SOMA\n\n"
        "PHYLUM runs **PALEON (DEEP TIME 2.0)** as its coupled planetary engine, **WITNESS** as its observation layer, and **SOMA** as its organismal biology layer. "
        "**PALEON makes the planet an evolutionary force. SOMA gives the lineages bodies and lives. WITNESS records the evidence.**\n\n"
        "PALEON adds interacting atmosphere, ocean, cryosphere, hydrology, carbon and nutrient cycles, soil fertility, ecological succession, tectonic boundary mechanics, erosion/sedimentation proxies, dynamic sea level, extreme weather and SOMA-aware life-to-planet feedback. "
        "Climate and productivity now emerge from latitude, relief, greenhouse forcing, water availability, ocean influence, nutrients and long-lived disturbances rather than a single global noise field.\n\n"
        "Life is no longer only responding to the world: autotrophy, respiration, decomposition, ecosystem engineering and aquatic productivity can slowly alter atmospheric chemistry, soils, nutrients and ocean oxygen. Those planetary changes feed back into DEEP TIME ecology and SOMA physiology.\n\n"
        "The generated `renders/paleon.svg` plate and `docs/paleon.html` dossier expose the current planetary system. Nothing is scheduled for a particular generation; thresholds, climate regimes, tectonic events and feedbacks emerge from state.\n"
    )
    if _paleon_re.search(r"## Current model(?: — [^\n]+)?\n", text):
        text = _paleon_re.sub(r"## Current model(?: — [^\n]+)?\n.*?(?=\n## Observatory|\n## License)", model + "\n", text, flags=_paleon_re.S)
    else:
        anchor = "\n## Observatory" if "\n## Observatory" in text else "\n## License"
        text = text.replace(anchor, "\n" + model + anchor) if anchor in text else text + "\n\n" + model

    # The legacy generator writes Anatomy first; upgrade just the planet section
    # after it runs so future generations cannot regress the documentation.
    if "│   ├── paleon.py" not in text:
        text = text.replace(
            "│   ├── planet.py                   # climate, geography and tectonics\n",
            "│   ├── paleon.py                   # DEEP TIME 2.0 coupled planetary engine\n"
            "│   ├── planet.py                   # compatibility surface delegated to PALEON\n",
        )
    if "│   ├── paleon.svg" not in text:
        text = text.replace(
            "│   ├── soma.svg                    # SOMA organism field guide\n",
            "│   ├── soma.svg                    # SOMA organism field guide\n"
            "│   ├── paleon.svg                  # PALEON planetary systems plate\n",
        )
    if "PALEON planetary dossier" not in text and "## Observatory\n" in text:
        text = text.replace(
            "Open the generated **SOMA Field Guide** at `docs/soma.html` for organism plates, life cycles, physiology, reproduction and behavior.\n\n",
            "Open the generated **SOMA Field Guide** at `docs/soma.html` for organism plates, life cycles, physiology, reproduction and behavior. Open the **PALEON planetary dossier** at `docs/paleon.html` for atmosphere, ocean, cryosphere, nutrient-cycle and hydrology state.\n\n",
        )
    README_PATH.write_text(text, encoding="utf-8")

_paleon_legacy_render_all = render_all

def render_all(world, species, env, pathogens, plates, branch, interactions):
    _paleon_legacy_render_all(world, species, env, pathogens, plates, branch, interactions)
    _render_paleon_assets(world, species, env, plates, Path(__file__).resolve().parents[1])
# === PALEON RENDER LAYER v2 END ===

# === NERVE RENDER LAYER v1 START ===
# NERVE is layered after PALEON/SOMA/WITNESS so older renderers remain valid.
import re as _nerve_re
from .nerve import render_nerve_assets as _render_nerve_assets

_nerve_legacy_update_readme = update_readme
def update_readme(world, species, pathogens, interactions):
    _nerve_legacy_update_readme(world, species, pathogens, interactions)
    gen = int(world.get("generation", 0))
    text = README_PATH.read_text(encoding="utf-8")
    if "renders/nerve.svg" not in text:
        marker = "## Planetary system — PALEON" if "## Planetary system — PALEON" in text else "## Living organisms — SOMA"
        insertion = f"## Living minds — NERVE\n\n![PHYLUM NERVE ethogram](renders/nerve.svg?gen={gen:06d})\n\n"
        text = text.replace(marker, insertion + marker) if marker in text else text + "\n\n" + insertion
    else:
        text = _nerve_re.sub(r"renders/nerve\.svg\?gen=[^\)\s]+", f"renders/nerve.svg?gen={gen:06d}", text)
    model = (
        "## Current model — NERVE + SOMA + PALEON\n\n"
        "PHYLUM runs **PALEON (DEEP TIME 2.0)** as its coupled planetary engine, **SOMA** as its organismal biology layer, **NERVE** as its cognition and behavior layer, and **WITNESS** as its observation system. "
        "**PALEON gives life a changing planet. SOMA gives life bodies. NERVE gives life experience. WITNESS records the evidence.**\n\n"
        "NERVE adds nervous-system complexity, perception, spatial and threat memory, learning, behavioral repertoires, temperament, social recognition, cooperation, communication complexity, cultural traditions, social transmission, costly cognition and the possibility of object-assisted behavior. Learned state persists inside a lineage but is not treated as genetic code; descendant lineages inherit cognitive architecture while cultural traditions only cross a split through founder transmission.\n\n"
        "Cognition has energetic and life-history costs, and no intelligence milestone is scheduled. Tool use, teaching, complex communication and persistent culture are possibilities produced by anatomy, ecology, selection and experience rather than guaranteed progression.\n\n"
        "The generated `renders/nerve.svg` ethogram and `docs/nerve.html` browser expose the current cognitive and behavioral state alongside the SOMA field guide and PALEON planetary dossier.\n"
    )
    if _nerve_re.search(r"## Current model(?: — [^\n]+)?\n", text):
        text = _nerve_re.sub(r"## Current model(?: — [^\n]+)?\n.*?(?=\n## Observatory|\n## License)", model + "\n", text, flags=_nerve_re.S)
    else:
        anchor = "\n## Observatory" if "\n## Observatory" in text else "\n## License"
        text = text.replace(anchor, "\n" + model + anchor) if anchor in text else text + "\n\n" + model
    if "│   ├── nerve.py" not in text:
        marker = "│   ├── paleon.py                   # DEEP TIME 2.0 coupled planetary engine\n"
        if marker in text:
            text = text.replace(marker, marker + "│   ├── nerve.py                    # cognition, memory, learning and culture\n", 1)
    if "│   ├── nerve.svg" not in text:
        marker = "│   ├── paleon.svg                  # PALEON planetary systems plate\n"
        if marker in text:
            text = text.replace(marker, marker + "│   ├── nerve.svg                   # NERVE ethogram / living minds plate\n", 1)
    if "NERVE ethogram" not in text and "## Observatory\n" in text:
        text = text.replace(
            "Open the generated **SOMA Field Guide** at `docs/soma.html` for organism plates, life cycles, physiology, reproduction and behavior.",
            "Open the generated **SOMA Field Guide** at `docs/soma.html` for organism plates, life cycles, physiology, reproduction and behavior. Open the **NERVE ethogram** at `docs/nerve.html` for cognition, memory, learned behavior and cultural traditions.",
            1,
        )
    README_PATH.write_text(text, encoding="utf-8")

_nerve_legacy_render_all = render_all
def render_all(world, species, env, pathogens, plates, branch, interactions):
    _nerve_legacy_render_all(world, species, env, pathogens, plates, branch, interactions)
    root = Path(__file__).resolve().parents[1]
    _render_nerve_assets(world, species, env, interactions, root)
    # Add NERVE to the already-generated static Observatory navigation.
    index = root / "docs" / "index.html"
    if index.exists():
        html_text = index.read_text(encoding="utf-8")
        if 'href="nerve.html"' not in html_text:
            soma_link = '<a href="soma.html" style="background:#0f2022;color:var(--text);border:1px solid #2e4743;padding:8px 11px;border-radius:6px;text-decoration:none">SOMA</a>'
            nerve_link = '<a href="nerve.html" style="background:#0f2022;color:var(--text);border:1px solid #2e4743;padding:8px 11px;border-radius:6px;text-decoration:none">NERVE</a>'
            html_text = html_text.replace(soma_link, soma_link + nerve_link, 1) if soma_link in html_text else html_text
            index.write_text(html_text, encoding="utf-8")
# === NERVE RENDER LAYER v1 END ===

# === TECHNE RENDER LAYER v1 START ===
# TECHNE layers after NERVE. It exposes cultural ancestry and material traces
# without replacing the existing WITNESS/SOMA/PALEON render chain.
import re as _techne_re
from .techne import render_techne_assets as _render_techne_assets

_techne_legacy_update_readme = update_readme
def update_readme(world, species, pathogens, interactions):
    _techne_legacy_update_readme(world, species, pathogens, interactions)
    root = Path(__file__).resolve().parents[1]
    text = README_PATH.read_text(encoding="utf-8")
    gen = int(world.get("generation", 0))
    if "renders/techne.svg" not in text:
        anchor = "## Living minds — NERVE"
        insertion = f"## Living cultures — TECHNE\n\n![PHYLUM TECHNE cultural record](renders/techne.svg?gen={gen:06d})\n\n"
        if anchor in text:
            text = text.replace(anchor, insertion + anchor, 1)
        else:
            text += "\n\n" + insertion
    else:
        text = _techne_re.sub(r"renders/techne\.svg\?gen=[^\)\s]+", f"renders/techne.svg?gen={gen:06d}", text)
    model = (
        "## Current model — TECHNE\n"
        "PHYLUM now runs a coupled stack: **PALEON / DEEP TIME 2.0** governs the planet; **SOMA** gives lineages organism-level bodies and life histories; **NERVE** gives them perception, memory, learning and social behavior; **TECHNE** allows learned information to persist as cultural lineages, material practices and archaeological sites; **WITNESS** records the evidence.\n\n"
        "TECHNE is not a civilization tech tree. Persistent nesting, caching, route marking, construction, object use, dialects and rarer material innovations require compatible NERVE cognition, SOMA anatomy, ecology and opportunity. Knowledge can diffuse between contacting populations, mutate culturally, or disappear after bottlenecks and collapse.\n\n"
        "The generated `renders/techne.svg` record and `docs/techne.html` browser expose cultural practices, dialects, living cultural lineages, active sites and ruins. No technology milestone is scheduled for a particular generation.\n"
    )
    if _techne_re.search(r"## Current model(?: — [^\n]+)?\n", text):
        text = _techne_re.sub(r"## Current model(?: — [^\n]+)?\n.*?(?=\n## Observatory|\n## License)", model + "\n", text, flags=_techne_re.S)
    if "│   ├── techne.py" not in text:
        marker = "│   ├── nerve.py                    # cognition, memory, learning and culture\n"
        if marker in text:
            text = text.replace(marker, marker + "│   ├── techne.py                   # cultural inheritance, material practices and archaeology\n", 1)
    if "│   ├── techne.svg" not in text:
        marker = "│   ├── nerve.svg                   # NERVE ethogram / living minds plate\n"
        if marker in text:
            text = text.replace(marker, marker + "│   ├── techne.svg                  # TECHNE cultural / archaeological record\n", 1)
    if "TECHNE cultural record" not in text and "## Observatory\n" in text:
        text = text.replace(
            "Open the **NERVE ethogram** at `docs/nerve.html` for cognition, memory, learned behavior and cultural traditions.",
            "Open the **NERVE ethogram** at `docs/nerve.html` for cognition, memory, learned behavior and cultural traditions. Open the **TECHNE cultural record** at `docs/techne.html` for practices, dialects, cultural phylogeny and archaeological sites.",
            1,
        )
    README_PATH.write_text(text, encoding="utf-8")

_techne_legacy_render_all = render_all
def render_all(world, species, env, pathogens, plates, branch, interactions):
    _techne_legacy_render_all(world, species, env, pathogens, plates, branch, interactions)
    root = Path(__file__).resolve().parents[1]
    _render_techne_assets(world, species, root)
    index = root / "docs" / "index.html"
    if index.exists():
        html_text = index.read_text(encoding="utf-8")
        if 'href="techne.html"' not in html_text:
            nerve_link = '<a href="nerve.html" style="background:#0f2022;color:var(--text);border:1px solid #2e4743;padding:8px 11px;border-radius:6px;text-decoration:none">NERVE</a>'
            techne_link = '<a href="techne.html" style="background:#0f2022;color:var(--text);border:1px solid #2e4743;padding:8px 11px;border-radius:6px;text-decoration:none">TECHNE</a>'
            html_text = html_text.replace(nerve_link, nerve_link + techne_link, 1) if nerve_link in html_text else html_text
            index.write_text(html_text, encoding="utf-8")
# === TECHNE RENDER LAYER v1 END ===

