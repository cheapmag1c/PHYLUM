from __future__ import annotations

import argparse
import json

from .core import commit_message, evolve_one, load_state


def main() -> None:
    parser = argparse.ArgumentParser(prog="phylum", description="A world that evolves through Git history.")
    sub = parser.add_subparsers(dest="command", required=True)

    evolve = sub.add_parser("evolve", help="Advance the world")
    evolve.add_argument("--steps", type=int, default=1)
    evolve.add_argument("--lineage", default=None, help="Lineage salt, normally owner/repository")

    sub.add_parser("status", help="Print current state")
    sub.add_parser("commit-message", help="Print a commit message for the current generation")

    args = parser.parse_args()
    if args.command == "evolve":
        result = None
        for _ in range(max(1, args.steps)):
            result = evolve_one(args.lineage)
        assert result is not None
        w = result["world"]
        print(f"PHYLUM generation {w['generation']} · {w['living_species']} living lineages · {int(w['total_population'])} organisms")
        for e in result["events"]:
            print(f"- {e['text']}")
    elif args.command == "status":
        w, species, env = load_state()
        living = sorted((s for s in species if s.get("extinct_generation") is None), key=lambda s: s["population"], reverse=True)
        payload = {
            "generation": w["generation"],
            "lineage": w["active_lineage"],
            "living_species": len(living),
            "extinct_species": w["extinct_species"],
            "population": int(w["total_population"]),
            "dominant": living[0]["name"] if living else None,
            "climate": {k: env[k] for k in ("temperature", "moisture", "resources")},
        }
        print(json.dumps(payload, indent=2))
    elif args.command == "commit-message":
        print(commit_message())


if __name__ == "__main__":
    main()
