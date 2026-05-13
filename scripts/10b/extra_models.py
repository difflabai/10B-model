#!/usr/bin/env python3
"""Generate the top-up models that are not (country × category) cells:

- global.10B.dynamics — unsupervised macro-dynamics model (k-means clusters
  on the country needs profile matrix). Output is `runs/macro-dynamics.json`,
  produced by `scripts/10b/dynamics.py`.
- global.10B.supervised-trajectory — supervised hold-out trajectory head.
- global.10B.personal-agent — agent-facing query layer over the embedding.

These three live alongside the per-cell models to keep the model graph
complete and to surface the supervised/unsupervised split the project
description calls for.
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


def write(path: Path, doc: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def io(name: str, kind: str, desc: str) -> Dict[str, str]:
    return {"name": name, "kind": kind, "description": desc}


def comp(cid: str, name: str, role: str, syms: List[str] | None = None) -> Dict[str, Any]:
    return {"id": cid, "name": name, "role": role, "crate_path": None, "key_symbols": syms or []}


def param(k: str, v: str, d: str | None = None) -> Dict[str, Any]:
    out = {"key": k, "value": v}
    if d is not None:
        out["description"] = d
    return out


def ref(label: str, kind: str, location: str) -> Dict[str, str]:
    return {"label": label, "kind": kind, "location": location}


def dep(target: str, kind: str, note: str) -> Dict[str, Any]:
    return {"target_model_id": target, "kind": kind, "note": note}


def needs_tree() -> Dict[str, Any]:
    return json.loads((BASE / "needs-tree.json").read_text())


def category_ids() -> List[str]:
    return list(needs_tree()["categories"].keys())


def country_slugs() -> List[str]:
    cdir = BASE / "countries"
    return sorted([p.name for p in cdir.iterdir() if p.is_dir()])


def macro_dynamics_model() -> None:
    cats = category_ids()
    slugs = country_slugs()
    meta = {
        "id": "global.10B.dynamics",
        "name": "10B macro-dynamics — unsupervised cluster discovery",
        "kind": "sector_economic",
        "blurb": (
            "Unsupervised k-means clustering of the country × category needs profile matrix. "
            "Reveals hidden dynamics of the macro space: clusters, peer groups, attractors."
        ),
        "mechanism": (
            "Loads the country × category satisfaction matrix produced by `scripts/10b/scorer.py`, "
            "performs k-means++ initialised k-means clustering with deterministic seed, and emits "
            "cluster assignments, centroids, and per-country nearest-peer lists. The clusters are "
            "the unsupervised reveal of macro-space structure called for by the project: which "
            "needs profiles repeat across populations, where the attractors sit, and which countries "
            "sit at transition boundaries between clusters."
        ),
        "components": [
            comp("matrix-loader", "Country profile matrix loader", "Loads scored country profiles."),
            comp("kmeans", "k-means++ engine", "Deterministic seeded clustering."),
            comp("peers", "Peer-distance index", "Per-country k-nearest-neighbour lookup over the needs profile."),
            comp("labeler", "Cluster labeller", "Names each cluster by its dominant strengths and gaps."),
        ],
        "inputs": [
            io("country-profiles", "matrix", f"({len(slugs)} countries × {len(cats)} categories) satisfaction matrix."),
        ],
        "outputs": [
            io("macro-dynamics", "report", "Cluster centroids, sizes, labels, and per-country assignments."),
            io("country-peers", "graph", "Per-country nearest-peer lists for personal-agent peer-comparison."),
        ],
        "parameters": [
            param("country-count", str(len(slugs))),
            param("category-count", str(len(cats))),
            param("k", "6", "Number of clusters."),
            param("seed", "42", "Deterministic seed."),
            param("init", "k-means++"),
            param("max-iters", "60"),
        ],
        "references": [
            ref("MacQueen (1967) — k-means", "paper", "macqueen-1967"),
            ref("Arthur & Vassilvitskii (2007) — k-means++", "paper", "arthur-vassilvitskii-2007"),
            ref("scripts/10b/dynamics.py", "spec", "scripts/10b/dynamics.py"),
        ],
        "depends_on": [dep("global.10B", "depends_on", "Top-level 10B model owns this dynamics head.")]
        + [dep(f"global.10B.countries.{s}", "consumes_from", f"Country profile for {s}.") for s in slugs[:50]],
    }
    run = {
        "modelId": "global.10B.dynamics",
        "engine": "closed-form",
        "inputs": {
            "country-profiles": {"glob": "../countries/*/runs/output.json"},
            "needs-tree": {"path": "../needs-tree.json"},
        },
        "spec": {"inline": {"algorithm": "k-means++", "k": 6, "seed": 42}},
        "output": "../runs/macro-dynamics.json",
    }
    d = BASE / "dynamics"
    write(d / "model.meta.json", meta)
    write(d / "model.run.json", run)


def supervised_trajectory_model() -> None:
    cats = category_ids()
    slugs = country_slugs()
    meta = {
        "id": "global.10B.supervised-trajectory",
        "name": "10B supervised trajectory — hold-out predictor",
        "kind": "forecast_harness",
        "blurb": (
            "Supervised head: predicts hold-out sociodemographic characteristics from the "
            "10B macro-embedding. Validates that the embedding meaningfully captures the "
            "human needs of populations beyond the indicators it was trained on."
        ),
        "mechanism": (
            "For each held-out indicator (e.g. life expectancy, fertility rate, internet penetration) "
            "trains a quintile predictor on 80% of countries using only the 10B macro-embedding as "
            "features, evaluates on the remaining 20%, and reports area under the curve.\n\n"
            "Reproduces the project's stated supervised trajectory: the embedding model that captures "
            "the human needs of a population is validated by predicting hold-outs."
        ),
        "components": [
            comp("splitter", "Hold-out splitter", "Stratified 80/20 split with deterministic seed."),
            comp("trainer", "Quintile predictor trainer", "Logistic regression per indicator over the embedding."),
            comp("scorer", "AUC scorer", "Macro-averaged AUC across hold-out indicators."),
        ],
        "inputs": [
            io("embedding", "embedding", "10B macro-embedding (country-level)."),
            io("holdout-indicators", "indicator-set", "Sociodemographic targets withheld from the scoring step."),
        ],
        "outputs": [
            io("auc-by-indicator", "table", "Per-indicator AUC scores."),
            io("aggregate-auc", "scalar", "Macro-averaged AUC."),
        ],
        "parameters": [
            param("split", "80/20"),
            param("seed", "42"),
            param("classifier", "logistic-regression"),
            param("targets", "life-expectancy, fertility-rate, internet-penetration, gdp-quintile, gini-quintile"),
        ],
        "references": [
            ref("OECD Better Life Index", "url", "https://www.oecdbetterlifeindex.org/"),
            ref("ROC AUC — Hanley & McNeil 1982", "paper", "hanley-mcneil-1982"),
        ],
        "depends_on": [dep("global.10B", "depends_on", "Supervised head of the top-level 10B model.")],
    }
    run = {
        "modelId": "global.10B.supervised-trajectory",
        "engine": "monte-carlo",
        "inputs": {
            "embedding": {"path": "../runs/macro-embedding.json"},
            "holdout-targets": {"value": [
                "life-expectancy",
                "fertility-rate",
                "internet-penetration",
                "gdp-quintile",
                "gini-quintile",
            ]},
        },
        "spec": {"inline": {"split": [0.8, 0.2], "seed": 42, "classifier": "logreg", "num_samples": 1000}},
        "output": "../runs/supervised-auc.json",
    }
    d = BASE / "supervised-trajectory"
    write(d / "model.meta.json", meta)
    write(d / "model.run.json", run)


def personal_agent_model() -> None:
    meta = {
        "id": "global.10B.personal-agent",
        "name": "10B personal-agent query layer",
        "kind": "sector_economic",
        "blurb": (
            "Agent-facing query surface over the 10B embedding. Answers the three founding "
            "questions: How can I connect with my neighbors? · What economic value can I bring "
            "to my community? · How can I effectively advocate for change?"
        ),
        "mechanism": (
            "For a given user (resolved to a country and optionally a sub-region), produces:\n\n"
            "  • **Connect** — the country's belonging-category gaps and a list of peer countries "
            "    that have closed similar gaps successfully.\n"
            "  • **Contribute** — the country's work + education category strengths and weaknesses, "
            "    surfaced as economic opportunities the user can pursue.\n"
            "  • **Advocate** — the country's agency + governance category gaps, plus the relative "
            "    distance to the global mean on environment / safety, surfaced as advocacy levers."
        ),
        "components": [
            comp("connect", "Connect surface", "Belonging gap + peer-country comparison."),
            comp("contribute", "Contribute surface", "Work+education strengths/weaknesses."),
            comp("advocate", "Advocate surface", "Agency+governance levers + global comparators."),
            comp("query", "Query layer", "Agent-facing query API over the embedding."),
        ],
        "inputs": [
            io("embedding", "embedding", "10B macro-embedding."),
            io("user-context", "context", "User's resolved country and optional region."),
            io("peers", "graph", "Country peer index from global.10B.dynamics."),
        ],
        "outputs": [
            io("connect", "report", "Community-building suggestions for the user."),
            io("contribute", "report", "Economic-contribution suggestions for the user."),
            io("advocate", "report", "Advocacy-lever suggestions for the user."),
        ],
        "parameters": [
            param("design-question-1", "How can I connect with my neighbors?"),
            param("design-question-2", "What economic value can I bring to my community?"),
            param("design-question-3", "How can I effectively advocate for change?"),
        ],
        "references": [
            ref("10B project description", "spec", "registry/global/10B/needs-tree.json"),
        ],
        "depends_on": [
            dep("global.10B", "depends_on", "Top-level 10B model is the embedding source."),
            dep("global.10B.dynamics", "consumes_from", "Cluster labels and peer-country lists."),
        ],
    }
    run = {
        "modelId": "global.10B.personal-agent",
        "engine": "closed-form",
        "inputs": {
            "embedding": {"path": "../runs/macro-embedding.json"},
            "dynamics": {"path": "../runs/macro-dynamics.json"},
        },
        "spec": {"inline": {"role": "query-surface"}},
        "output": "./runs/agent-context.json",
    }
    d = BASE / "personal-agent"
    write(d / "model.meta.json", meta)
    write(d / "model.run.json", run)


def main() -> int:
    macro_dynamics_model()
    supervised_trajectory_model()
    personal_agent_model()
    print("wrote 3 top-up models (dynamics, supervised-trajectory, personal-agent).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
