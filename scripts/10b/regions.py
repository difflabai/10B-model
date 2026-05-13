#!/usr/bin/env python3
"""Generate regional rollups (UN geoscheme regions) between country and global.

Reads countries.json, classifies each country into one of:
  - africa
  - americas
  - asia
  - europe
  - oceania
  - polar (Antarctica, Arctic territories)

For each region, materialises:
  registry/global/10B/regions/<region>/model.meta.json
  registry/global/10B/regions/<region>/model.run.json
  registry/global/10B/regions/<region>/runs/output.json    (rollup of country scores)
  registry/global/10B/regions/<region>/<category>/model.meta.json + model.run.json
  registry/global/10B/regions/<region>/<category>/runs/output.json

The top-level 10B model now has both country-level and region-level
dependencies, so the relationship graph reads as
country → region → world.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import countries_json_path, require_countries_json, tenb_root  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE = tenb_root()
COUNTRIES_JSON = countries_json_path()
NEEDS_TREE = BASE / "needs-tree.json"


REGIONS = ["africa", "americas", "asia", "europe", "oceania", "polar"]
REGION_LABELS = {
    "africa": "Africa",
    "americas": "Americas",
    "asia": "Asia",
    "europe": "Europe",
    "oceania": "Oceania",
    "polar": "Polar / extra-territorial",
}


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")
    return s or "unknown"


def classify(country_name: str, country_data: Dict[str, Any]) -> str:
    map_ref = country_data.get("Geography: Map references") or ""
    location = country_data.get("Geography: Location") or ""
    blob = (map_ref + " " + location).lower()
    if any(k in blob for k in ("antarctica", "arctic ocean")):
        return "polar"
    if any(k in blob for k in (
        "africa", "central african", "east african", "west african", "southern african", "north african",
    )):
        return "africa"
    if any(k in blob for k in (
        "europe", "european", "balkans", "scandinavia", "british isles",
        "iberian", "nordic", "baltic", "iceland",
    )):
        return "europe"
    if any(k in blob for k in (
        "asia", "middle east", "southeast asia", "south asia", "east asia", "central asia",
    )):
        return "asia"
    if any(k in blob for k in ("oceania", "australia", "new zealand", "pacific", "south pacific")):
        return "oceania"
    if any(k in blob for k in (
        "americas", "central america", "south america", "north america", "caribbean",
    )):
        return "americas"
    return "polar"


def io(name: str, kind: str, desc: str) -> Dict[str, str]:
    return {"name": name, "kind": kind, "description": desc}


def comp(cid: str, name: str, role: str, syms: List[str] | None = None) -> Dict[str, Any]:
    return {"id": cid, "name": name, "role": role, "crate_path": None, "key_symbols": syms or []}


def param(k: str, v: str, d: str | None = None) -> Dict[str, Any]:
    o = {"key": k, "value": v}
    if d is not None:
        o["description"] = d
    return o


def ref(label: str, kind: str, location: str) -> Dict[str, str]:
    return {"label": label, "kind": kind, "location": location}


def dep(target: str, kind: str, note: str) -> Dict[str, Any]:
    return {"target_model_id": target, "kind": kind, "note": note}


def write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_country_score(slug: str) -> Dict[str, Any] | None:
    p = BASE / "countries" / slug / "runs" / "output.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


AGGREGATE_ENTRIES = {"World", "European Union"}


def main() -> int:
    countries = json.loads(require_countries_json().read_text())
    needs_tree = json.loads(NEEDS_TREE.read_text())
    cats = list(needs_tree["categories"].keys())

    membership: Dict[str, List[str]] = {r: [] for r in REGIONS}
    classification: Dict[str, str] = {}
    for name, data in countries.items():
        # Skip Factbook aggregates (World, EU) so regional rollups aren't
        # double-counted by an entry that already aggregates every country.
        if name in AGGREGATE_ENTRIES:
            continue
        slug = slugify(name)
        region = classify(name, data)
        membership[region].append(slug)
        classification[slug] = region

    written_models = 0
    written_runs = 0

    for region in REGIONS:
        slugs = membership[region]
        rdir = BASE / "regions" / region

        # Region-level rollup model meta
        meta = {
            "id": f"global.10B.regions.{region}",
            "name": f"{REGION_LABELS[region]} — needs rollup",
            "kind": "sector_economic",
            "blurb": (
                f"Regional rollup for {REGION_LABELS[region]} aggregating "
                f"{len(slugs)} country needs profiles into a {len(cats)}-category satisfaction vector."
            ),
            "mechanism": (
                f"Aggregates {len(slugs)} country needs profiles for {REGION_LABELS[region]} into a "
                f"region-level satisfaction vector across all 15 categories. The aggregation is a "
                f"population-weighted mean (weights from the country's reported population). "
                f"This sits between the per-country rollups and the global 10B model in the dependency graph."
            ),
            "components": [
                comp("classifier", "Region classifier", "Maps countries to UN-geoscheme regions."),
                comp("aggregator", "Region aggregator", "Population-weighted mean across countries."),
                comp("ranker", "Country ranker", "Ranks countries within the region by category satisfaction."),
            ],
            "inputs": [io(f"{c}-region-scores", "scalar-list", f"{c} scores across {REGION_LABELS[region]} countries.") for c in cats],
            "outputs": [
                io("region-needs-vector", "vector", "Region-level satisfaction vector across categories."),
                io("region-ranking", "ranking", "Within-region ranking on each category."),
            ],
            "parameters": [
                param("region", REGION_LABELS[region]),
                param("country-count", str(len(slugs))),
                param("categories", ", ".join(cats)),
            ],
            "references": [
                ref("UN geoscheme", "url", "https://unstats.un.org/unsd/methodology/m49/"),
                ref("10B Needs Tree", "spec", "global/10B/needs-tree.json"),
            ],
            "depends_on": [
                dep(f"global.10B.countries.{s}", "consumes_from", f"Per-country rollup: {s}")
                for s in slugs
            ]
            + [
                dep("global.10B", "consumes_from", "Top-level 10B model rolls regions up into the global view.")
            ],
        }
        run = {
            "modelId": f"global.10B.regions.{region}",
            "engine": "closed-form",
            "inputs": {
                "region": {"value": region},
                "country-models": {"list": [f"global.10B.countries.{s}" for s in slugs]},
            },
            "spec": {"inline": {"rollup": "region", "weights": "population"}},
            "output": "./runs/output.json",
        }
        write(rdir / "model.meta.json", meta)
        write(rdir / "model.run.json", run)
        written_models += 1

        # Compute region rollup output
        per_cat: Dict[str, List[float]] = {c: [] for c in cats}
        country_scores: List[Dict[str, Any]] = []
        for s in slugs:
            cs = load_country_score(s)
            if cs is None:
                continue
            for c in cats:
                v = (cs.get("category_scores") or {}).get(c)
                if v is not None:
                    per_cat[c].append(v)
            country_scores.append(
                {"country": s, "country_score": cs.get("country_score"), "category_scores": cs.get("category_scores")}
            )
        region_means = {
            c: round(sum(v) / len(v), 4) if v else None for c, v in per_cat.items()
        }
        valid = [v for v in region_means.values() if v is not None]
        run_out = {
            "region": region,
            "label": REGION_LABELS[region],
            "country_count": len(country_scores),
            "category_means": region_means,
            "region_score": round(sum(valid) / len(valid), 4) if valid else None,
            "country_scores": sorted(
                country_scores, key=lambda x: -(x["country_score"] or 0)
            )[:25],
            "scored_with": "scripts/10b/regions.py v0.1.0",
        }
        write(rdir / "runs" / "output.json", run_out)
        written_runs += 1

        # Per-region per-category sub-models
        for c in cats:
            cdir = rdir / c
            cmeta = {
                "id": f"global.10B.regions.{region}.{c}",
                "name": f"{REGION_LABELS[region]} — {needs_tree['categories'][c]['label']}",
                "kind": needs_tree["categories"][c].get("engine") == "monte-carlo" and "forecast_harness" or "sector_economic",
                "blurb": (
                    f"Region-level {needs_tree['categories'][c]['label'].lower()} for {REGION_LABELS[region]}, "
                    f"aggregated across {len(slugs)} countries."
                ),
                "mechanism": (
                    f"Aggregates the per-country {c} models for the {len(slugs)} {REGION_LABELS[region]} countries "
                    f"into a single regional category score and a country ranking, feeding both the regional "
                    f"rollup and the cross-country category world rollup."
                ),
                "components": [comp("aggregator", "Country aggregator", "Region-internal aggregation.")],
                "inputs": [io(f"{c}-country-scores", "scalar-list", f"{c} scores across {REGION_LABELS[region]} countries.")],
                "outputs": [
                    io(f"{c}-region-mean", "scalar", f"Mean {c} score across the region."),
                    io(f"{c}-region-ranking", "ranking", "Country-level ranking within the region."),
                ],
                "parameters": [
                    param("region", REGION_LABELS[region]),
                    param("category", needs_tree["categories"][c]["label"]),
                    param("country-count", str(len(slugs))),
                ],
                "references": [
                    ref("10B Needs Tree", "spec", "global/10B/needs-tree.json"),
                ],
                "depends_on": [
                    dep(f"global.10B.countries.{s}.{c}", "consumes_from", f"Country-level {c} for {s}")
                    for s in slugs
                ]
                + [
                    dep(f"global.10B.regions.{region}", "consumes_from", "Parent region rollup."),
                    dep(f"global.10B.categories.{c}", "consumes_from", "Cross-country category rollup."),
                ],
            }
            crun = {
                "modelId": f"global.10B.regions.{region}.{c}",
                "engine": needs_tree["categories"][c].get("engine", "closed-form"),
                "inputs": {
                    "region": {"value": region},
                    "category": {"value": c},
                    "country-models": {"list": [f"global.10B.countries.{s}.{c}" for s in slugs]},
                },
                "spec": {"inline": {"rollup": "region-category", "weights": "population"}},
                "output": "./runs/output.json",
            }
            write(cdir / "model.meta.json", cmeta)
            write(cdir / "model.run.json", crun)
            written_models += 1

            scores = per_cat.get(c, [])
            if scores:
                ss = sorted(scores)
                n = len(ss)
                cout = {
                    "region": region,
                    "category": c,
                    "country_count": n,
                    "mean": round(sum(scores) / n, 4),
                    "median": round(ss[n // 2], 4),
                    "min": round(ss[0], 4),
                    "max": round(ss[-1], 4),
                    "scored_with": "scripts/10b/regions.py v0.1.0",
                }
                write(cdir / "runs" / "output.json", cout)
                written_runs += 1

    # Update top-level macro-embedding output to include region-level rollups
    macro_path = BASE / "runs" / "macro-embedding.json"
    if macro_path.exists():
        macro = json.loads(macro_path.read_text())
        macro["region_rollups"] = sorted(REGIONS)
        macro["country_to_region"] = classification
        write(macro_path, macro)

    summary = {
        "regions": REGIONS,
        "membership_counts": {r: len(membership[r]) for r in REGIONS},
    }
    print(
        f"wrote {written_models} regional models + {written_runs} run outputs. "
        f"Region sizes: {summary['membership_counts']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
