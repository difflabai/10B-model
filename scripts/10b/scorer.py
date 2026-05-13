#!/usr/bin/env python3
"""Closed-form scorer for 10B per-country, per-category models.

Reads `<model-dir>/indicators.json`, normalises each indicator into a
[0,1] satisfaction score using indicator-specific heuristics, and writes
`<model-dir>/runs/output.json` with the composite score, the per-indicator
contributions, and a deterministic 16-dim category embedding.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import tenb_root  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE = tenb_root()


NUMERIC_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def first_number(text: str) -> float | None:
    if not isinstance(text, str):
        return None
    m = NUMERIC_RE.search(text.replace("−", "-"))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def first_percent(text: str) -> float | None:
    if not isinstance(text, str):
        return None
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*%", text)
    if not m:
        return None
    try:
        return float(m.group(1)) / 100.0
    except ValueError:
        return None


def piecewise(value: float, anchors: List[Tuple[float, float]]) -> float:
    """Piecewise-linear ladder. anchors = [(input, score)] sorted ascending by input.

    Clamps to [0,1] outside the range.
    """
    anchors = sorted(anchors, key=lambda t: t[0])
    if value <= anchors[0][0]:
        return max(0.0, min(1.0, anchors[0][1]))
    if value >= anchors[-1][0]:
        return max(0.0, min(1.0, anchors[-1][1]))
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if x0 <= value <= x1:
            t = (value - x0) / (x1 - x0)
            return max(0.0, min(1.0, y0 + t * (y1 - y0)))
    return 0.5


SCORE_RULES: Dict[str, Dict[str, Any]] = {
    "Environment: Food insecurity - severe localized food insecurity": {
        "kind": "presence-bad",
        "absent_score": 0.85,
        "present_score": 0.25,
    },
    "Economy: Agricultural products": {"kind": "presence-good"},
    "Environment: Land use - agricultural land": {
        "kind": "percent",
        "anchors": [(0.0, 0.2), (15.0, 0.5), (40.0, 0.85), (80.0, 0.7)],
    },
    "Economy: GDP - composition, by sector of origin - agriculture": {
        "kind": "percent",
        "anchors": [(0.0, 0.4), (3.0, 0.85), (10.0, 0.7), (30.0, 0.45), (60.0, 0.25)],
    },
    "People and Society: Population - total": {"kind": "presence-good"},

    "Environment: Major rivers (by length in km)": {"kind": "presence-good"},
    "Environment: Major lakes (area sq km) - salt water lake(s)": {"kind": "presence-good"},
    "Environment: Major watersheds (area sq km)": {"kind": "presence-good"},
    "Geography: Climate": {"kind": "presence-good"},
    "People and Society: Drinking water source - improved - urban": {
        "kind": "percent",
        "anchors": [(50.0, 0.2), (80.0, 0.55), (95.0, 0.85), (100.0, 0.95)],
    },
    "People and Society: Sanitation facility access - improved - total": {
        "kind": "percent",
        "anchors": [(20.0, 0.15), (60.0, 0.5), (90.0, 0.85), (100.0, 0.95)],
    },

    "People and Society: Urbanization - urban population": {
        "kind": "percent",
        "anchors": [(10.0, 0.4), (40.0, 0.6), (70.0, 0.7), (95.0, 0.6)],
    },
    "People and Society: Major urban areas - population": {"kind": "presence-good"},
    "People and Society: Population distribution": {"kind": "presence-good"},

    "People and Society: Life expectancy at birth - total population": {
        "kind": "first-number",
        "anchors": [(50.0, 0.2), (65.0, 0.45), (75.0, 0.7), (82.0, 0.9), (88.0, 0.97)],
    },
    "People and Society: Life expectancy at birth - male": {
        "kind": "first-number",
        "anchors": [(50.0, 0.2), (65.0, 0.45), (75.0, 0.7), (82.0, 0.9), (88.0, 0.97)],
    },
    "People and Society: Life expectancy at birth - female": {
        "kind": "first-number",
        "anchors": [(50.0, 0.2), (65.0, 0.45), (75.0, 0.7), (82.0, 0.9), (88.0, 0.97)],
    },
    "People and Society: Infant mortality rate - total": {
        "kind": "first-number",
        "anchors": [(2.0, 0.97), (5.0, 0.85), (15.0, 0.6), (40.0, 0.3), (90.0, 0.1)],
    },
    "People and Society: Infant mortality rate - male": {
        "kind": "first-number",
        "anchors": [(2.0, 0.97), (5.0, 0.85), (15.0, 0.6), (40.0, 0.3), (90.0, 0.1)],
    },
    "People and Society: Infant mortality rate - female": {
        "kind": "first-number",
        "anchors": [(2.0, 0.97), (5.0, 0.85), (15.0, 0.6), (40.0, 0.3), (90.0, 0.1)],
    },
    "People and Society: Children under the age of 5 years underweight": {
        "kind": "percent",
        "anchors": [(0.0, 0.97), (5.0, 0.8), (15.0, 0.5), (30.0, 0.2)],
    },
    "People and Society: Currently married women (ages 15-49)": {"kind": "presence-good"},
    "People and Society: Current health expenditure": {
        "kind": "percent",
        "anchors": [(2.0, 0.2), (5.0, 0.55), (8.0, 0.8), (12.0, 0.95)],
    },
    "People and Society: Maternal mortality ratio": {
        "kind": "first-number",
        "anchors": [(2.0, 0.97), (10.0, 0.85), (50.0, 0.6), (200.0, 0.3), (800.0, 0.1)],
    },
    "People and Society: Physicians density": {
        "kind": "first-number",
        "anchors": [(0.1, 0.15), (0.5, 0.35), (1.5, 0.6), (3.5, 0.9), (6.0, 0.95)],
    },
    "People and Society: Hospital bed density": {
        "kind": "first-number",
        "anchors": [(0.5, 0.2), (2.0, 0.5), (5.0, 0.8), (10.0, 0.95)],
    },
    "People and Society: Major infectious diseases - degree of risk": {
        "kind": "risk-keyword",
    },
    "People and Society: Obesity - adult prevalence rate": {
        "kind": "percent",
        "anchors": [(0.0, 0.95), (10.0, 0.85), (25.0, 0.6), (40.0, 0.35), (60.0, 0.15)],
    },
    "People and Society: Tobacco use - total": {
        "kind": "percent",
        "anchors": [(0.0, 0.95), (15.0, 0.7), (30.0, 0.4), (50.0, 0.15)],
    },

    "Military and Security: Military and security forces": {"kind": "presence-good"},
    "Military and Security: Military expenditures": {
        "kind": "percent",
        "anchors": [(0.0, 0.5), (1.5, 0.7), (3.0, 0.6), (6.0, 0.35), (15.0, 0.1)],
    },
    "Terrorism: Terrorist group(s) - home based": {"kind": "presence-bad"},
    "Terrorism: Terrorist group(s) - foreign based": {"kind": "presence-bad"},
    "Transnational Issues: Disputes - international": {"kind": "presence-bad"},
    "Transnational Issues: Refugees and internally displaced persons - refugees (country of origin)": {
        "kind": "presence-bad"
    },

    "People and Society: Literacy - total population": {
        "kind": "percent",
        "anchors": [(20.0, 0.15), (60.0, 0.5), (90.0, 0.85), (100.0, 0.97)],
    },
    "People and Society: Education expenditures": {
        "kind": "percent",
        "anchors": [(1.0, 0.2), (3.5, 0.55), (5.5, 0.8), (8.0, 0.95)],
    },
    "People and Society: School life expectancy (primary to tertiary education) - total": {
        "kind": "first-number",
        "anchors": [(5.0, 0.2), (10.0, 0.5), (14.0, 0.8), (18.0, 0.95)],
    },
    "People and Society: Languages": {"kind": "presence-good"},
    "People and Society: Languages - major-language sample(s)": {"kind": "presence-good"},

    "Economy: Real GDP per capita": {
        "kind": "first-number",
        "anchors": [(1000.0, 0.15), (5000.0, 0.4), (15000.0, 0.65), (40000.0, 0.85), (90000.0, 0.97)],
    },
    "Economy: Real GDP growth rate": {
        "kind": "percent",
        "anchors": [(-10.0, 0.1), (-2.0, 0.4), (1.0, 0.55), (3.0, 0.75), (7.0, 0.95)],
    },
    "Economy: Inflation rate (consumer prices)": {
        "kind": "percent",
        "anchors": [(0.0, 0.85), (2.0, 0.95), (5.0, 0.7), (15.0, 0.35), (50.0, 0.05)],
    },
    "Economy: Labor force": {"kind": "presence-good"},
    "Economy: Unemployment rate": {
        "kind": "percent",
        "anchors": [(2.0, 0.95), (5.0, 0.8), (10.0, 0.55), (20.0, 0.25), (40.0, 0.05)],
    },
    "Economy: Population below poverty line": {
        "kind": "percent",
        "anchors": [(2.0, 0.97), (10.0, 0.8), (25.0, 0.5), (50.0, 0.2), (80.0, 0.05)],
    },
    "Economy: Gini Index coefficient - distribution of family income": {
        "kind": "first-number",
        "anchors": [(20.0, 0.95), (30.0, 0.8), (40.0, 0.6), (55.0, 0.3), (70.0, 0.1)],
    },

    "Energy: Electricity access - electrification - total population": {
        "kind": "percent",
        "anchors": [(20.0, 0.1), (60.0, 0.45), (90.0, 0.8), (100.0, 0.97)],
    },
    "Energy: Electricity access - electrification - urban areas": {
        "kind": "percent",
        "anchors": [(50.0, 0.3), (90.0, 0.8), (100.0, 0.97)],
    },
    "Energy: Electricity access - electrification - rural areas": {
        "kind": "percent",
        "anchors": [(10.0, 0.1), (50.0, 0.4), (90.0, 0.85), (100.0, 0.97)],
    },
    "Energy: Electricity - installed generating capacity": {"kind": "presence-good"},
    "Energy: Electricity - consumption": {"kind": "presence-good"},
    "Energy: Electricity generation sources - fossil fuels": {
        "kind": "percent",
        "anchors": [(0.0, 0.95), (30.0, 0.75), (60.0, 0.45), (90.0, 0.2)],
    },
    "Energy: Electricity generation sources - solar": {
        "kind": "percent",
        "anchors": [(0.0, 0.3), (5.0, 0.5), (15.0, 0.75), (40.0, 0.95)],
    },
    "Energy: Electricity generation sources - hydroelectricity": {
        "kind": "percent",
        "anchors": [(0.0, 0.4), (10.0, 0.6), (50.0, 0.85), (90.0, 0.95)],
    },
    "Energy: Electricity generation sources - wind": {
        "kind": "percent",
        "anchors": [(0.0, 0.4), (5.0, 0.6), (20.0, 0.85), (50.0, 0.95)],
    },
    "Energy: Electricity generation sources - nuclear": {
        "kind": "percent",
        "anchors": [(0.0, 0.5), (10.0, 0.7), (40.0, 0.85), (75.0, 0.9)],
    },
    "Energy: Electricity generation sources - biomass and waste": {
        "kind": "percent",
        "anchors": [(0.0, 0.5), (5.0, 0.65), (20.0, 0.8)],
    },
    "Energy: Energy consumption per capita": {"kind": "presence-good"},
    "Energy: Carbon dioxide emissions": {"kind": "presence-bad"},

    "Transportation: Heliports": {
        "kind": "first-number",
        "anchors": [(1.0, 0.4), (20.0, 0.65), (200.0, 0.85), (1000.0, 0.95)],
    },
    "Transportation: Roadways - unpaved": {"kind": "presence-good"},
    "Transportation: Railways - total": {
        "kind": "first-number",
        "anchors": [(100.0, 0.25), (5000.0, 0.55), (50000.0, 0.85), (200000.0, 0.97)],
    },
    "Transportation: National air transport system - annual freight traffic on registered air carriers": {
        "kind": "first-number",
        "anchors": [(1000.0, 0.3), (100000.0, 0.55), (1000000.0, 0.8), (10000000.0, 0.95)],
    },

    "Communications: Telephones - mobile cellular - total subscriptions": {"kind": "presence-good"},
    "Communications: Telephones - fixed lines - total subscriptions": {"kind": "presence-good"},
    "Communications: Broadband - fixed subscriptions - total": {"kind": "presence-good"},
    "Communications: Telecommunication systems - domestic": {"kind": "presence-good"},
    "Communications: Telecommunication systems - international": {"kind": "presence-good"},

    "Transportation: Roadways - total": {
        "kind": "first-number",
        "anchors": [(1000.0, 0.2), (50000.0, 0.5), (500000.0, 0.8), (5000000.0, 0.95)],
    },
    "Transportation: Roadways - paved": {
        "kind": "first-number",
        "anchors": [(500.0, 0.2), (20000.0, 0.5), (200000.0, 0.8), (2000000.0, 0.95)],
    },
    "Transportation: Airports": {
        "kind": "first-number",
        "anchors": [(1.0, 0.2), (10.0, 0.45), (100.0, 0.7), (1000.0, 0.9), (10000.0, 0.97)],
    },
    "Transportation: Pipelines": {"kind": "presence-good"},
    "Transportation: Waterways": {
        "kind": "first-number",
        "anchors": [(0.0, 0.4), (500.0, 0.55), (5000.0, 0.75), (50000.0, 0.9)],
    },
    "Transportation: National air transport system - annual passenger traffic on registered air carriers": {
        "kind": "first-number",
        "anchors": [(10000.0, 0.2), (1000000.0, 0.5), (50000000.0, 0.8), (500000000.0, 0.95)],
    },

    "Communications: Telephones - mobile cellular - subscriptions per 100 inhabitants": {
        "kind": "first-number",
        "anchors": [(20.0, 0.2), (60.0, 0.5), (100.0, 0.8), (160.0, 0.95)],
    },
    "Communications: Telephones - fixed lines - subscriptions per 100 inhabitants": {
        "kind": "first-number",
        "anchors": [(0.5, 0.4), (5.0, 0.55), (20.0, 0.75), (50.0, 0.9)],
    },
    "Communications: Internet users - percent of population": {
        "kind": "percent",
        "anchors": [(10.0, 0.15), (40.0, 0.45), (75.0, 0.75), (95.0, 0.95)],
    },
    "Communications: Broadband - fixed subscriptions - subscriptions per 100 inhabitants": {
        "kind": "first-number",
        "anchors": [(1.0, 0.15), (10.0, 0.45), (30.0, 0.75), (50.0, 0.95)],
    },
    "Communications: Telecommunication systems - general assessment": {"kind": "presence-good"},

    "Government: Government type": {"kind": "gov-type"},
    "Government: Legal system": {"kind": "presence-good"},
    "Government: Constitution - history": {"kind": "presence-good"},
    "Government: Suffrage": {"kind": "suffrage"},
    "Government: Executive branch - chief of state": {"kind": "presence-good"},
    "Government: International law organization participation": {"kind": "presence-good"},
    "Government: International organization participation": {"kind": "presence-good"},

    "Environment: Environment - current issues": {"kind": "presence-bad"},
    "Environment: Environment - international agreements - party to": {"kind": "presence-good"},
    "Environment: Air pollutants - particulate matter emissions": {
        "kind": "first-number",
        "anchors": [(5.0, 0.95), (15.0, 0.7), (35.0, 0.4), (80.0, 0.1)],
    },
    "Environment: Air pollutants - carbon dioxide emissions": {"kind": "presence-bad"},
    "Environment: Air pollutants - methane emissions": {"kind": "presence-bad"},
    "Environment: Land use - forest": {
        "kind": "percent",
        "anchors": [(0.0, 0.2), (20.0, 0.55), (50.0, 0.85), (90.0, 0.95)],
    },
    "Environment: Waste and recycling - municipal solid waste generated annually": {"kind": "presence-bad"},

    "People and Society: Ethnic groups": {"kind": "presence-good"},
    "People and Society: Religions": {"kind": "presence-good"},
    "People and Society: Net migration rate": {
        "kind": "first-number",
        "anchors": [(-15.0, 0.25), (-5.0, 0.5), (0.0, 0.65), (5.0, 0.8), (15.0, 0.7)],
    },
    "People and Society: Total fertility rate": {
        "kind": "first-number",
        "anchors": [(1.2, 0.4), (1.8, 0.7), (2.2, 0.9), (3.5, 0.7), (6.0, 0.35)],
    },

    "Government: National holiday": {"kind": "presence-good"},
    "Government: National anthem": {"kind": "presence-good"},
    "Government: National symbol(s)": {"kind": "presence-good"},
    "Government: Citizenship - citizenship by birth": {"kind": "presence-good"},

    "Government: Legislative branch": {"kind": "presence-good"},
    "Government: Political parties": {"kind": "presence-good"},
    "Communications: Broadcast media": {"kind": "presence-good"},
}


SUFFRAGE_KEYWORDS = ("universal",)
GOV_TYPE_GOOD = (
    "parliamentary republic",
    "federal republic",
    "constitutional monarchy",
    "presidential republic",
    "semi-presidential",
    "parliamentary democracy",
    "federal parliamentary",
)
GOV_TYPE_BAD = (
    "absolute monarchy",
    "communist state",
    "authoritarian",
    "military",
    "in transition",
    "theocratic",
    "one-party",
    "totalitarian",
)
RISK_LEVELS = {
    "very high": 0.15,
    "high": 0.3,
    "intermediate": 0.55,
    "moderate": 0.65,
    "low": 0.85,
    "very low": 0.92,
}


def score_indicator(field: str, value: str | None) -> float | None:
    rule = SCORE_RULES.get(field)
    if rule is None:
        return None
    kind = rule["kind"]
    if value is None:
        return None
    if kind == "presence-good":
        if not isinstance(value, str) or not value.strip():
            return 0.0
        n = len(value)
        if n < 40:
            return 0.55
        if n < 120:
            return 0.65
        if n < 320:
            return 0.75
        if n < 800:
            return 0.85
        return 0.92
    if kind == "presence-bad":
        return rule.get("absent_score", 0.5) if not value else rule.get("present_score", 0.4)
    if kind == "percent":
        v = first_percent(value)
        if v is None:
            v_num = first_number(value)
            v = v_num / 100.0 if v_num is not None and v_num > 1.0 else None
        if v is None:
            return None
        return piecewise(v * 100.0, rule["anchors"])
    if kind == "first-number":
        v = first_number(value)
        if v is None:
            return None
        return piecewise(v, rule["anchors"])
    if kind == "risk-keyword":
        lower = value.lower()
        for k, s in RISK_LEVELS.items():
            if k in lower:
                return s
        return 0.5
    if kind == "suffrage":
        lower = value.lower()
        for k in SUFFRAGE_KEYWORDS:
            if k in lower:
                return 0.85
        return 0.55
    if kind == "gov-type":
        lower = value.lower()
        for k in GOV_TYPE_BAD:
            if k in lower:
                return 0.3
        for k in GOV_TYPE_GOOD:
            if k in lower:
                return 0.8
        return 0.55
    return None


def deterministic_embedding(seed: str, dim: int = 16) -> List[float]:
    h = hashlib.sha256(seed.encode("utf-8")).digest()
    out: List[float] = []
    while len(out) < dim:
        h = hashlib.sha256(h).digest()
        for i in range(0, len(h), 2):
            if len(out) >= dim:
                break
            n = int.from_bytes(h[i : i + 2], "big") / 65535.0
            out.append(round(2.0 * n - 1.0, 5))
    return out


def category_embedding(
    *,
    seed: str,
    composite_score: float | None,
    coverage: float,
    contributions: List[Dict[str, Any]],
    dim: int = 16,
) -> List[float]:
    """Build a category embedding whose first 4 dims carry actual signal:
        [composite_score, coverage, sub_score_1, sub_score_2]
    and whose remaining dims are hash-deterministic so the macro-space has
    enough non-collinear directions to cluster meaningfully.
    """
    head: List[float] = [
        round(composite_score if composite_score is not None else 0.0, 5),
        round(coverage, 5),
    ]
    scored = [c["score"] for c in contributions if c.get("score") is not None]
    head.append(round(scored[0] if len(scored) > 0 else 0.0, 5))
    head.append(round(scored[1] if len(scored) > 1 else 0.0, 5))
    tail = deterministic_embedding(seed, dim - len(head))
    return head + tail


def score_category_dir(cat_dir: Path) -> Dict[str, Any]:
    indicators = json.loads((cat_dir / "indicators.json").read_text())
    contributions: List[Dict[str, Any]] = []
    scored_values: List[float] = []
    for ind in indicators["indicators"]:
        s = score_indicator(ind["field"], ind.get("value"))
        if s is not None:
            scored_values.append(s)
            contributions.append({"field": ind["field"], "score": round(s, 4)})
        else:
            contributions.append({"field": ind["field"], "score": None})
    composite = sum(scored_values) / len(scored_values) if scored_values else None
    embedding = category_embedding(
        seed=f"{indicators['country']}|{indicators['category']}",
        composite_score=composite,
        coverage=indicators["coverage"],
        contributions=contributions,
    )
    return {
        "country": indicators["country"],
        "category": indicators["category"],
        "engine": indicators["engine"],
        "indicator_coverage": indicators["coverage"],
        "indicators_scored": len(scored_values),
        "indicators_total": len(indicators["indicators"]),
        "composite_score": round(composite, 4) if composite is not None else None,
        "score_kind": "scalar_in_unit_interval",
        "contributions": contributions,
        "embedding": embedding,
        "embedding_dim": len(embedding),
        "scored_with": "scripts/10b/scorer.py v0.1.0",
    }


def main() -> int:
    base = BASE / "countries"
    if not base.exists():
        print("registry not generated yet")
        return 1
    only = int(os.environ.get("ONLY_N_COUNTRIES", "0"))
    countries = sorted(base.iterdir())
    if only:
        countries = countries[:only]
    cat_runs = 0
    country_runs = 0
    category_world: Dict[str, List[float]] = {}
    category_country_scores: Dict[str, Dict[str, Any]] = {}
    country_summaries: Dict[str, Dict[str, Any]] = {}

    for country_dir in countries:
        if not country_dir.is_dir():
            continue
        per_cat: Dict[str, Dict[str, Any]] = {}
        for cat_dir in sorted(country_dir.iterdir()):
            if not cat_dir.is_dir() or cat_dir.name == "runs":
                continue
            if not (cat_dir / "indicators.json").exists():
                continue
            out = score_category_dir(cat_dir)
            (cat_dir / "runs").mkdir(parents=True, exist_ok=True)
            (cat_dir / "runs" / "output.json").write_text(
                json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            per_cat[out["category"]] = out
            cat_runs += 1
            category_country_scores.setdefault(out["category"], {})[country_dir.name] = out["composite_score"]
            if out["composite_score"] is not None:
                category_world.setdefault(out["category"], []).append(out["composite_score"])

        # Country rollup
        scores = {c: v["composite_score"] for c, v in per_cat.items()}
        valid = [s for s in scores.values() if s is not None]
        country_score = sum(valid) / len(valid) if valid else None
        cat_embeddings = [v["embedding"] for v in per_cat.values()]
        country_embedding = [round(sum(col) / len(col), 5) for col in zip(*cat_embeddings)]

        # Tier averages
        tier_map = {
            "subsistence": ["food", "water", "shelter", "health", "safety"],
            "development": ["education", "work", "energy", "mobility", "communications"],
            "agency": ["governance", "environment", "belonging", "meaning", "agency"],
        }
        tier_scores = {}
        for tier, cats in tier_map.items():
            ts = [scores[c] for c in cats if scores.get(c) is not None]
            tier_scores[tier] = round(sum(ts) / len(ts), 4) if ts else None

        # Plain-text summary for personal-agent use
        ranked = sorted(
            [(c, s) for c, s in scores.items() if s is not None], key=lambda t: t[1]
        )
        summary_lines = []
        if ranked:
            weakest = ranked[:3]
            strongest = ranked[-3:][::-1]
            summary_lines.append(
                f"For someone in {country_dir.name.replace('-', ' ').title()}, the three needs "
                f"areas with the largest gaps are: "
                + ", ".join(f"{c} ({s:.2f})" for c, s in weakest)
                + "."
            )
            summary_lines.append(
                "The three strongest areas are: "
                + ", ".join(f"{c} ({s:.2f})" for c, s in strongest)
                + "."
            )
            summary_lines.append(
                "Personal-agent suggestions: focus community-building energy on weakest categories; "
                "leverage strongest categories as sources of economic value to bring to the community."
            )
        summary = "\n".join(summary_lines)

        country_run = {
            "country": country_dir.name,
            "category_scores": scores,
            "country_score": round(country_score, 4) if country_score is not None else None,
            "tier_scores": tier_scores,
            "country_embedding": country_embedding,
            "embedding_dim": len(country_embedding),
            "summary": summary,
            "scored_with": "scripts/10b/scorer.py v0.1.0",
        }
        (country_dir / "runs").mkdir(parents=True, exist_ok=True)
        (country_dir / "runs" / "output.json").write_text(
            json.dumps(country_run, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        country_runs += 1
        country_summaries[country_dir.name] = {
            "country_score": country_run["country_score"],
            "tier_scores": tier_scores,
            "embedding": country_embedding,
        }

    # Cross-country category rollups. The category dir is created by
    # generate.py; skip this section gracefully if scorer is run
    # standalone before generate.py has been invoked — the macro-embedding
    # rollup below can still proceed.
    cat_base = BASE / "categories"
    cat_iter = cat_base.iterdir() if cat_base.is_dir() else iter(())
    for cat in cat_iter:
        if not cat.is_dir():
            continue
        scores = category_world.get(cat.name, [])
        if not scores:
            continue
        scores_sorted = sorted(scores)
        n = len(scores_sorted)
        med = scores_sorted[n // 2]
        # Track which countries were dropped vs. scored, so the rollup is
        # transparent about its denominator. Skipped countries are typically
        # uninhabited / military territories (Akrotiri, US Pacific atolls,
        # Antarctica) with no factbook data for the category's indicators.
        scored_set = {c for c, v in (category_country_scores.get(cat.name, {})).items() if v is not None}
        all_set = set(country_summaries.keys())
        skipped = sorted(all_set - scored_set)
        out = {
            "category": cat.name,
            "countries_total": len(all_set),
            "countries_with_data": n,
            "countries_covered": n,  # legacy alias
            "skipped_countries": skipped,
            "coverage_ratio": round(n / max(1, len(all_set)), 4),
            "world_mean": round(sum(scores) / n, 4),
            "world_median": round(med, 4),
            "world_min": round(scores_sorted[0], 4),
            "world_max": round(scores_sorted[-1], 4),
            "world_p10": round(scores_sorted[max(0, n // 10)], 4),
            "world_p90": round(scores_sorted[min(n - 1, (9 * n) // 10)], 4),
            "scored_with": "scripts/10b/scorer.py v0.1.0",
        }
        (cat / "runs").mkdir(parents=True, exist_ok=True)
        (cat / "runs" / "output.json").write_text(
            json.dumps(out, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    # Top-level macro embedding output
    top_dir = BASE
    all_country_embeds = [s["embedding"] for s in country_summaries.values() if s.get("embedding")]
    if all_country_embeds:
        macro = [round(sum(col) / len(col), 5) for col in zip(*all_country_embeds)]
    else:
        macro = []
    valid_country_scores = [s["country_score"] for s in country_summaries.values() if s.get("country_score") is not None]
    macro_out = {
        "country_count": len(country_summaries),
        "category_count": len(category_world),
        "world_mean_country_score": round(sum(valid_country_scores) / len(valid_country_scores), 4)
        if valid_country_scores
        else None,
        "macro_embedding": macro,
        "embedding_dim": len(macro),
        "country_summary_table": [
            {
                "country": c,
                "country_score": v["country_score"],
                "tier_scores": v["tier_scores"],
            }
            for c, v in sorted(country_summaries.items())
        ],
        "scored_with": "scripts/10b/scorer.py v0.1.0",
    }
    (top_dir / "runs").mkdir(parents=True, exist_ok=True)
    (top_dir / "runs" / "macro-embedding.json").write_text(
        json.dumps(macro_out, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(
        f"scored {cat_runs} (country × category) models, {country_runs} country rollups, "
        f"{len(category_world)} category rollups, top-level macro."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
