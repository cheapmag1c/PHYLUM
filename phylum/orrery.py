from __future__ import annotations

import colorsys
import html
import json
import math
import shutil
from pathlib import Path
from typing import Any

from .biology import normalize_range, trophic_role
from .constants import BIOME_LABELS, GRID_COLS, GRID_ROWS, MAP_SAMPLE_COLS, MAP_SAMPLE_ROWS
from .planet import biome_at, cell_world_xy, geography_at, plate_at
from .socius import ensure_world_socius, socius_catalog
from .storage import CHANGES_PATH, EVENTS_PATH, README_PATH, load_json, read_ndjson
from .utils import clamp, mean, stable_int

ORRERY_VERSION = 1

BIOME_COLORS = {
    "abyss": "#071118", "shelf": "#102934", "ice": "#a8b8b8", "tundra": "#596968",
    "alpine": "#6a6661", "desert": "#736348", "steppe": "#576144", "temperate": "#324b3b",
    "wetland": "#284b4a", "rainforest": "#214538", "barren": "#514e47",
}

SITE_GLYPHS = {
    "nest-site": "△", "cache-site": "◇", "route-marker": "·", "tool-site": "◆",
    "shelter": "⌂", "waterwork": "≈", "tended-patch": "✣", "hearth": "⊙",
    "workshop": "▣", "symbolic-site": "✦",
}


def _esc(v: Any) -> str:
    return html.escape(str(v), quote=True)


def _species_color(sp: dict[str, Any]) -> tuple[str, str, str]:
    h = (stable_int(sp.get("id", sp.get("name", "x"))) % 360) / 360.0
    r, g, b = colorsys.hls_to_rgb(h, 0.63, 0.56)
    base = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
    r2, g2, b2 = colorsys.hls_to_rgb(h, 0.35, 0.48)
    dark = f"#{int(r2*255):02x}{int(g2*255):02x}{int(b2*255):02x}"
    r3, g3, b3 = colorsys.hls_to_rgb(h, 0.79, 0.64)
    pale = f"#{int(r3*255):02x}{int(g3*255):02x}{int(b3*255):02x}"
    return base, dark, pale


def _map_xy(cell: tuple[float, float] | list[float], mx: float, my: float, mw: float, mh: float) -> tuple[float, float]:
    return mx + (float(cell[0]) + 0.5) / GRID_COLS * mw, my + (float(cell[1]) + 0.5) / GRID_ROWS * mh


def _centroid_cells(cells: set[tuple[int, int]]) -> tuple[float, float]:
    if not cells:
        return (GRID_COLS / 2, GRID_ROWS / 2)
    return (sum(x for x, _ in cells) / len(cells), sum(y for _, y in cells) / len(cells))


def _species_centroid(sp: dict[str, Any]) -> tuple[float, float]:
    return _centroid_cells(normalize_range(sp))


def _group_cells(group: dict[str, Any]) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for row in group.get("territory", []):
        if isinstance(row, (list, tuple)) and len(row) == 2:
            try:
                x, y = int(row[0]), int(row[1])
            except (TypeError, ValueError):
                continue
            if 0 <= x < GRID_COLS and 0 <= y < GRID_ROWS:
                out.add((x, y))
    return out


def _cell_blob(cells: set[tuple[int, int]], mx: float, my: float, mw: float, mh: float, color: str, opacity: float, stroke: str | None = None, dash: str | None = None, radius_scale: float = 0.72) -> str:
    if not cells:
        return ""
    cw, ch = mw / GRID_COLS, mh / GRID_ROWS
    rr = min(cw, ch) * radius_scale
    paths = []
    links = []
    for x, y in sorted(cells):
        cx, cy = _map_xy((x, y), mx, my, mw, mh)
        jitter = ((stable_int(f"orrery:{x}:{y}:{color}") % 100) / 100 - 0.5) * 0.08
        r = rr * (1 + jitter)
        paths.append(f"M{cx-r:.1f},{cy:.1f}a{r:.1f},{r:.1f} 0 1,0 {r*2:.1f},0a{r:.1f},{r:.1f} 0 1,0 {-r*2:.1f},0")
        for n in ((x+1, y), (x, y+1)):
            if n in cells:
                x2, y2 = _map_xy(n, mx, my, mw, mh)
                links.append(f"M{cx:.1f},{cy:.1f}L{x2:.1f},{y2:.1f}")
    attrs = f' stroke="{stroke or color}" stroke-width="0.8"'
    if dash:
        attrs += f' stroke-dasharray="{dash}"'
    link_svg = f'<path d="{" ".join(links)}" fill="none" stroke="{color}" stroke-width="{rr*1.45:.2f}" stroke-linecap="round" opacity="{opacity*0.75:.3f}"/>' if links else ""
    return link_svg + f'<path d="{" ".join(paths)}" fill="{color}" opacity="{opacity:.3f}"{attrs}/>'


