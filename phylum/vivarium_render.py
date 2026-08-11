from __future__ import annotations

import colorsys
import html
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .constants import GRID_COLS, GRID_ROWS
from .vivarium import load_vivarium_state, vivarium_summary


def _esc(v: Any) -> str:
    return html.escape(str(v))


def render_vivarium_assets(world: dict[str, Any], species: list[dict[str, Any]], root: Path) -> None:
    state, agents, cohorts, eco = load_vivarium_state()
    summary = vivarium_summary(world, species)
    living = [a for a in agents if a.get("alive", True)]
    by_sid = {str(s.get("id")): s for s in species}
    last = state.get("last_checkpoint", {})
    W, H = 1800, 1080
    map_x, map_y, map_w, map_h = 48, 170, 1110, 690
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
             '<rect width="100%" height="100%" fill="#071014"/>',
             '<style>text{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;fill:#dce8e2}.muted{fill:#748a82}.tiny{font-size:13px}.small{font-size:16px}.label{font-size:12px;letter-spacing:2px}.metric{font-size:30px}.title{font-size:24px;letter-spacing:6px}.panel{fill:#0b1619;stroke:#263b38;stroke-width:1}.line{stroke:#263b38;stroke-width:1}</style>',
             f'<text x="48" y="54" class="title">PHYLUM / VIVARIUM</text>',
             f'<text x="48" y="86" class="muted small">CONTINUOUS LIVING-WORLD ENGINE · OBSERVATION {int(world.get("generation",0)):06d} · YEAR {float(summary.get("sim_year",0)):.2f}</text>',
             f'<text x="48" y="125" class="small">{int(summary.get("explicit_organisms",0))} explicit organisms · {int(summary.get("cohorts",0))} bounded cohorts · {int(summary.get("conceptual_population",0)):,} conceptual organisms</text>',
             f'<rect x="{map_x}" y="{map_y}" width="{map_w}" height="{map_h}" rx="8" class="panel"/>']
    # cartographic grid
    for x in range(GRID_COLS + 1):
        px = map_x + x / GRID_COLS * map_w
        if x % 4 == 0: parts.append(f'<line x1="{px:.1f}" y1="{map_y}" x2="{px:.1f}" y2="{map_y+map_h}" class="line" opacity=".35"/>')
    for y in range(GRID_ROWS + 1):
        py = map_y + y / GRID_ROWS * map_h
        if y % 3 == 0: parts.append(f'<line x1="{map_x}" y1="{py:.1f}" x2="{map_x+map_w}" y2="{py:.1f}" class="line" opacity=".35"/>')
    # cohort circles first
    max_count = max([float(c.get("count",0)) for c in cohorts] or [1])
    for c in cohorts:
        n=float(c.get("count",0))
        if n<=0: continue
        x,y=int(c.get("cell",[0,0])[0]),int(c.get("cell",[0,0])[1]); cx=map_x+(x+.5)/GRID_COLS*map_w; cy=map_y+(y+.5)/GRID_ROWS*map_h; r=2.5+12*(n/max_count)**.5
        sid=str(c.get("species_id")); hue=stable_hue(sid)
        parts.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="{hsl_hex(hue,34,44)}" opacity=".22" stroke="{hsl_hex(hue,42,62)}" stroke-width="1"/>')
    # explicit organisms
    for a in living[:1400]:
        x,y=int(a.get("cell",[0,0])[0]),int(a.get("cell",[0,0])[1]); jitter=(int(str(a.get("id","0")).split("-")[-1])%97)/97.0
        cx=map_x+(x+.18+.62*jitter)/GRID_COLS*map_w; cy=map_y+(y+.18+.62*((jitter*1.71)%1))/GRID_ROWS*map_h; sid=str(a.get("species_id")); hue=stable_hue(sid)
        health=float(a.get("health",1)); rad=1.8+float(a.get("genes",{}).get("body_size",1))**.2
        parts.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{rad:.2f}" fill="{hsl_hex(hue,55,48+health*20)}" opacity=".94"><title>{_esc(a.get("id"))} · {_esc(by_sid.get(sid,{}).get("name",sid))} · energy {float(a.get("energy",0))*100:.0f}% · health {health*100:.0f}%</title></circle>')
    # right metrics
    px=1200
    parts.append(f'<rect x="{px}" y="170" width="552" height="690" rx="8" class="panel"/>')
    metrics=[("SIMULATED DAYS",f'{float(summary.get("sim_day",0)):,.0f}'),("CHECKPOINT SPAN",f'{int(last.get("simulated_days",0))} days'),("BIRTHS",f'{float(last.get("births",0)):,.1f}'),("DEATHS",f'{float(last.get("deaths",0)):,.1f}'),("PREDATION",f'{float(last.get("observed_predation",0)):,.1f}')]
    y=220
    for label,value in metrics:
        parts.append(f'<text x="{px+28}" y="{y}" class="muted label">{label}</text><text x="{px+28}" y="{y+38}" class="metric">{value}</text>'); y+=92
    parts.append(f'<text x="{px+28}" y="{y+5}" class="muted label">DEATH CAUSES</text>'); y+=32
    for cause,n in list((last.get("death_causes") or {}).items())[:6]:
        parts.append(f'<text x="{px+28}" y="{y}" class="small">{_esc(cause):18s}</text><text x="{px+410}" y="{y}" class="small" text-anchor="end">{float(n):,.1f}</text>'); y+=29
    # specimen strip
    parts.append('<text x="48" y="905" class="muted label">LIVING SPECIMENS / INDIVIDUAL STATE</text>')
    for i,a in enumerate(living[:6]):
        x=48+i*284; y=930; sid=str(a.get("species_id")); sp=by_sid.get(sid,{})
        parts.append(f'<rect x="{x}" y="{y}" width="264" height="112" rx="6" class="panel"/>')
        parts.append(f'<text x="{x+14}" y="{y+23}" class="tiny muted">{_esc(a.get("id"))} / {_esc(a.get("stage"))}</text>')
        parts.append(f'<text x="{x+14}" y="{y+48}" class="small">{_esc(sp.get("name",sid))}</text>')
        parts.append(f'<text x="{x+14}" y="{y+73}" class="tiny">age {float(a.get("age_days",0)):.0f}d · energy {float(a.get("energy",0))*100:.0f}% · health {float(a.get("health",0))*100:.0f}%</text>')
        parents=a.get("parent_ids",[]); parts.append(f'<text x="{x+14}" y="{y+96}" class="tiny muted">parents {_esc(" / ".join(parents) if parents else "migration founder")}</text>')
    parts.append('</svg>')
    svg=''.join(parts)
    (root/'renders').mkdir(parents=True,exist_ok=True); (root/'docs').mkdir(parents=True,exist_ok=True)
    (root/'renders'/'vivarium.svg').write_text(svg,encoding='utf-8'); (root/'docs'/'vivarium.svg').write_text(svg,encoding='utf-8')
    data={"summary":summary,"organisms":living[:220],"cohorts":cohorts[:220],"last_checkpoint":last}
    (root/'docs'/'vivarium-data.json').write_text(json.dumps(data,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    html_doc=f'''<!doctype html><html><head><meta charset="utf-8"><title>PHYLUM / VIVARIUM</title><style>body{{margin:0;background:#071014;color:#dce8e2;font:14px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}main{{max-width:1800px;margin:auto;padding:22px}}a{{color:#9bb8aa}}object{{width:100%;border:1px solid #263b38;border-radius:8px}}pre{{background:#0b1619;border:1px solid #263b38;padding:16px;overflow:auto}}</style></head><body><main><p><a href="index.html">← ORRERY</a></p><h1>VIVARIUM / LIVING WORLD</h1><p>Species statistics are measured from explicit organisms and bounded cohorts. Observation checkpoints advance continuous simulated days.</p><object type="image/svg+xml" data="vivarium.svg?world={int(world.get('generation',0)):06d}"></object><h2>Engine state</h2><pre>{_esc(json.dumps(summary,indent=2))}</pre></main></body></html>'''
    (root/'docs'/'vivarium.html').write_text(html_doc,encoding='utf-8')


def hsl_hex(h: float, s: float, l: float) -> str:
    r, g, b = colorsys.hls_to_rgb((float(h) % 360.0) / 360.0, max(0.0, min(100.0, float(l))) / 100.0, max(0.0, min(100.0, float(s))) / 100.0)
    return f"#{round(r*255):02x}{round(g*255):02x}{round(b*255):02x}"


def stable_hue(value: str) -> int:
    return sum((i+1)*ord(ch) for i,ch in enumerate(value)) % 360
