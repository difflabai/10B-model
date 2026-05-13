#!/usr/bin/env python3
"""Generate a manifest summarising the contents of the 10B registry.

Output:
    registry/global/10B/runs/manifest.json

Includes counts, model IDs, and structural summary so a consumer (UI,
agent, ETL job) can navigate the registry without filesystem walks.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import tenb_root  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE = tenb_root()


def model_ids() -> List[str]:
    out: List[str] = []
    for meta in BASE.rglob("model.meta.json"):
        try:
            d = json.loads(meta.read_text())
            if "id" in d:
                out.append(d["id"])
        except Exception:
            continue
    out.sort()
    return out


def forecast_ids() -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for fp in BASE.rglob("forecasts/*.json"):
        if not fp.is_file():
            continue
        try:
            d = json.loads(fp.read_text())
            owner = str(fp.parent.parent.relative_to(BASE))
            out.append(
                {
                    "id": d.get("id", fp.stem),
                    "owner": owner,
                    "label": d.get("label", ""),
                }
            )
        except Exception:
            continue
    return out


def main() -> int:
    ids = model_ids()
    forecasts = forecast_ids()
    countries_dir = BASE / "countries"
    regions_dir = BASE / "regions"
    categories_dir = BASE / "categories"

    # iterdir() fails if the dir is missing — possible when manifest.py is
    # run before the dir-producing pipeline steps. Report zero in that case
    # so the manifest still serialises and the user sees an honest count.
    def _count_dirs(p: Path) -> int:
        return sum(1 for child in p.iterdir() if child.is_dir()) if p.is_dir() else 0

    country_count = _count_dirs(countries_dir)
    region_count = _count_dirs(regions_dir)
    category_count = _count_dirs(categories_dir)

    by_namespace: Dict[str, int] = {}
    for mid in ids:
        ns = ".".join(mid.split(".")[:3]) if mid.count(".") >= 2 else mid
        by_namespace[ns] = by_namespace.get(ns, 0) + 1

    manifest = {
        "registry": "global/10B",
        "schema": "global.10B.needs-tree",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "model_count": len(ids),
        "forecast_count": len(forecasts),
        "country_count": country_count,
        "region_count": region_count,
        "category_count": category_count,
        "top_level_models": [
            "global.10B",
            "global.10B.needs-tree",
            "global.10B.dynamics",
            "global.10B.supervised-trajectory",
            "global.10B.personal-agent",
        ],
        "namespace_counts": dict(sorted(by_namespace.items())),
        "outputs": {
            "macro_embedding": "global/10B/runs/macro-embedding.json",
            "macro_dynamics": "global/10B/runs/macro-dynamics.json",
            "manifest": "global/10B/runs/manifest.json",
            "personal_agent": "global/10B/personal-agent/runs/index.json",
        },
        "design_questions": [
            "How can I connect with my neighbors?",
            "What economic value can I bring to my community?",
            "How can I effectively advocate for change?",
        ],
    }
    out = BASE / "runs" / "manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"manifest: {len(ids)} models, {len(forecasts)} forecasts, "
        f"{country_count} countries, {region_count} regions, {category_count} categories."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
