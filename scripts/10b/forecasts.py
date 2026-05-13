#!/usr/bin/env python3
"""Generate forecasts for the 10B model registry.

Per the project description, the supervised trajectory aims to predict
hold-out datasets of sociodemographic characteristics. We attach:

  - One numeric forecast per cross-country category rollup (e.g. world-mean
    food security in 2030).
  - One numeric forecast per (country × category) model where the country
    is among the 30 most populous (the supervised hold-out trajectory's
    primary targets).
  - One macro-trajectory forecast on the top-level 10B model.

Forecast metadata follows the ForecastMeta schema at
`crates/bwm-server/src/registry/meta.rs` (round-trips losslessly with
serde_json::from_str::<ForecastMeta>(...)).
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import (  # noqa: E402
    countries_json_path,
    require_countries_json,
    slugify,
    tenb_root,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE = tenb_root()
COUNTRIES_JSON = countries_json_path()
NEEDS_TREE_JSON = BASE / "needs-tree.json"


def now() -> dt.datetime:
    return dt.datetime(2026, 5, 8, 0, 0, 0, tzinfo=dt.timezone.utc)


def iso(d: dt.datetime) -> str:
    return d.isoformat().replace("+00:00", "Z")


def numeric_outcome_space(unit: str, lo: float, hi: float) -> Dict[str, Any]:
    return {
        "kind": "numeric",
        "unit": unit,
        "min": str(lo),
        "max": str(hi),
        "categories": [],
    }


def fixed_schedule(hours: int, triggers: List[str]) -> Dict[str, Any]:
    return {"kind": "fixed", "interval_hours": hours, "triggers": triggers}


def forecast(
    *,
    fid: str,
    label: str,
    task_family: str,
    tags: List[str],
    prompt: str,
    resolution_criteria: str,
    expected_resolution_at: dt.datetime,
    outcome_space: Dict[str, Any],
    schedule: Dict[str, Any],
    evidence: List[Dict[str, Any]] | None = None,
    diagnostics: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    return {
        "id": fid,
        "label": label,
        "task_family": task_family,
        "tags": tags,
        "prompt": prompt,
        "resolution_criteria": resolution_criteria,
        "expected_resolution_at": iso(expected_resolution_at),
        "last_checkpoint_at": None,
        "next_checkpoint_at": iso(
            now() + dt.timedelta(hours=schedule.get("interval_hours") or 168)
        ),
        "current_summary": None,
        "current_prediction": None,
        "outcome_space": outcome_space,
        "schedule": schedule,
        "evidence": evidence or [],
        "diagnostics": diagnostics or [],
        "history": [],
        "status": "pending",
    }


def category_world_forecast(cat_id: str, label: str) -> Dict[str, Any]:
    return forecast(
        fid=f"{cat_id}-world-2030",
        label=f"{label} world mean by 2030-12-31",
        task_family="needs.world.category",
        tags=["10B", cat_id, "world-mean", "2030"],
        prompt=(
            f"What will the population-weighted world-mean satisfaction score for "
            f"the {label.lower()} category be on 2030-12-31, computed by the "
            f"global.10B.categories.{cat_id} rollup? Score is in [0,1] where 1 = "
            f"full satisfaction across all countries."
        ),
        resolution_criteria=(
            f"Resolves to the value of `world_mean` in "
            f"global/10B/categories/{cat_id}/runs/output.json on 2030-12-31."
        ),
        expected_resolution_at=dt.datetime(2030, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc),
        outcome_space=numeric_outcome_space("score [0,1]", 0.0, 1.0),
        schedule=fixed_schedule(168, [f"global.10B.categories.{cat_id}.run"]),
    )


def country_category_forecast(cat_id: str, country_slug: str, country_name: str, label: str) -> Dict[str, Any]:
    return forecast(
        fid=f"{country_slug}-{cat_id}-2028",
        label=f"{country_name} {label.lower()} score by 2028-12-31",
        task_family="needs.country.category",
        tags=["10B", cat_id, country_slug, "supervised-holdout"],
        prompt=(
            f"What will the satisfaction score for the {label.lower()} category in "
            f"{country_name} be on 2028-12-31, as computed by the model "
            f"global.10B.countries.{country_slug}.{cat_id}? "
            f"This is a primary supervised hold-out target."
        ),
        resolution_criteria=(
            f"Resolves to the `composite_score` in "
            f"global/10B/countries/{country_slug}/{cat_id}/runs/output.json on 2028-12-31."
        ),
        expected_resolution_at=dt.datetime(2028, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc),
        outcome_space=numeric_outcome_space("score [0,1]", 0.0, 1.0),
        schedule=fixed_schedule(720, [f"global.10B.countries.{country_slug}.{cat_id}.run"]),
    )


def macro_forecast() -> Dict[str, Any]:
    return forecast(
        fid="macro-trajectory-2030",
        label="10B macro-embedding hold-out accuracy by 2030-12-31",
        task_family="needs.macro.holdout",
        tags=["10B", "macro", "holdout", "supervised"],
        prompt=(
            "What will the supervised hold-out accuracy of the 10B macro-embedding be on "
            "2030-12-31, evaluated against the held-out sociodemographic dataset? "
            "Accuracy is the area under the curve for predicting a country's category "
            "satisfaction quintile from its 10B embedding."
        ),
        resolution_criteria=(
            "Resolves to the AUC of a country-category quintile predictor trained on the "
            "10B embedding and evaluated on the held-out 20% of countries on 2030-12-31."
        ),
        expected_resolution_at=dt.datetime(2030, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc),
        outcome_space=numeric_outcome_space("AUC [0.5,1]", 0.5, 1.0),
        schedule=fixed_schedule(168, ["global.10B.run"]),
    )


def population_for(country_data: Dict[str, Any]) -> int:
    pop = country_data.get("People and Society: Population - total", "")
    if not isinstance(pop, str):
        return 0
    digits = "".join(ch for ch in pop.split("(")[0] if ch.isdigit() or ch == ",")
    digits = digits.replace(",", "")
    try:
        return int(digits) if digits else 0
    except ValueError:
        return 0


def main() -> int:
    countries = json.loads(require_countries_json().read_text())
    needs_tree = json.loads(NEEDS_TREE_JSON.read_text())

    base = BASE

    # Category world rollups
    cat_count = 0
    cat_id_to_label = {c: d["label"] for c, d in needs_tree["categories"].items()}
    for cat_id, label in cat_id_to_label.items():
        forecasts_dir = base / "categories" / cat_id / "forecasts"
        forecasts_dir.mkdir(parents=True, exist_ok=True)
        f = category_world_forecast(cat_id, label)
        (forecasts_dir / f"{f['id']}.json").write_text(
            json.dumps(f, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        cat_count += 1

    # Top 30 most populous countries get supervised hold-out forecasts on every category.
    # Skip Factbook aggregates ("World", "European Union") — including them would put
    # a meta-aggregate at the top of the populous list and crowd out real targets.
    AGGREGATE_ENTRIES = {"World", "European Union"}
    pops: List[Tuple[str, int]] = []
    for name, data in countries.items():
        if name in AGGREGATE_ENTRIES:
            continue
        pops.append((name, population_for(data)))
    pops.sort(key=lambda t: -t[1])
    top_countries = [n for n, _ in pops[:30]]

    cc_count = 0

    for country in top_countries:
        slug = slugify(country)
        for cat_id, label in cat_id_to_label.items():
            cdir = base / "countries" / slug / cat_id / "forecasts"
            if not (base / "countries" / slug / cat_id).exists():
                continue
            cdir.mkdir(parents=True, exist_ok=True)
            f = country_category_forecast(cat_id, slug, country, label)
            (cdir / f"{f['id']}.json").write_text(
                json.dumps(f, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            cc_count += 1

    # Top-level macro forecast
    top_forecasts = base / "forecasts"
    top_forecasts.mkdir(parents=True, exist_ok=True)
    f = macro_forecast()
    (top_forecasts / f"{f['id']}.json").write_text(
        json.dumps(f, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(
        f"wrote {cat_count} category-rollup forecasts, {cc_count} (country × category) "
        f"hold-out forecasts, 1 macro-trajectory forecast."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
