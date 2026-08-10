from __future__ import annotations

import hashlib
import math
import random
from typing import Any, Iterable


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def stable_int(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:16], 16)


def fingerprint(data: Any) -> str:
    import json
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def deterministic_rng(seed: int, generation: int, lineage: str, channel: str = "main") -> random.Random:
    payload = f"{seed}:{generation}:{lineage}:{channel}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def weighted_choice(rng: random.Random, pairs: Iterable[tuple[Any, float]]) -> Any:
    items = [(item, max(0.0, float(weight))) for item, weight in pairs]
    total = sum(w for _, w in items)
    if total <= 0:
        return items[0][0] if items else None
    target = rng.random() * total
    upto = 0.0
    for item, weight in items:
        upto += weight
        if upto >= target:
            return item
    return items[-1][0]


def smoothstep(edge0: float, edge1: float, x: float) -> float:
    if edge1 == edge0:
        return 0.0
    t = clamp((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def mean(values: Iterable[float], default: float = 0.0) -> float:
    vals = list(values)
    return sum(vals) / len(vals) if vals else default


def euclidean(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.dist(a, b)