def _terrain_layers(world: dict[str, Any], env: dict[str, Any], plates: dict[str, Any], mx: float, my: float, mw: float, mh: float) -> str:
    seed = int(world.get("seed", 0))
    sw, sh = mw / MAP_SAMPLE_COLS, mh / MAP_SAMPLE_ROWS
    biome_paths = {k: [] for k in BIOME_COLORS}
    shade_paths: dict[int, list[str]] = {0: [], 1: [], 2: [], 3: []}
    for gy in range(MAP_SAMPLE_ROWS):
        wy = (gy + 0.5) / MAP_SAMPLE_ROWS * float(env.get("height", 100))
        for gx in range(MAP_SAMPLE_COLS):
            wx = (gx + 0.5) / MAP_SAMPLE_COLS * float(env.get("width", 160))
            biome = biome_at(env, plates, wx, wy, seed)
            geo = geography_at(env, plates, wx, wy, seed)
            xx = mx + gx * sw
            yy = my + gy * sh
            path = f"M{xx:.1f},{yy:.1f}h{sw+0.45:.1f}v{sh+0.45:.1f}h{-sw-0.45:.1f}Z"
            biome_paths.setdefault(biome, []).append(path)
            elev = float(geo.get("elevation", 0.5))
            band = 3 if elev > 0.78 else 2 if elev > 0.63 else 1 if elev > 0.50 else 0
            shade_paths[band].append(path)
    parts = ['<g id="layer-biomes">']
    for biome, rows in biome_paths.items():
        if rows:
            parts.append(f'<path d="{"".join(rows)}" fill="{BIOME_COLORS.get(biome, "#444")}"/>')
    parts.append('</g><g id="layer-relief" pointer-events="none">')
    shade = {0: ("#021016", 0.10), 1: ("#d7e0d9", 0.025), 2: ("#e6dfca", 0.050), 3: ("#efe6d1", 0.085)}
    for band, rows in shade_paths.items():
        if rows:
            col, op = shade[band]
            parts.append(f'<path d="{"".join(rows)}" fill="{col}" opacity="{op}"/>')
    parts.append('</g>')
    return ''.join(parts)


def _plate_layer(world: dict[str, Any], env: dict[str, Any], plates: dict[str, Any], mx: float, my: float, mw: float, mh: float) -> str:
    cw, ch = mw / GRID_COLS, mh / GRID_ROWS
    pids = {}
    for gy in range(GRID_ROWS):
        for gx in range(GRID_COLS):
            wx, wy = cell_world_xy((gx, gy), env)
            pids[(gx, gy)] = plate_at(plates, wx, wy, env).get("id")
    lines = []
    for gy in range(GRID_ROWS):
        for gx in range(GRID_COLS):
            pid = pids[(gx, gy)]
            if gx + 1 < GRID_COLS and pids[(gx+1, gy)] != pid:
                x = mx + (gx + 1) * cw; y = my + gy * ch
                lines.append(f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x:.1f}" y2="{y+ch:.1f}"/>')
            if gy + 1 < GRID_ROWS and pids[(gx, gy+1)] != pid:
                x = mx + gx * cw; y = my + (gy + 1) * ch
                lines.append(f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x+cw:.1f}" y2="{y:.1f}"/>')
    return '<g id="layer-plates" stroke="#ad8063" stroke-width="0.9" stroke-dasharray="2 5" opacity="0.42">' + ''.join(lines) + '</g>'


def _contours(world: dict[str, Any], env: dict[str, Any], plates: dict[str, Any], mx: float, my: float, mw: float, mh: float) -> str:
    seed = int(world.get("seed", 0))
    cw, ch = mw / GRID_COLS, mh / GRID_ROWS
    elevations = {}
    for gy in range(GRID_ROWS):
        for gx in range(GRID_COLS):
            wx, wy = cell_world_xy((gx, gy), env)
            elevations[(gx, gy)] = float(geography_at(env, plates, wx, wy, seed).get("elevation", 0.5))
    lines = []
    for gy in range(GRID_ROWS - 1):
        for gx in range(GRID_COLS - 1):
            v = elevations[(gx, gy)]
            for level in (0.46, 0.58, 0.70, 0.82):
                right = elevations[(gx+1, gy)]
                down = elevations[(gx, gy+1)]
                if (v-level) * (right-level) < 0:
                    x = mx + (gx + 1) * cw; y = my + gy * ch
                    lines.append(f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x:.1f}" y2="{y+ch:.1f}"/>')
                if (v-level) * (down-level) < 0:
                    x = mx + gx * cw; y = my + (gy + 1) * ch
                    lines.append(f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x+cw:.1f}" y2="{y:.1f}"/>')
    return '<g id="layer-contours" stroke="#c9d0c8" stroke-width="0.42" opacity="0.20">' + ''.join(lines) + '</g>'


def _social_layer(world: dict[str, Any], species: list[dict[str, Any]], mx: float, my: float, mw: float, mh: float) -> str:
    ws = ensure_world_socius(world)
    by_id = {str(s.get("id")): s for s in species if s.get("id")}
    parts = ['<g id="layer-social">']
    for g in ws.get("groups", []):
        sp = by_id.get(str(g.get("species_id")))
        if not sp:
            continue
        base, dark, pale = _species_color(sp)
        cells = _group_cells(g)
        if cells:
            parts.append(_cell_blob(cells, mx, my, mw, mh, pale, 0.09, stroke=pale, dash="5 4", radius_scale=0.57))
        centroid = g.get("centroid")
        if centroid:
            x, y = _map_xy(centroid, mx, my, mw, mh)
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8.5" fill="#071012" stroke="{pale}" stroke-width="1.2"/><text x="{x:.1f}" y="{y+3.6:.1f}" text-anchor="middle" class="micro" fill="{pale}">S</text>')
            parts.append(f'<text x="{x+12:.1f}" y="{y-8:.1f}" class="micro" fill="{pale}">{_esc(g.get("name"))}</text>')
    # Relationship arcs.
    groups = {str(g.get("id")): g for g in ws.get("groups", [])}
    for rel in sorted(ws.get("relationships", []), key=lambda r: abs(float(r.get("value", 0))), reverse=True)[:36]:
        a, b = groups.get(str(rel.get("a"))), groups.get(str(rel.get("b")))
        if not a or not b or not a.get("centroid") or not b.get("centroid"):
            continue
        x1, y1 = _map_xy(a["centroid"], mx, my, mw, mh)
        x2, y2 = _map_xy(b["centroid"], mx, my, mw, mh)
        value = float(rel.get("value", 0))
        col = "#9cc6b3" if value >= 0 else "#d38b77"
        op = 0.18 + min(0.65, abs(value) * 0.55)
        dash = "" if value >= 0 else ' stroke-dasharray="4 5"'
        parts.append(f'<path d="M{x1:.1f},{y1:.1f} Q{(x1+x2)/2:.1f},{min(y1,y2)-18:.1f} {x2:.1f},{y2:.1f}" fill="none" stroke="{col}" stroke-width="{0.8+abs(value)*1.7:.2f}" opacity="{op:.2f}"{dash}/>')
    parts.append('</g>')
    return ''.join(parts)


