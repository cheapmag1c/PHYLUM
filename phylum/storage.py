from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORLD_DIR = ROOT / "world"
FOSSIL_DIR = ROOT / "fossils"
RENDER_DIR = ROOT / "renders"
DOCS_DIR = ROOT / "docs"

WORLD_PATH = WORLD_DIR / "current.json"
SPECIES_PATH = WORLD_DIR / "species.json"
ENV_PATH = WORLD_DIR / "environment.json"
PATHOGENS_PATH = WORLD_DIR / "pathogens.json"
PLATES_PATH = WORLD_DIR / "plates.json"
BRANCH_PATH = WORLD_DIR / "branch.json"
INTERACTIONS_PATH = WORLD_DIR / "interactions.json"
CHANGES_PATH = WORLD_DIR / "changes.json"
EVENTS_PATH = FOSSIL_DIR / "events.ndjson"
HISTORY_PATH = FOSSIL_DIR / "history.ndjson"
ATLAS_HISTORY_PATH = FOSSIL_DIR / "atlas-history.ndjson"
SPECIES_FOSSIL_DIR = FOSSIL_DIR / "species"
SNAPSHOT_DIR = FOSSIL_DIR / "snapshots"
CHECKPOINT_DIR = FOSSIL_DIR / "checkpoints"
README_PATH = ROOT / "README.md"


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def append_ndjson(path: Path, items: list[dict[str, Any]]) -> None:
    if not items:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item, sort_keys=True) + "\n")


def read_ndjson(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-limit:] if limit else rows


def load_state() -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    world = load_json(WORLD_PATH, {}) or {}
    species = load_json(SPECIES_PATH, []) or []
    env = load_json(ENV_PATH, {}) or {}
    return world, species, env


def load_extended() -> tuple[
    dict[str, Any], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]],
    dict[str, Any], dict[str, Any], list[dict[str, Any]],
]:
    world, species, env = load_state()
    pathogens = load_json(PATHOGENS_PATH, []) or []
    plates = load_json(PLATES_PATH, {}) or {}
    branch = load_json(BRANCH_PATH, {}) or {}
    interactions = load_json(INTERACTIONS_PATH, []) or []
    return world, species, env, pathogens, plates, branch, interactions


def save_extended(
    world: dict[str, Any],
    species: list[dict[str, Any]],
    env: dict[str, Any],
    pathogens: list[dict[str, Any]],
    plates: dict[str, Any],
    branch: dict[str, Any],
    interactions: list[dict[str, Any]],
) -> None:
    atomic_json(WORLD_PATH, world)
    atomic_json(SPECIES_PATH, species)
    atomic_json(ENV_PATH, env)
    atomic_json(PATHOGENS_PATH, pathogens)
    atomic_json(PLATES_PATH, plates)
    atomic_json(BRANCH_PATH, branch)
    atomic_json(INTERACTIONS_PATH, interactions)


def backup_state(tag: str = "pre-evolve") -> Path:
    root = ROOT / ".phylum-backup"
    backup = root / tag
    backup.mkdir(parents=True, exist_ok=True)
    for path in (WORLD_PATH, SPECIES_PATH, ENV_PATH, PATHOGENS_PATH, PLATES_PATH, BRANCH_PATH, INTERACTIONS_PATH, CHANGES_PATH):
        if path.exists():
            shutil.copy2(path, backup / path.name)
    # Local multi-step experiments should not accumulate thousands of untracked backups.
    dirs=sorted((d for d in root.iterdir() if d.is_dir()),key=lambda d:d.stat().st_mtime,reverse=True)
    for old in dirs[5:]: shutil.rmtree(old,ignore_errors=True)
    return backup


def write_checkpoint(generation: int, payload: dict[str, Any]) -> Path:
    path = CHECKPOINT_DIR / f"gen-{generation:06d}.json"
    atomic_json(path, payload)
    return path
