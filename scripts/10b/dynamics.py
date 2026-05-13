#!/usr/bin/env python3
"""Unsupervised dynamics over the 10B macro-space.

Reads the per-country category-score matrix produced by `scorer.py`,
runs k-means clustering on the [num_countries × num_categories] matrix to
reveal "hidden dynamics" — needs-profile clusters across countries —
and writes:

  - global/10B/runs/macro-dynamics.json  (cluster assignments + centroids)
  - global/10B/countries/<slug>/runs/peers.json  (k nearest neighbour
    countries by needs profile, for personal-agent peer-comparison.)

Stdlib-only k-means with deterministic seeding so output is reproducible.
"""

from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import tenb_root  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE = tenb_root()
NEEDS_TREE = BASE / "needs-tree.json"


def load_country_profiles() -> Tuple[List[str], List[str], List[List[float]]]:
    base = BASE / "countries"
    needs = json.loads(NEEDS_TREE.read_text())
    cats = list(needs["categories"].keys())
    countries: List[str] = []
    matrix: List[List[float]] = []
    for cd in sorted(base.iterdir()):
        if not cd.is_dir():
            continue
        run = cd / "runs" / "output.json"
        if not run.exists():
            continue
        out = json.loads(run.read_text())
        scores = out.get("category_scores") or {}
        if any(scores.get(c) is None for c in cats):
            continue
        countries.append(cd.name)
        matrix.append([float(scores[c]) for c in cats])
    return cats, countries, matrix


def euclidean(a: List[float], b: List[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def kmeans(
    points: List[List[float]], k: int, *, seed: int = 42, iters: int = 60
) -> Tuple[List[int], List[List[float]]]:
    rng = random.Random(seed)
    # k-means++ init
    centroids = [points[rng.randrange(len(points))]]
    while len(centroids) < k:
        d2 = [min(euclidean(p, c) ** 2 for c in centroids) for p in points]
        total = sum(d2)
        if total <= 0:
            centroids.append(points[rng.randrange(len(points))])
            continue
        r = rng.random() * total
        acc = 0.0
        for p, d in zip(points, d2):
            acc += d
            if acc >= r:
                centroids.append(p)
                break
    assignments = [0] * len(points)
    for _ in range(iters):
        new_assign = [
            min(range(k), key=lambda j: euclidean(p, centroids[j])) for p in points
        ]
        if new_assign == assignments:
            break
        assignments = new_assign
        new_centroids = []
        for j in range(k):
            members = [p for p, a in zip(points, assignments) if a == j]
            if members:
                dim = len(members[0])
                new_centroids.append(
                    [sum(m[d] for m in members) / len(members) for d in range(dim)]
                )
            else:
                new_centroids.append(points[rng.randrange(len(points))])
        centroids = new_centroids
    return assignments, centroids


def cluster_label(centroid: List[float], cats: List[str]) -> str:
    pairs = list(zip(cats, centroid))
    pairs.sort(key=lambda t: -t[1])
    top = ", ".join(c for c, _ in pairs[:3])
    pairs.sort(key=lambda t: t[1])
    bot = ", ".join(c for c, _ in pairs[:3])
    overall = sum(centroid) / len(centroid)
    return (
        f"avg {overall:.2f}; strongest in [{top}], weakest in [{bot}]"
    )


def main() -> int:
    k = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    cats, countries, matrix = load_country_profiles()
    if not matrix:
        print("no country profiles; run scorer.py first")
        return 1

    assignments, centroids = kmeans(matrix, k=k, seed=42)

    cluster_table: Dict[int, List[str]] = {}
    for c, a in zip(countries, assignments):
        cluster_table.setdefault(a, []).append(c)

    out = {
        "method": "k-means (k-means++ init, deterministic seed=42, 60 iters max)",
        "k": k,
        "categories": cats,
        "country_count": len(countries),
        "clusters": [
            {
                "id": cid,
                "size": len(cluster_table[cid]),
                "label": cluster_label(centroids[cid], cats),
                "centroid": [round(v, 4) for v in centroids[cid]],
                "members_sample": sorted(cluster_table[cid])[:20],
                "all_members": sorted(cluster_table[cid]),
            }
            for cid in sorted(cluster_table)
        ],
        "country_assignments": dict(sorted(zip(countries, assignments), key=lambda t: t[0])),
        "scored_with": "scripts/10b/dynamics.py v0.1.0",
    }
    base = BASE
    (base / "runs").mkdir(parents=True, exist_ok=True)
    (base / "runs" / "macro-dynamics.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Per-country peers — k=10 nearest neighbours on the same matrix.
    countries_dir = base / "countries"
    by_idx = {c: i for i, c in enumerate(countries)}
    written = 0
    for c, idx in by_idx.items():
        dists = sorted(
            ((euclidean(matrix[idx], matrix[j]), countries[j]) for j in range(len(countries)) if j != idx),
            key=lambda t: t[0],
        )
        peers_top = [{"country": n, "distance": round(d, 4)} for d, n in dists[:10]]
        peers_bot = [{"country": n, "distance": round(d, 4)} for d, n in dists[-5:]]
        cluster_id = assignments[idx]
        peers_in_cluster = [
            cc for cc in cluster_table[cluster_id] if cc != c
        ]
        peers_doc = {
            "country": c,
            "cluster_id": cluster_id,
            "cluster_label": cluster_label(centroids[cluster_id], cats),
            "nearest_peers": peers_top,
            "most_different": peers_bot,
            "cluster_peers": peers_in_cluster[:20],
            "scored_with": "scripts/10b/dynamics.py v0.1.0",
        }
        d = countries_dir / c / "runs"
        if d.parent.exists():
            d.mkdir(parents=True, exist_ok=True)
            (d / "peers.json").write_text(
                json.dumps(peers_doc, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            written += 1

    print(
        f"k-means k={k}: {len(cluster_table)} clusters across "
        f"{len(countries)} countries; wrote {written} peer files."
    )
    print("Cluster sizes:", sorted([(cid, len(m)) for cid, m in cluster_table.items()]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