def _site_layer(world: dict[str, Any], mx: float, my: float, mw: float, mh: float) -> str:
    techne = world.get("techne", {}) if isinstance(world.get("techne"), dict) else {}
    parts = ['<g id="layer-sites">']
    for site in techne.get("sites", [])[-120:]:
        pos = site.get("position")
        if not pos:
            continue
        x, y = _map_xy(pos, mx, my, mw, mh)
        active = bool(site.get("active", False))
        col = "#d7c78f" if active else "#807a70"
        glyph = SITE_GLYPHS.get(str(site.get("kind")), "·")
        parts.append(f'<g><title>{_esc(site.get("kind"))}: {_esc(site.get("practice"))}</title><circle cx="{x:.1f}" cy="{y:.1f}" r="7.8" fill="#071012" stroke="{col}" stroke-width="1" opacity="0.94"/><text x="{x:.1f}" y="{y+3.6:.1f}" text-anchor="middle" class="micro" fill="{col}">{_esc(glyph)}</text></g>')
    parts.append('</g>')
    return ''.join(parts)


def _disease_layer(species: list[dict[str, Any]], mx: float, my: float, mw: float, mh: float) -> str:
    parts = ['<g id="layer-disease">']
    for sp in species:
        if sp.get("extinct_generation") is not None:
            continue
        prevalence = max([float(v) for v in sp.get("infections", {}).values()] or [0.0])
        if prevalence < 0.006:
            continue
        x, y = _map_xy(_species_centroid(sp), mx, my, mw, mh)
        rr = 13 + prevalence * 48
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rr:.1f}" fill="#d15f69" opacity="{0.05+prevalence*0.12:.2f}" stroke="#e57a82" stroke-width="1.8" stroke-dasharray="6 5"/><text x="{x:.1f}" y="{y+rr+12:.1f}" text-anchor="middle" class="micro" fill="#e99aa0">PATHOGEN {prevalence*100:.1f}%</text>')
    parts.append('</g>')
    return ''.join(parts)


def _event_layer(world: dict[str, Any], mx: float, my: float, mw: float, mh: float) -> str:
    changes = load_json(CHANGES_PATH, {}) or {}
    gen = int(world.get("generation", 0))
    if int(changes.get("to_generation", -1)) != gen:
        changes = {}
    colors = {
        "migration":"#b9d4c5","speciation":"#d8c080","extinction":"#a79a98","disease":"#e1747d","pandemic":"#f05d67",
        "disaster":"#e09a66","mass_extinction":"#ff725f","tectonic":"#c99a6c","climate":"#79a9bb","contact":"#c7a5d8","era":"#e1cf8d",
        "group_formation":"#9fc6b2","group_fission":"#b8d8c9","social_collapse":"#b78078","social_relation":"#9bb8d2","social_norm":"#d2c18f",
        "innovation":"#d4b86c","construction":"#d3bd85","artifact":"#9b9487","cultural_exchange":"#b7a4d3","knowledge_loss":"#b27e7b",
    }
    parts = ['<g id="layer-events">']
    for marker in changes.get("markers", [])[:28]:
        pos = marker.get("position")
        if not pos:
            continue
        x, y = _map_xy(pos, mx, my, mw, mh)
        kind = str(marker.get("kind", "event"))
        col = colors.get(kind, "#d7e2dd")
        glyph = _esc(marker.get("glyph", "•"))
        parts.append(f'<g><title>{_esc(marker.get("text",""))}</title><circle cx="{x:.1f}" cy="{y:.1f}" r="9.2" fill="#061012" stroke="{col}" stroke-width="1.4"/><text x="{x:.1f}" y="{y+3.6:.1f}" text-anchor="middle" class="micro" fill="{col}">{glyph}</text></g>')
    parts.append('</g>')
    return ''.join(parts)


