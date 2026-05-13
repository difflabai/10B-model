#!/usr/bin/env python3
"""Generate per-country agent-context outputs for the personal-agent model.

For each country, materialises an output file answering the three
founding questions:

    1. How can I connect with my neighbors?    (connect surface)
    2. What economic value can I bring to my community?  (contribute surface)
    3. How can I effectively advocate for change?  (advocate surface)

Outputs land at:
    global/10B/personal-agent/runs/<country-slug>.json
    global/10B/personal-agent/runs/index.json

The surfaces are computed from already-materialised registry artefacts:
the per-country category scores, the cluster assignment, and the
nearest-peer list — keeping this script a pure aggregator over upstream
model outputs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import tenb_root  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE = tenb_root()


def load_country(slug: str) -> Dict[str, Any] | None:
    out = BASE / "countries" / slug / "runs" / "output.json"
    if not out.exists():
        return None
    return json.loads(out.read_text())


def load_peers(slug: str) -> Dict[str, Any] | None:
    p = BASE / "countries" / slug / "runs" / "peers.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def category_world_means() -> Dict[str, float]:
    out: Dict[str, float] = {}
    cats_dir = BASE / "categories"
    if not cats_dir.is_dir():
        return out
    for cd in cats_dir.iterdir():
        runp = cd / "runs" / "output.json"
        if runp.exists():
            d = json.loads(runp.read_text())
            out[cd.name] = d.get("world_mean", 0.0)
    return out


def country_label(slug: str) -> str:
    return slug.replace("-", " ").title()


def surface_connect(country: Dict[str, Any], peers: Dict[str, Any] | None, world: Dict[str, float]) -> Dict[str, Any]:
    scores = country.get("category_scores") or {}
    belonging = scores.get("belonging")
    meaning = scores.get("meaning")
    communications = scores.get("communications")
    relevant = {
        "belonging": belonging,
        "meaning": meaning,
        "communications": communications,
    }
    gaps = sorted(
        ((c, s) for c, s in relevant.items() if s is not None),
        key=lambda t: t[1],
    )
    weakest = gaps[0] if gaps else None
    weakest_world = world.get(weakest[0]) if weakest else None
    text_lines = []
    if weakest:
        delta = weakest[1] - (weakest_world or 0)
        text_lines.append(
            f"Your country's biggest community-building gap is in **{weakest[0]}** "
            f"(score {weakest[1]:.2f}, world mean {weakest_world:.2f}, "
            f"{'+' if delta >= 0 else ''}{delta:.2f} vs world)."
        )
    if peers:
        peer_names = [p["country"] for p in peers.get("nearest_peers", [])[:5]]
        text_lines.append(
            "Closest peer countries (similar overall needs profile): "
            + ", ".join(country_label(p) for p in peer_names)
            + ". Look at how their communities are organised — most likely useful patterns."
        )
    return {
        "question": "How can I connect with my neighbors?",
        "categories_consulted": list(relevant.keys()),
        "category_scores": relevant,
        "weakest_category": weakest[0] if weakest else None,
        "narrative": " ".join(text_lines) if text_lines else "Insufficient data.",
    }


def surface_contribute(country: Dict[str, Any], world: Dict[str, float]) -> Dict[str, Any]:
    scores = country.get("category_scores") or {}
    relevant = {
        "work": scores.get("work"),
        "education": scores.get("education"),
        "energy": scores.get("energy"),
        "communications": scores.get("communications"),
    }
    deltas = [
        (c, scores[c] - world.get(c, 0.5))
        for c in relevant
        if scores.get(c) is not None
    ]
    deltas.sort(key=lambda t: t[1])
    gaps = [c for c, _ in deltas[:2]]
    strengths = [c for c, _ in deltas[-2:]][::-1]
    text_lines = []
    if gaps:
        text_lines.append(
            "Below-world-mean economic capability dimensions you can plausibly close: "
            + ", ".join(gaps) + "."
        )
    if strengths:
        text_lines.append(
            "Above-world-mean dimensions you can leverage as sources of value: "
            + ", ".join(strengths) + "."
        )
    text_lines.append(
        "Personal-agent guidance: in an AI economic transition, the work/education/communications "
        "complement is the lever — pursue value at the intersection of your strengths and your community's gaps."
    )
    return {
        "question": "What economic value can I bring to my community?",
        "categories_consulted": list(relevant.keys()),
        "category_scores": relevant,
        "above_world_mean": strengths,
        "below_world_mean": gaps,
        "narrative": " ".join(text_lines),
    }


def surface_advocate(country: Dict[str, Any], world: Dict[str, float]) -> Dict[str, Any]:
    scores = country.get("category_scores") or {}
    relevant = {
        "agency": scores.get("agency"),
        "governance": scores.get("governance"),
        "environment": scores.get("environment"),
        "safety": scores.get("safety"),
    }
    deltas = [
        (c, (scores[c] or 0.5) - world.get(c, 0.5))
        for c in relevant
        if scores.get(c) is not None
    ]
    deltas.sort(key=lambda t: t[1])
    biggest_lever = deltas[0] if deltas else None
    text_lines = []
    if biggest_lever:
        text_lines.append(
            f"Highest-leverage advocacy dimension: **{biggest_lever[0]}** "
            f"(country {scores.get(biggest_lever[0]):.2f} vs world {world.get(biggest_lever[0]):.2f})."
        )
    text_lines.append(
        "Approach: pair the strongest agency/governance score (gives you the institutional surface "
        "to operate within) with the highest-leverage gap (gives you the change to push for)."
    )
    return {
        "question": "How can I effectively advocate for change?",
        "categories_consulted": list(relevant.keys()),
        "category_scores": relevant,
        "highest_leverage": biggest_lever[0] if biggest_lever else None,
        "narrative": " ".join(text_lines),
    }


def main() -> int:
    runs_dir = BASE / "personal-agent" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    world = category_world_means()
    countries_dir = BASE / "countries"
    written = 0
    index: List[Dict[str, Any]] = []
    for cd in sorted(countries_dir.iterdir()):
        if not cd.is_dir():
            continue
        country = load_country(cd.name)
        if country is None or not country.get("category_scores"):
            continue
        peers = load_peers(cd.name)
        ctx = {
            "country_slug": cd.name,
            "country_label": country_label(cd.name),
            "country_score": country.get("country_score"),
            "tier_scores": country.get("tier_scores"),
            "cluster_id": peers.get("cluster_id") if peers else None,
            "cluster_label": peers.get("cluster_label") if peers else None,
            "connect": surface_connect(country, peers, world),
            "contribute": surface_contribute(country, world),
            "advocate": surface_advocate(country, world),
            "scored_with": "scripts/10b/agent_context.py v0.1.0",
        }
        (runs_dir / f"{cd.name}.json").write_text(
            json.dumps(ctx, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        index.append({
            "country": cd.name,
            "country_score": country.get("country_score"),
            "cluster_id": ctx["cluster_id"],
        })
        written += 1

    (runs_dir / "index.json").write_text(
        json.dumps(
            {
                "country_count": written,
                "files": [f"{i['country']}.json" for i in index],
                "by_country": {i["country"]: i for i in index},
                "scored_with": "scripts/10b/agent_context.py v0.1.0",
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {written} per-country agent-context files + 1 index.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
