#!/usr/bin/env python3
"""Generate the global/10B/* model registry from countries.json + needs-tree.json.

Output structure (under registry root, default ./registry):

    global/10B/
        needs-tree.json                     (already authored, top-level schema)
        model.meta.json                     (10B index — depends on every country rollup)
        model.run.json
        categories/<cat>/                   (cross-country category rollups, 15 total)
            model.meta.json
            model.run.json
        countries/<slug>/                   (per-country rollup, ~258 total)
            model.meta.json
            model.run.json
            <category>/                     (per-country, per-category model — ~258*15 ≈ 3870 total)
                model.meta.json
                model.run.json
                indicators.json             (the raw country-data slice this model consumes)

Model IDs are dot-separated, e.g.:
    global.10B
    global.10B.categories.food
    global.10B.countries.afghanistan
    global.10B.countries.afghanistan.food
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _paths import (  # noqa: E402
    countries_json_path,
    registry_root,
    require_countries_json,
    tenb_root,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
COUNTRIES_JSON = countries_json_path()


def _needs_tree_path() -> Path:
    return tenb_root() / "needs-tree.json"


def slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "unknown"


def country_dot_id(name: str) -> str:
    return slugify(name)


def safe_get(country: Dict[str, Any], key: str) -> str | None:
    v = country.get(key)
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        if not v or v in ("(NA)", "NA", "see entry for", "see entry"):
            return None
        return v
    return str(v)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def io_spec(name: str, kind: str, description: str) -> Dict[str, str]:
    return {"name": name, "kind": kind, "description": description}


def reference(label: str, kind: str, location: str) -> Dict[str, str]:
    return {"label": label, "kind": kind, "location": location}


def parameter_row(key: str, value: str, description: str | None = None) -> Dict[str, Any]:
    row: Dict[str, Any] = {"key": key, "value": value}
    if description is not None:
        row["description"] = description
    return row


def component(
    cid: str, name: str, role: str, key_symbols: List[str] | None = None
) -> Dict[str, Any]:
    return {
        "id": cid,
        "name": name,
        "role": role,
        "crate_path": None,
        "key_symbols": key_symbols or [],
    }


def model_meta(
    *,
    model_id: str,
    name: str,
    kind: str,
    blurb: str,
    mechanism: str,
    components: List[Dict[str, Any]],
    inputs: List[Dict[str, Any]],
    outputs: List[Dict[str, Any]],
    parameters: List[Dict[str, Any]],
    references: List[Dict[str, Any]],
    depends_on: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    return {
        "id": model_id,
        "name": name,
        "kind": kind,
        "blurb": blurb,
        "mechanism": mechanism,
        "components": components,
        "inputs": inputs,
        "outputs": outputs,
        "parameters": parameters,
        "references": references,
        "depends_on": depends_on or [],
    }


def model_run(
    *,
    model_id: str,
    engine: str,
    inputs: Dict[str, Any] | None = None,
    spec: Dict[str, Any] | None = None,
    output: str = "./runs/output.json",
) -> Dict[str, Any]:
    return {
        "modelId": model_id,
        "engine": engine,
        "inputs": inputs or {},
        "spec": spec or {"inline": {}},
        "output": output,
    }


def category_country_model(
    *,
    country_name: str,
    country_slug: str,
    cat_id: str,
    cat_def: Dict[str, Any],
    country_data: Dict[str, Any],
) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    model_id = f"global.10B.countries.{country_slug}.{cat_id}"
    label = cat_def["label"]
    engine = cat_def.get("engine", "closed-form")
    kind = "forecast_harness" if engine == "monte-carlo" else "sector_economic"

    indicators_present: Dict[str, str] = {}
    for ind in cat_def.get("indicators", []):
        v = safe_get(country_data, ind)
        if v:
            indicators_present[ind] = v

    coverage = (
        len(indicators_present) / max(1, len(cat_def.get("indicators", []) or [1]))
    )

    inputs = [
        io_spec(
            "country-indicators",
            "country_factbook_slice",
            f"Slice of CIA World Factbook fields covering {label.lower()} for {country_name}.",
        ),
        io_spec(
            "needs-tree",
            "schema",
            "Reference to global.10B.needs-tree which defines the supervisory schema.",
        ),
    ]
    outputs = [
        io_spec(
            "satisfaction-score",
            "scalar",
            f"Composite needs-satisfaction score for {label.lower()} in {country_name}, in [0,1].",
        ),
        io_spec(
            "indicator-fingerprint",
            "embedding",
            "Per-category embedding feeding the macro-space unsupervised model.",
        ),
        io_spec(
            "evidence-trace",
            "provenance",
            "References to the specific factbook fields and values consumed.",
        ),
    ]
    parameters = [
        parameter_row("country", country_name),
        parameter_row("category", label),
        parameter_row(
            "indicator-coverage",
            f"{coverage:.2f}",
            "Fraction of category indicators with non-null values for this country.",
        ),
        parameter_row(
            "indicators-present",
            str(len(indicators_present)),
            f"of {len(cat_def.get('indicators', []))} indicators populated.",
        ),
    ]
    components = [
        component(
            "ingester",
            "Factbook ingester",
            "Pulls the relevant factbook fields and normalises units.",
            ["safe_get", "normalise_units"],
        ),
        component(
            "scorer",
            "Closed-form scorer" if engine == "closed-form" else "Monte-Carlo scorer",
            "Maps normalised indicators to a [0,1] satisfaction score.",
            ["score_category"],
        ),
        component(
            "embedder",
            "Indicator embedder",
            "Produces a category-level embedding feeding the macro-space model.",
            ["embed_category"],
        ),
    ]
    refs = [
        reference("10B Needs Tree", "spec", "global/10B/needs-tree.json"),
        reference("CIA World Factbook", "url", "https://www.cia.gov/the-world-factbook/"),
    ]
    for fw in cat_def.get("frameworks", []):
        refs.append(reference(fw, "spec", f"frameworks/{fw}"))

    blurb = (
        f"{label} for {country_name}: {cat_def['blurb']} "
        f"Driven by {len(indicators_present)} of "
        f"{len(cat_def.get('indicators', []))} CIA World Factbook indicators."
    )

    mechanism = (
        f"This model captures the **{label.lower()}** dimension of human need for "
        f"**{country_name}**.\n\n"
        f"It ingests the relevant slice of the CIA World Factbook (see indicators.json) "
        f"and produces a composite satisfaction score in [0,1] together with a category-level "
        f"embedding that feeds the unsupervised macro-space model.\n\n"
        f"Engine: `{engine}`. The closed-form variant scores indicators on a normalised "
        f"piecewise-linear ladder per indicator type and aggregates by capability-weighted mean. "
        f"The Monte-Carlo variant samples from per-indicator uncertainty distributions to produce "
        f"interval estimates and feed the supervised hold-out predictions.\n\n"
        f"Frameworks: {', '.join(cat_def.get('frameworks', []))}."
    )

    meta = model_meta(
        model_id=model_id,
        name=f"{country_name} — {label}",
        kind=kind,
        blurb=blurb,
        mechanism=mechanism,
        components=components,
        inputs=inputs,
        outputs=outputs,
        parameters=parameters,
        references=refs,
        depends_on=[
            {
                "target_model_id": "global.10B.needs-tree",
                "kind": "depends_on",
                "note": "Schema dependency on the 10B needs tree.",
            },
            {
                "target_model_id": f"global.10B.categories.{cat_id}",
                "kind": "consumes_from",
                "note": "Cross-country category rollup that aggregates this model along with peers.",
            },
        ],
    )

    run = model_run(
        model_id=model_id,
        engine=engine,
        inputs={
            "country": {"value": country_name},
            "category": {"value": cat_id},
            "indicators": {"path": "./indicators.json"},
            "needs-tree": {"path": "../../../needs-tree.json"},
        },
        spec={"inline": {"engine": engine, "category": cat_id}},
        output="./runs/output.json",
    )

    indicators_doc = {
        "country": country_name,
        "category": cat_id,
        "label": label,
        "engine": engine,
        "indicators": [
            {
                "field": ind,
                "value": indicators_present.get(ind),
                "present": ind in indicators_present,
            }
            for ind in cat_def.get("indicators", [])
        ],
        "coverage": coverage,
    }
    return meta, run, indicators_doc


def country_rollup_model(
    *,
    country_name: str,
    country_slug: str,
    needs_tree: Dict[str, Any],
    category_coverage: Dict[str, float],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    model_id = f"global.10B.countries.{country_slug}"
    cats = list(needs_tree["categories"].keys())
    components = [
        component(
            f"cat-{c}",
            f"{needs_tree['categories'][c]['label']} feed",
            f"Consumes global.10B.countries.{country_slug}.{c}",
            ["aggregate_category"],
        )
        for c in cats
    ]
    inputs = [
        io_spec(
            f"{c}-score",
            "scalar",
            f"{needs_tree['categories'][c]['label']} satisfaction score for {country_name}.",
        )
        for c in cats
    ]
    outputs = [
        io_spec(
            "country-needs-vector",
            "embedding",
            "Country-level needs embedding spanning all 15 categories.",
        ),
        io_spec(
            "tier-scores",
            "vector",
            "Per-tier (subsistence / development / agency) satisfaction averages.",
        ),
        io_spec(
            "country-summary",
            "report",
            "Plain-text summary of needs gaps and strengths used by personal agents.",
        ),
    ]
    avg_coverage = sum(category_coverage.values()) / max(1, len(category_coverage))
    parameters = [
        parameter_row("country", country_name),
        parameter_row("category-count", str(len(cats))),
        parameter_row(
            "average-coverage",
            f"{avg_coverage:.2f}",
            "Mean indicator coverage across categories.",
        ),
    ] + [
        parameter_row(f"{c}-coverage", f"{category_coverage.get(c, 0.0):.2f}")
        for c in cats
    ]
    refs = [
        reference("10B Needs Tree", "spec", "global/10B/needs-tree.json"),
        reference("CIA World Factbook", "url", "https://www.cia.gov/the-world-factbook/"),
    ]
    blurb = (
        f"Country-level rollup for **{country_name}** spanning all "
        f"{len(cats)} needs categories, feeding the global.10B macro-space model. "
        f"Average indicator coverage: {avg_coverage:.0%}."
    )
    mechanism = (
        f"Aggregates the 15 per-category models for {country_name} into a single "
        f"country needs embedding and a set of tier-level (subsistence / development / agency) "
        f"satisfaction averages.\n\n"
        f"Each category model contributes a satisfaction score and a category embedding; the "
        f"rollup concatenates the embeddings, weights category contributions by indicator coverage, "
        f"and emits a country-level vector along with a plain-text summary suitable for consumption "
        f"by a personal agent helping the user navigate community building and economic transition."
    )
    meta = model_meta(
        model_id=model_id,
        name=f"{country_name} — needs rollup",
        kind="sector_economic",
        blurb=blurb,
        mechanism=mechanism,
        components=components,
        inputs=inputs,
        outputs=outputs,
        parameters=parameters,
        references=refs,
        depends_on=[
            {
                "target_model_id": f"global.10B.countries.{country_slug}.{c}",
                "kind": "consumes_from",
                "note": f"Per-country, per-category model: {needs_tree['categories'][c]['label']}",
            }
            for c in cats
        ],
    )
    run = model_run(
        model_id=model_id,
        engine="closed-form",
        inputs={
            "country": {"value": country_name},
            "category-models": {
                "list": [
                    f"global.10B.countries.{country_slug}.{c}" for c in cats
                ]
            },
        },
        spec={"inline": {"rollup": "country", "weights": "indicator-coverage"}},
        output="./runs/output.json",
    )
    return meta, run


def category_world_rollup(
    *,
    cat_id: str,
    cat_def: Dict[str, Any],
    country_slugs: List[str],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    model_id = f"global.10B.categories.{cat_id}"
    label = cat_def["label"]
    components = [
        component(
            "aggregator",
            f"{label} world aggregator",
            "Aggregates per-country category scores by population-weighted mean.",
            ["population_weighted_mean"],
        ),
        component(
            "ranker",
            f"{label} country ranker",
            "Ranks countries by category satisfaction with confidence intervals.",
            ["rank_with_ci"],
        ),
        component(
            "macro-embedder",
            f"{label} macro-embedder",
            "Produces a 16-dim global category embedding for the unsupervised macro-space.",
            ["embed_macro"],
        ),
    ]
    inputs = [
        io_spec(
            f"{cat_id}-country-scores",
            "scalar-list",
            f"Per-country satisfaction scores for {label.lower()}.",
        )
    ]
    outputs = [
        io_spec(
            f"{cat_id}-world-mean",
            "scalar",
            f"Population-weighted world mean for {label.lower()}.",
        ),
        io_spec(
            f"{cat_id}-country-ranking",
            "ranking",
            f"Country-level ranking on {label.lower()}.",
        ),
        io_spec(
            f"{cat_id}-macro-embedding",
            "embedding",
            f"{label} contribution to the global 10B macro-space embedding.",
        ),
    ]
    parameters = [
        parameter_row("category", label),
        parameter_row("countries-covered", str(len(country_slugs))),
        parameter_row(
            "frameworks",
            ", ".join(cat_def.get("frameworks", [])),
            "Theoretical frameworks the category draws from.",
        ),
    ]
    refs = [
        reference("10B Needs Tree", "spec", "global/10B/needs-tree.json"),
    ]
    blurb = (
        f"World rollup for **{label.lower()}** across {len(country_slugs)} countries — "
        f"the cross-country slice of the 10B model along the {cat_id} dimension."
    )
    mechanism = (
        f"Aggregates the per-country {cat_id} models into a population-weighted world mean, "
        f"a country-level ranking with confidence intervals, and a macro-space embedding feeding "
        f"the unsupervised dynamics model.\n\n"
        f"This is the supervised trajectory's primary anchor for the {cat_id} dimension: holdout "
        f"datasets of sociodemographic characteristics are predicted via the per-country models "
        f"and validated against the world mean and ranking produced here."
    )
    meta = model_meta(
        model_id=model_id,
        name=f"World — {label}",
        kind="sector_economic",
        blurb=blurb,
        mechanism=mechanism,
        components=components,
        inputs=inputs,
        outputs=outputs,
        parameters=parameters,
        references=refs,
        depends_on=[
            {
                "target_model_id": f"global.10B.countries.{slug}.{cat_id}",
                "kind": "consumes_from",
                "note": f"Per-country {cat_id} model.",
            }
            for slug in country_slugs
        ],
    )
    run = model_run(
        model_id=model_id,
        engine="closed-form",
        inputs={
            "category": {"value": cat_id},
            "country-models": {
                "list": [
                    f"global.10B.countries.{slug}.{cat_id}" for slug in country_slugs
                ]
            },
        },
        spec={"inline": {"rollup": "category", "weights": "population"}},
        output="./runs/output.json",
    )
    return meta, run


def root_index_model(
    *,
    needs_tree: Dict[str, Any],
    country_slugs: List[str],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    cats = list(needs_tree["categories"].keys())
    model_id = "global.10B"
    components = [
        component(
            "macro-embedder",
            "Macro-space embedder",
            "Embeds (country, category) pairs into the unsupervised dynamics space.",
            ["macro_embed"],
        ),
        component(
            "supervised-trajectory",
            "Supervised trajectory head",
            "Predicts hold-out sociodemographic characteristics from the embedding.",
            ["holdout_predict"],
        ),
        component(
            "unsupervised-dynamics",
            "Unsupervised dynamics head",
            "Reveals hidden dynamics of the macro-space (clusters, transitions, attractors).",
            ["macro_dynamics"],
        ),
        component(
            "agent-interface",
            "Personal-agent interface",
            "Surfaces relevant slices of the embedding to a user's personal AI agent.",
            ["agent_query"],
        ),
    ]
    inputs = [
        io_spec(
            "country-rollups",
            "embedding-list",
            f"All {len(country_slugs)} country-level needs embeddings.",
        ),
        io_spec(
            "category-rollups",
            "embedding-list",
            f"All {len(cats)} cross-country category embeddings.",
        ),
        io_spec(
            "holdout-targets",
            "dataset",
            "Held-out sociodemographic datasets for supervised validation.",
        ),
    ]
    outputs = [
        io_spec(
            "macro-embedding",
            "embedding",
            "The 10B human-needs embedding spanning all (country × category) pairs.",
        ),
        io_spec(
            "macro-dynamics",
            "report",
            "Hidden dynamics of the macro-space — clusters, transitions, attractors.",
        ),
        io_spec(
            "personal-agent-context",
            "context",
            "Context surfaces for personal agents helping users connect, contribute, and advocate.",
        ),
    ]
    parameters = [
        parameter_row("country-count", str(len(country_slugs))),
        parameter_row("category-count", str(len(cats))),
        parameter_row("model-count", str(len(country_slugs) * (len(cats) + 1) + len(cats) + 1)),
        parameter_row(
            "design-questions",
            "How can I connect with my neighbors? · What economic value can I bring to my community? · How can I effectively advocate for change?",
            "User-facing questions the system aims to support.",
        ),
    ]
    refs = [
        reference("10B Needs Tree", "spec", "global/10B/needs-tree.json"),
        reference("Maslow (1943)", "paper", "https://doi.org/10.1037/h0054346"),
        reference("Max-Neef (1991) Human Scale Development", "paper", "max-neef-1991"),
        reference("Doyal & Gough (1991) A Theory of Human Need", "paper", "doyal-gough-1991"),
        reference("UN Sustainable Development Goals", "url", "https://sdgs.un.org/goals"),
    ]
    blurb = (
        "Top-level **10B** model — captures the human needs of every population on earth as a "
        f"({len(country_slugs)} countries × {len(cats)} categories) embedding, jointly trained on a supervised "
        "hold-out trajectory of sociodemographic characteristics and an unsupervised dynamics head "
        "that reveals attractors and transitions in the macro-space."
    )
    mechanism = (
        "Two converging trajectories meet at this model:\n\n"
        "**Top-down**: countries × categories × indicators from the CIA World Factbook and other public datasets. "
        "Each (country × category) pair is captured by a per-category model whose embedding feeds this rollup.\n\n"
        "**Bottom-up**: simulated human behaviour and online activity, fed via personal-agent traces and "
        "the work-and-economy and communications categories.\n\n"
        "Both meet here as an embedding model that captures the human needs of a population. "
        "The supervised trajectory predicts hold-out datasets of sociodemographic characteristics; "
        "the unsupervised component reveals hidden dynamics of the macro-space. "
        "Over time the system supports personal agents helping users build community and navigate the "
        "AI economic transition — answering: 'How can I connect with my neighbors?', "
        "'What economic value can I bring to my community?', and 'How can I effectively advocate for change?'"
    )
    meta = model_meta(
        model_id=model_id,
        name="10B — human-needs macro model",
        kind="forecast_harness",
        blurb=blurb,
        mechanism=mechanism,
        components=components,
        inputs=inputs,
        outputs=outputs,
        parameters=parameters,
        references=refs,
        depends_on=[
            {
                "target_model_id": f"global.10B.categories.{c}",
                "kind": "consumes_from",
                "note": f"Cross-country rollup for {needs_tree['categories'][c]['label']}",
            }
            for c in cats
        ]
        + [
            {
                "target_model_id": f"global.10B.countries.{slug}",
                "kind": "consumes_from",
                "note": f"Per-country rollup",
            }
            for slug in country_slugs
        ]
        + [
            {
                "target_model_id": "global.10B.needs-tree",
                "kind": "depends_on",
                "note": "Schema dependency on the 10B needs tree.",
            }
        ],
    )
    run = model_run(
        model_id=model_id,
        engine="monte-carlo",
        inputs={
            "country-rollups": {
                "list": [f"global.10B.countries.{s}" for s in country_slugs]
            },
            "category-rollups": {
                "list": [f"global.10B.categories.{c}" for c in cats]
            },
            "needs-tree": {"path": "./needs-tree.json"},
        },
        spec={"inline": {"head": "macro", "embedding_dim": 384, "num_samples": 1024}},
        output="./runs/macro-embedding.json",
    )
    return meta, run


def main() -> int:
    base = tenb_root()
    only_n = int(os.environ.get("ONLY_N_COUNTRIES", "0"))

    countries = json.loads(require_countries_json().read_text(encoding="utf-8"))
    needs_tree_path = base / "needs-tree.json"
    if not needs_tree_path.exists():
        raise SystemExit(
            f"needs-tree.json not found at {needs_tree_path}. "
            "Run scripts from a checkout of difflabai/10B-model (or point $BWM_10B_ROOT at one) "
            "and make sure global/10B/needs-tree.json is present."
        )
    needs_tree = json.loads(needs_tree_path.read_text(encoding="utf-8"))
    base.mkdir(parents=True, exist_ok=True)

    # The CIA Factbook has a synthetic "World" entry that aggregates every
    # country. Including it as a country here would double-count every
    # population-weighted rollup (every country counted once individually +
    # once via the World aggregate). Drop it before slugifying.
    AGGREGATE_ENTRIES = {"World", "European Union"}
    country_names = [
        name for name in countries.keys() if name not in AGGREGATE_ENTRIES
    ]
    if only_n:
        country_names = country_names[:only_n]
    country_slugs = [country_dot_id(n) for n in country_names]
    cats = list(needs_tree["categories"].keys())

    total_models = 0

    needs_tree_meta = model_meta(
        model_id="global.10B.needs-tree",
        name="10B Needs Tree",
        kind="sector_economic",
        blurb=needs_tree["description"],
        mechanism=(
            "Schema-only model. Defines the 15 categories, three tiers, theoretical lineage, "
            "and the indicator slices each (country × category) model is expected to populate. "
            "All other 10B models depend on this schema."
        ),
        components=[
            component(
                "schema",
                "Needs schema",
                "Holds the canonical category definitions, frameworks, and indicators.",
                ["needs_tree"],
            )
        ],
        inputs=[],
        outputs=[
            io_spec(
                "schema",
                "spec",
                "The canonical needs-tree schema referenced by all 10B models.",
            )
        ],
        parameters=[
            parameter_row("category-count", str(len(cats))),
            parameter_row("tier-count", str(len(needs_tree["tiers"]))),
        ],
        references=[reference("Needs Tree JSON", "spec", "needs-tree.json")],
    )
    schema_dir = base / "schema"
    write_json(schema_dir / "model.meta.json", needs_tree_meta)
    write_json(
        schema_dir / "model.run.json",
        model_run(
            model_id="global.10B.needs-tree",
            engine="closed-form",
            inputs={"schema": {"path": "../needs-tree.json"}},
            spec={"inline": {"role": "schema"}},
            output="./runs/output.json",
        ),
    )
    total_models += 1

    for cat_id, cat_def in needs_tree["categories"].items():
        cat_dir = base / "categories" / cat_id
        meta, run = category_world_rollup(
            cat_id=cat_id, cat_def=cat_def, country_slugs=country_slugs
        )
        write_json(cat_dir / "model.meta.json", meta)
        write_json(cat_dir / "model.run.json", run)
        total_models += 1

    for country_name, country_slug in zip(country_names, country_slugs):
        country_data = countries[country_name]
        country_dir = base / "countries" / country_slug
        category_coverage: Dict[str, float] = {}
        for cat_id, cat_def in needs_tree["categories"].items():
            cat_dir = country_dir / cat_id
            meta, run, indicators_doc = category_country_model(
                country_name=country_name,
                country_slug=country_slug,
                cat_id=cat_id,
                cat_def=cat_def,
                country_data=country_data,
            )
            write_json(cat_dir / "model.meta.json", meta)
            write_json(cat_dir / "model.run.json", run)
            write_json(cat_dir / "indicators.json", indicators_doc)
            category_coverage[cat_id] = indicators_doc["coverage"]
            total_models += 1
        meta, run = country_rollup_model(
            country_name=country_name,
            country_slug=country_slug,
            needs_tree=needs_tree,
            category_coverage=category_coverage,
        )
        write_json(country_dir / "model.meta.json", meta)
        write_json(country_dir / "model.run.json", run)
        total_models += 1

    meta, run = root_index_model(
        needs_tree=needs_tree, country_slugs=country_slugs
    )
    write_json(base / "model.meta.json", meta)
    write_json(base / "model.run.json", run)
    total_models += 1

    print(
        f"Generated {total_models} models under {base}\n"
        f"  countries: {len(country_names)}\n"
        f"  categories: {len(cats)}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