def render_world_orrery(world: dict[str, Any], species: list[dict[str, Any]], env: dict[str, Any], pathogens: list[dict[str, Any]], plates: dict[str, Any], branch: dict[str, Any], interactions: list[dict[str, Any]], output_path: Path) -> str:
    W, H = 1800, 1160
    mx, my, mw, mh = 48, 148, 1240, 760
    sx = 1320
    live = [s for s in species if s.get("extinct_generation") is None and float(s.get("population", 0)) > 0]
    dead = [s for s in species if s.get("extinct_generation") is not None]
    total = int(sum(float(s.get("population", 0)) for s in live))
    occupied = len(set().union(*(normalize_range(s) for s in live))) if live else 0
    gen = int(world.get("generation", 0))
    era = world.get("era", {}).get("name", "Origin Era")
    ws = ensure_world_socius(world)
    techne = world.get("techne", {}) if isinstance(world.get("techne"), dict) else {}
    active_pathogens = len([p for p in pathogens if p.get("extinct_generation") is None])
    parts = [f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="PHYLUM ORRERY observatory generation {gen}">
<defs>
<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#04090b"/><stop offset="1" stop-color="#0a1113"/></linearGradient>
<linearGradient id="panel" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#091216"/><stop offset="1" stop-color="#0c1719"/></linearGradient>
<filter id="soft"><feGaussianBlur stdDeviation="3"/></filter>
<style>
text{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;fill:#dbe5e1}} .muted{{fill:#718680}} .micro{{font-size:9px}} .tiny{{font-size:11px}} .small{{font-size:13px}} .label{{font-size:12px;letter-spacing:1.8px}} .metric{{font-size:25px;font-weight:600}} .hair{{stroke:#203234;stroke-width:1}} .panel{{fill:url(#panel);stroke:#223638;stroke-width:1}}
</style></defs><rect width="100%" height="100%" fill="url(#bg)"/>
<text x="48" y="52" font-size="28" letter-spacing="6">PHYLUM / ORRERY</text><text x="48" y="84" class="small muted">AUTONOMOUS DEEP-TIME OBSERVATORY · GEN {gen:06d} · {_esc(str(era).upper())}</text>
<text x="1752" y="52" text-anchor="end" class="small">{len(live)} LIVING · {len(dead)} EXTINCT · {total:,} ORGANISMS</text><text x="1752" y="78" text-anchor="end" class="tiny muted">{occupied} OCCUPIED CELLS · {active_pathogens} PATHOGENS · {len(plates.get('plates',[]))} PLATES · {len(ws.get('groups',[]))} SOCIAL GROUPS</text>
<rect x="{mx}" y="{my}" width="{mw}" height="{mh}" rx="14" fill="#061014" stroke="#2a3f40"/>
''']
    parts.append(_terrain_layers(world, env, plates, mx, my, mw, mh))
    parts.append(_contours(world, env, plates, mx, my, mw, mh))
    parts.append(_plate_layer(world, env, plates, mx, my, mw, mh))
    # Survey grid.
    parts.append('<g id="layer-grid" opacity="0.16" stroke="#78908a" stroke-width="0.55">')
    for i in range(1, 12):
        x = mx + i * mw / 12
        parts.append(f'<line x1="{x:.1f}" y1="{my}" x2="{x:.1f}" y2="{my+mh}"/>')
    for i in range(1, 8):
        y = my + i * mh / 8
        parts.append(f'<line x1="{mx}" y1="{y:.1f}" x2="{mx+mw}" y2="{y:.1f}"/>')
    parts.append('</g>')
    # Fossil ghost ranges first.
    parts.append('<g id="layer-fossils">')
    for sp in dead[-20:]:
        cells = {(int(c[0]), int(c[1])) for c in sp.get("last_range", []) if isinstance(c, list) and len(c) == 2}
        if cells:
            _, _, pale = _species_color(sp)
            parts.append(_cell_blob(cells, mx, my, mw, mh, pale, 0.035, stroke=pale, dash="2 4", radius_scale=0.56))
    parts.append('</g>')
    # Living species ranges.
    parts.append('<g id="layer-ranges">')
    for sp in sorted(live, key=lambda s: float(s.get("population", 0)), reverse=True):
        base, dark, pale = _species_color(sp)
        cells = normalize_range(sp)
        parts.append(_cell_blob(cells, mx, my, mw, mh, base, 0.19, stroke=dark, radius_scale=0.64))
        # Range core is shown as a smaller luminous kernel.
        cx, cy = _map_xy(_species_centroid(sp), mx, my, mw, mh)
        core = clamp(math.log1p(float(sp.get("population", 0))) * 1.35, 5, 14)
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{core:.1f}" fill="{pale}" opacity="0.16" filter="url(#soft)"/><circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.2" fill="{pale}"/>')
    parts.append('</g>')
    parts.append(_social_layer(world, species, mx, my, mw, mh))
    parts.append(_site_layer(world, mx, my, mw, mh))
    parts.append(_disease_layer(species, mx, my, mw, mh))
    parts.append(_event_layer(world, mx, my, mw, mh))
    # Species labels.
    parts.append('<g id="layer-labels">')
    for idx, sp in enumerate(sorted(live, key=lambda s: float(s.get("population", 0)), reverse=True)[:18]):
        cx, cy = _map_xy(_species_centroid(sp), mx, my, mw, mh)
        _, _, pale = _species_color(sp)
        side = -1 if cx > mx + mw * 0.70 else 1
        lx = cx + side * (24 + (idx % 4) * 5)
        ly = cy - 18 - (idx % 3) * 7
        anchor = "end" if side < 0 else "start"
        parts.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{lx:.1f}" y2="{ly:.1f}" stroke="{pale}" opacity="0.40" stroke-width="0.7"/>')
        parts.append(f'<text x="{lx+side*4:.1f}" y="{ly:.1f}" text-anchor="{anchor}" class="small" fill="{pale}">{_esc(sp.get("name"))}</text><text x="{lx+side*4:.1f}" y="{ly+14:.1f}" text-anchor="{anchor}" class="micro muted">{int(sp.get("population",0)):,} · {_esc(trophic_role(sp))}</text>')
    parts.append('</g>')
    # Map chrome.
    parts.append(f'<text x="{mx+18}" y="{my+28}" class="label">WORLD / COMPOSITE</text><text x="{mx+18}" y="{my+47}" class="micro muted">BIOME + RELIEF + PLATES + LIFE + CULTURE + SOCIETY + EVENTS</text>')
    parts.append(f'<g transform="translate({mx+mw-38},{my+42})"><circle r="20" fill="#061014" stroke="#657b75"/><path d="M0,-14 L4,2 L0,-1 L-4,2 Z" fill="#d6dfdb"/><text y="-25" text-anchor="middle" class="micro">N</text></g>')
    # Sidebar cards.
    parts.append(f'<rect x="{sx}" y="148" width="432" height="760" rx="14" class="panel"/>')
    parts.append(f'<text x="{sx+24}" y="182" class="label">CURRENT STATE</text>')
    metrics = [("POPULATION", f"{total:,}"), ("LIVING", str(len(live))), ("GROUPS", str(len(ws.get("groups", [])))), ("SITES", str(len(techne.get("sites", [])))), ("PATHOGENS", str(active_pathogens)), ("DIVERSITY", f"{mean(float(s.get('genetic_diversity',0)) for s in live):.2f}")]
    for i, (lab, val) in enumerate(metrics):
        col = i % 2; row = i // 2; x = sx + 24 + col * 196; y = 215 + row * 70
        parts.append(f'<text x="{x}" y="{y}" class="micro muted">{lab}</text><text x="{x}" y="{y+29}" class="metric">{_esc(val)}</text>')
    # Layer health.
    y0 = 452
    parts.append(f'<text x="{sx+24}" y="{y0}" class="label">STACK / LIVE LAYERS</text>')
    layer_rows = [
        ("PALEON", float(env.get("resources", 0)), "planet"),
        ("SOMA", mean(float(s.get("soma", {}).get("physiology", {}).get("plasticity", 0)) for s in live), "body"),
        ("NERVE", mean(float(s.get("nerve", {}).get("architecture", {}).get("neural_complexity", 0)) for s in live), "experience"),
        ("TECHNE", mean(float(s.get("techne", {}).get("capacities", {}).get("cultural_storage", 0)) for s in live), "knowledge"),
        ("SOCIUS", mean(float(s.get("socius", {}).get("capacities", {}).get("group_persistence", 0)) for s in live), "society"),
    ]
    for i, (lab, val, desc) in enumerate(layer_rows):
        y = y0 + 30 + i * 38
        parts.append(f'<text x="{sx+24}" y="{y}" class="tiny">{lab}</text><rect x="{sx+104}" y="{y-10}" width="214" height="8" rx="4" fill="#182628"/><rect x="{sx+104}" y="{y-10}" width="{214*clamp(val,0,1):.1f}" height="8" rx="4" fill="#88a99c"/><text x="{sx+330}" y="{y}" class="micro muted">{desc}</text>')
    # Social summary.
    y1 = 688
    parts.append(f'<text x="{sx+24}" y="{y1}" class="label">SOCIUS</text>')
    if ws.get("groups"):
        top = sorted(ws.get("groups", []), key=lambda g: float(g.get("population_share", 0)), reverse=True)[:3]
        for i, g in enumerate(top):
            y = y1 + 28 + i * 49
            sp = next((s for s in species if str(s.get("id")) == str(g.get("species_id"))), {})
            _, _, pale = _species_color(sp or {"id": g.get("species_id")})
            parts.append(f'<circle cx="{sx+30}" cy="{y-4}" r="4" fill="{pale}"/><text x="{sx+44}" y="{y}" class="tiny">{_esc(g.get("name"))}</text><text x="{sx+44}" y="{y+15}" class="micro muted">{_esc(sp.get("name","unknown"))} · {_esc(g.get("leadership","diffuse"))} · {float(g.get("population_share",0))*100:.1f}%</text>')
    else:
        parts.append(f'<text x="{sx+24}" y="{y1+32}" class="small muted">No persistent social groups yet.</text><text x="{sx+24}" y="{y1+53}" class="micro muted">SOCIUS remains active and opportunity-gated.</text>')
    # Footer timeline and layer legend.
    recent = read_ndjson(EVENTS_PATH, 10)
    fy = 958
    parts.append(f'<line x1="48" y1="936" x2="1752" y2="936" class="hair"/><text x="48" y="{fy}" class="label">WITNESS / RECENT HISTORY</text>')
    for i, e in enumerate(recent[-6:]):
        parts.append(f'<text x="48" y="{fy+26+i*25}" class="tiny"><tspan class="muted">{int(e.get("generation",0)):06d} / {_esc(str(e.get("kind","event")).upper())}</tspan><tspan dx="14">{_esc(e.get("text",""))[:158]}</tspan></text>')
    lx = 1320
    parts.append(f'<text x="{lx}" y="{fy}" class="label">VISIBLE LAYERS</text>')
    legend = [("TERRAIN", "biome + relief"), ("RANGES", "species occupation"), ("SOCIAL", "groups + relations"), ("SITES", "TECHNE material traces"), ("DISEASE", "active infection"), ("EVENTS", "current WITNESS markers")]
    for i, (a, b) in enumerate(legend):
        parts.append(f'<text x="{lx}" y="{fy+26+i*25}" class="tiny"><tspan fill="#b9cbc4">{a}</tspan><tspan dx="12" class="muted">{b}</tspan></text>')
    parts.append('</svg>')
    svg = ''.join(parts)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(svg, encoding="utf-8")
    return svg


def render_phylogeny_orrery(world: dict[str, Any], species: list[dict[str, Any]], output_path: Path) -> str:
    rows = sorted(species, key=lambda s: (int(s.get("born_generation", 0)), str(s.get("id"))))
    gen = int(world.get("generation", 0))
    W = 1800
    H = max(760, 170 + len(rows) * 34)
    left, right = 240, 1720
    xspan = right - left
    maxg = max(gen, max([int(s.get("born_generation", 0)) for s in rows] or [1]), 1)
    ymap = {str(sp.get("id")): 138 + i * 34 for i, sp in enumerate(rows)}
    byid = {str(s.get("id")): s for s in rows}
    parts = [f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}"><defs><style>text{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;fill:#dbe5e1}} .muted{{fill:#70847f}} .tiny{{font-size:10px}} .small{{font-size:12px}} .hair{{stroke:#223437;stroke-width:1}}</style></defs><rect width="100%" height="100%" fill="#050b0d"/><text x="48" y="52" font-size="25" letter-spacing="5">PHYLOGENY / DEEP-TIME LINEAGE RECORD</text><text x="48" y="80" class="small muted">GEN {gen:06d} · biological ancestry with SOMA / NERVE / TECHNE / SOCIUS state markers</text>''']
    # Generation guides.
    for i in range(0, 11):
        g = int(maxg * i / 10)
        x = left + xspan * i / 10
        parts.append(f'<line x1="{x:.1f}" y1="105" x2="{x:.1f}" y2="{H-36}" class="hair" opacity="0.35"/><text x="{x:.1f}" y="101" text-anchor="middle" class="tiny muted">{g:06d}</text>')
    # Parent connectors.
    for sp in rows:
        pid = str(sp.get("parent_id")) if sp.get("parent_id") else None
        if pid and pid in ymap:
            p = byid[pid]
            born = int(sp.get("born_generation", 0))
            x = left + xspan * born / maxg
            xp = left + xspan * min(born, int(p.get("extinct_generation") or gen)) / maxg
            parts.append(f'<path d="M{xp:.1f},{ymap[pid]:.1f} C{x-20:.1f},{ymap[pid]:.1f} {x-20:.1f},{ymap[str(sp.get("id"))]:.1f} {x:.1f},{ymap[str(sp.get("id"))]:.1f}" fill="none" stroke="#617873" stroke-width="1"/>')
    for sp in rows:
        sid = str(sp.get("id")); y = ymap[sid]
        born = int(sp.get("born_generation", 0)); end = int(sp.get("extinct_generation") or gen)
        x1 = left + xspan * born / maxg; x2 = left + xspan * end / maxg
        base, dark, pale = _species_color(sp)
        living = sp.get("extinct_generation") is None
        dash = "" if living else ' stroke-dasharray="3 3"'
        parts.append(f'<line x1="{x1:.1f}" y1="{y:.1f}" x2="{max(x1+5,x2):.1f}" y2="{y:.1f}" stroke="{base}" stroke-width="5" stroke-linecap="round" opacity="{0.88 if living else 0.38}"{dash}/><circle cx="{x1:.1f}" cy="{y:.1f}" r="3.5" fill="{pale}"/>')
        parts.append(f'<text x="48" y="{y+4:.1f}" class="small" fill="{pale}">{_esc(sp.get("name"))}</text>')
        # State markers.
        marks = []
        if sp.get("soma", {}).get("innovations"): marks.append("SOMA+")
        if float(sp.get("nerve", {}).get("architecture", {}).get("neural_complexity", 0)) > 0.52: marks.append("NERVE")
        if sp.get("techne", {}).get("practices"): marks.append(f"TECHNE:{len(sp.get('techne',{}).get('practices',[]))}")
        if sp.get("socius", {}).get("group_ids"): marks.append(f"SOCIUS:{len(sp.get('socius',{}).get('group_ids',[]))}")
        if marks:
            parts.append(f'<text x="{min(right-8,max(x1+12,x2+12)):.1f}" y="{y+4:.1f}" class="tiny" fill="#9cb3ab">{_esc(" · ".join(marks))}</text>')
    parts.append('</svg>')
    svg = ''.join(parts)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(svg, encoding="utf-8")
    return svg


def _observatory_html(world: dict[str, Any], species: list[dict[str, Any]], env: dict[str, Any], pathogens: list[dict[str, Any]], plates: dict[str, Any], branch: dict[str, Any]) -> str:
    gen = int(world.get("generation", 0))
    live = [s for s in species if s.get("extinct_generation") is None]
    ws = ensure_world_socius(world)
    techne = world.get("techne", {}) if isinstance(world.get("techne"), dict) else {}
    top = sorted(live, key=lambda s: float(s.get("population", 0)), reverse=True)[:6]
    cards = ''.join(f'''<article class="lineage"><div class="dot" style="--c:{_species_color(sp)[0]}"></div><div><strong>{_esc(sp.get('name'))}</strong><small>{int(sp.get('population',0)):,} organisms · {_esc(trophic_role(sp))}</small></div><span>{len(sp.get('socius',{}).get('group_ids',[]))} groups</span></article>''' for sp in top)
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PHYLUM / ORRERY</title><style>
:root{{--bg:#05090b;--panel:#091114;--line:#223437;--text:#dbe5e1;--muted:#718680;--accent:#9ab6aa}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 30% -10%,#102126 0,#05090b 36%,#05090b 100%);color:var(--text);font:13px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}a{{color:inherit}}header{{padding:28px 34px 18px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:24px;align-items:flex-end}}h1{{font-size:22px;letter-spacing:5px;margin:0}}header p{{color:var(--muted);margin:7px 0 0}}.status{{text-align:right;color:var(--muted)}}nav{{display:flex;gap:8px;flex-wrap:wrap;padding:14px 34px;border-bottom:1px solid var(--line);position:sticky;top:0;background:#05090bea;backdrop-filter:blur(8px);z-index:5}}nav a,.layers button{{text-decoration:none;border:1px solid #284043;background:#0a1518;color:#cbd8d3;padding:8px 11px;border-radius:7px;cursor:pointer}}nav a:hover,.layers button.active{{border-color:#6d8a80;background:#102024}}main{{padding:24px 34px 60px;max-width:1880px;margin:auto}}.hero{{border:1px solid var(--line);border-radius:14px;overflow:hidden;background:#061012}}#atlas svg{{width:100%;height:auto;display:block}}.bar{{display:flex;justify-content:space-between;gap:18px;align-items:center;padding:12px 14px;border-top:1px solid var(--line);background:#081114}}.layers{{display:flex;gap:7px;flex-wrap:wrap}}.grid{{display:grid;grid-template-columns:1.2fr .8fr;gap:18px;margin-top:18px}}.panel{{border:1px solid var(--line);border-radius:12px;background:linear-gradient(135deg,#081114,#0a1517);padding:18px}}.panel h2{{font-size:12px;letter-spacing:2px;margin:0 0 16px;color:#a8bbb4}}.metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}.metric{{border:1px solid #1e3032;border-radius:8px;padding:12px}}.metric small,.lineage small{{display:block;color:var(--muted);margin-top:5px}}.metric strong{{font-size:22px}}.lineages{{display:grid;gap:8px}}.lineage{{display:grid;grid-template-columns:12px 1fr auto;align-items:center;gap:10px;border-top:1px solid #17282a;padding:10px 2px}}.lineage:first-child{{border-top:0}}.dot{{width:8px;height:8px;border-radius:50%;background:var(--c)}}.lineage span{{color:var(--muted)}}.views{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-top:18px}}.view{{border:1px solid var(--line);border-radius:10px;padding:15px;background:#081114;text-decoration:none}}.view strong{{display:block;letter-spacing:1px}}.view small{{display:block;color:var(--muted);margin-top:7px;line-height:1.45}}@media(max-width:1000px){{.grid{{grid-template-columns:1fr}}.views{{grid-template-columns:repeat(2,1fr)}}.metrics{{grid-template-columns:repeat(2,1fr)}}header{{align-items:flex-start;flex-direction:column}}.status{{text-align:left}}}}
</style></head><body><header><div><h1>PHYLUM / ORRERY</h1><p>Autonomous evolutionary observatory · graphical system revision 1</p></div><div class="status">GEN {gen:06d}<br>{_esc(world.get('era',{}).get('name','Origin Era'))}<br>{_esc(branch.get('lineage',world.get('active_lineage','unknown')))}</div></header><nav><a href="index.html">WORLD</a><a href="phylogeny.svg">PHYLOGENY</a><a href="soma.html">SOMA</a><a href="nerve.html">NERVE</a><a href="techne.html">TECHNE</a><a href="socius.html">SOCIUS</a><a href="paleon.html">PALEON</a></nav><main><section class="hero"><div id="atlas"><object data="current.svg" type="image/svg+xml" style="display:block;width:100%;min-height:520px"></object></div><div class="bar"><span>ORRERY COMPOSITE ATLAS</span><div class="layers"><button data-layer="layer-plates">plates</button><button data-layer="layer-ranges">ranges</button><button data-layer="layer-social">society</button><button data-layer="layer-sites">sites</button><button data-layer="layer-disease">disease</button><button data-layer="layer-events">events</button></div></div></section><section class="grid"><div class="panel"><h2>BIOSPHERE</h2><div class="metrics"><div class="metric"><small>POPULATION</small><strong>{int(sum(float(s.get('population',0)) for s in live)):,}</strong></div><div class="metric"><small>LIVING LINEAGES</small><strong>{len(live)}</strong></div><div class="metric"><small>SOCIAL GROUPS</small><strong>{len(ws.get('groups',[]))}</strong></div><div class="metric"><small>TECHNE SITES</small><strong>{len(techne.get('sites',[]))}</strong></div><div class="metric"><small>PATHOGENS</small><strong>{len([p for p in pathogens if p.get('extinct_generation') is None])}</strong></div><div class="metric"><small>PLATES</small><strong>{len(plates.get('plates',[]))}</strong></div></div></div><div class="panel"><h2>DOMINANT LINEAGES</h2><div class="lineages">{cards or '<p style="color:var(--muted)">No living lineages.</p>'}</div></div></section><section class="views"><a class="view" href="soma.html"><strong>SOMA</strong><small>body plans, life cycles, physiology and reproduction</small></a><a class="view" href="nerve.html"><strong>NERVE</strong><small>memory, learning, cognition and behavioral repertoire</small></a><a class="view" href="techne.html"><strong>TECHNE</strong><small>cultural inheritance, material practices and archaeology</small></a><a class="view" href="socius.html"><strong>SOCIUS</strong><small>persistent groups, norms, relationships and social lineages</small></a><a class="view" href="paleon.html"><strong>PALEON</strong><small>atmosphere, ocean, hydrology and planetary feedback</small></a></section></main><script>
const buttons=[...document.querySelectorAll('[data-layer]')];function withSvg(fn){{const o=document.querySelector('#atlas object');try{{const d=o.contentDocument;if(d)fn(d)}}catch(e){{}}}}buttons.forEach(b=>{{b.classList.add('active');b.onclick=()=>withSvg(d=>{{const el=d.getElementById(b.dataset.layer);if(!el)return;const hidden=el.style.display==='none';el.style.display=hidden?'':'none';b.classList.toggle('active',hidden)}})}});
</script></body></html>'''


def _socius_html(world: dict[str, Any], species: list[dict[str, Any]]) -> str:
    data = socius_catalog(world, species)
    groups = data.get("groups", [])
    rows = ''.join(f'''<tr><td>{_esc(g.get('name'))}</td><td>{_esc(g.get('species_name'))}</td><td>{float(g.get('population_share',0))*100:.1f}%</td><td>{float(g.get('cohesion',0)):.2f}</td><td>{_esc(g.get('leadership'))}</td><td>{_esc(', '.join(g.get('norms',[])) or '—')}</td></tr>''' for g in groups)
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PHYLUM / SOCIUS</title><style>body{{margin:0;background:#05090b;color:#dbe5e1;font:13px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}a{{color:#c8d8d2}}main{{max-width:1500px;margin:auto;padding:28px}}h1{{letter-spacing:4px}}p{{color:#758a83}}img{{width:100%;border:1px solid #223638;border-radius:12px;background:#071012}}table{{width:100%;border-collapse:collapse;margin-top:22px}}th,td{{padding:10px;border-bottom:1px solid #1e3032;text-align:left}}th{{color:#80958e;font-size:11px;letter-spacing:1px}}.top{{display:flex;justify-content:space-between;gap:20px;align-items:end}}.badge{{border:1px solid #284043;border-radius:7px;padding:8px 10px;background:#0a1518}}</style></head><body><main><div class="top"><div><a href="index.html">← ORRERY</a><h1>SOCIUS / SOCIAL LINEAGES</h1><p>Persistent groups can form, split, merge, relate and collapse without biological extinction.</p></div><div class="badge">GEN {int(world.get('generation',0)):06d} · {len(groups)} ACTIVE</div></div><img src="socius.svg" alt="SOCIUS social lineage record"><table><thead><tr><th>GROUP</th><th>SPECIES</th><th>SHARE</th><th>COHESION</th><th>COORDINATION</th><th>NORMS</th></tr></thead><tbody>{rows or '<tr><td colspan="6">No persistent groups yet. SOCIUS remains active and opportunity-gated.</td></tr>'}</tbody></table></main></body></html>'''


def render_orrery_assets(world: dict[str, Any], species: list[dict[str, Any]], env: dict[str, Any], pathogens: list[dict[str, Any]], plates: dict[str, Any], branch: dict[str, Any], interactions: list[dict[str, Any]], root: Path) -> None:
    root = Path(root)
    renders = root / "renders"
    docs = root / "docs"
    renders.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)
    world_svg = render_world_orrery(world, species, env, pathogens, plates, branch, interactions, renders / "current.svg")
    phylo_svg = render_phylogeny_orrery(world, species, renders / "phylogeny.svg")
    shutil.copy2(renders / "current.svg", docs / "current.svg")
    shutil.copy2(renders / "phylogeny.svg", docs / "phylogeny.svg")
    (docs / "index.html").write_text(_observatory_html(world, species, env, pathogens, plates, branch), encoding="utf-8")
    (docs / "socius.html").write_text(_socius_html(world, species), encoding="utf-8")
    snapshot = {
        "orrery_schema": ORRERY_VERSION,
        "generation": int(world.get("generation", 0)),
        "world": {"era": world.get("era", {}).get("name"), "population": int(sum(float(s.get("population", 0)) for s in species if s.get("extinct_generation") is None))},
        "socius": socius_catalog(world, species),
    }
    (docs / "orrery-data.json").write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def update_readme_orrery(world: dict[str, Any], species: list[dict[str, Any]]) -> None:
    if not README_PATH.exists():
        return
    text = README_PATH.read_text(encoding="utf-8")
    gen = int(world.get("generation", 0))
    # Add SOCIUS render beside the other living-system plates.
    if "renders/socius.svg" not in text:
        anchor = "## Living cultures — TECHNE"
        block = f"## Persistent groups — SOCIUS\n\n![PHYLUM SOCIUS social lineage record](renders/socius.svg?gen={gen:06d})\n\n"
        text = text.replace(anchor, block + anchor, 1) if anchor in text else text + "\n\n" + block
    else:
        import re
        text = re.sub(r"renders/socius\.svg\?gen=[^\)\s]+", f"renders/socius.svg?gen={gen:06d}", text)
    # Replace the current-model section while preserving the generated state block and license.
    import re
    model = (
        "## Current model — SOCIUS + ORRERY\n\n"
        "PHYLUM runs **PALEON / DEEP TIME 2.0** as its planetary engine, **SOMA** as organismal biology, **NERVE** as cognition and learning, **TECHNE** as cultural inheritance and material culture, **SOCIUS** as persistent social organization, and **WITNESS** as the historical evidence layer. **ORRERY** is the graphical observatory that renders the coupled world.\n\n"
        "SOCIUS introduces persistent groups, social territories, group ancestry, norms, coordination styles, relationships, fission and social collapse. Groups are not governments and do not imply civilization: formation remains gated by population, NERVE cognition, cooperation, recognition and TECHNE cultural persistence. A biological species can survive while one of its social lineages disappears.\n\n"
        "ORRERY is a major graphical revision: layered relief/biome cartography, cleaner species-range cores, SOCIUS territories and relationship arcs, TECHNE sites and ruins, disease/event overlays, a redesigned phylogeny and a rebuilt static Observatory with live layer controls.\n"
    )
    if re.search(r"## Current model(?: — [^\n]+)?\n", text):
        text = re.sub(r"## Current model(?: — [^\n]+)?\n.*?(?=\n## Observatory|\n## License)", model + "\n", text, flags=re.S)
    if "│   ├── socius.py" not in text:
        marker = "│   ├── techne.py                   # cultural inheritance, material practices and archaeology\n"
        if marker in text:
            text = text.replace(marker, marker + "│   ├── socius.py                   # persistent groups, norms and social lineages\n│   ├── orrery.py                   # ORRERY atlas and Observatory renderer\n", 1)
    if "│   ├── socius.svg" not in text:
        marker = "│   ├── techne.svg                  # TECHNE cultural / archaeological record\n"
        if marker in text:
            text = text.replace(marker, marker + "│   ├── socius.svg                  # SOCIUS social-lineage record\n", 1)
    README_PATH.write_text(text, encoding="utf-8")
