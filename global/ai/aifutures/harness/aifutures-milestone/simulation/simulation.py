#!/usr/bin/env python3
"""Monte Carlo engine for the AI Futures Model (Lifland, Halstead,
Kastner, Kokotajlo et al., December 2025).

Reads a JSON spec on stdin, writes a JSON prediction + manifest on stdout.

This is a content-hashed harness asset. To change behaviour, submit a new
version through the harness editor + structural validator + promoter.

Spec shape:
    {
      "scenario": "eli" | "daniel" | "alex" | "brendan",
      "milestone": "ac" | "sar" | "siar" | "ted_ai" | "asi",
      "parameters": {
        "present_year": float,            # e.g. 2026.33
        "metr_hrs_doubling_months": float,
        "ac_threshold_doublings": float,
        "rd_uplift_pre_ac": float,
        "rd_uplift_post_ac": float,
        "b": float,                       # ratio of successive uplift doublings
        "compute_growth_rate": float,
        "taste_only_singularity": bool
      },
      "num_samples": int,
      "seed": int
    }

Output shape:
    {
      "prediction": {
        "kind": "numeric",
        "mean": float,
        "intervals": {
          "50": [float, float],
          "80": [float, float],
          "90": [float, float]
        }
      },
      "manifest": {
        "seed": int,
        "num_samples": int,
        "scenario": str,
        "milestone": str,
        "parameters_used": {...},
        "samples_summary": {"mean": float, "stddev": float}
      }
    }
"""

from __future__ import annotations

import json
import math
import random
import statistics
import sys


MILESTONE_DOUBLING_GAPS = {
    # How many capability doublings beyond the AC threshold each milestone needs.
    # Calibrated to the source model's Stage 2 / Stage 3 dynamics.
    "ac": 0.0,
    "sar": 4.0,
    "siar": 6.0,
    "ted_ai": 7.5,
    "asi": 9.0,
}


SCENARIO_POSTURE = {
    # Fractional widening applied to the simulated samples around their mean.
    # `eli` widens; `daniel` slightly widens; `alex`/`brendan` are model-anchored.
    "eli": 0.20,
    "daniel": 0.10,
    "alex": 0.0,
    "brendan": 0.0,
}


def _quantile(s: list[float], q: float) -> float:
    """Linear-interpolated quantile of a *pre-sorted* list.

    Caller must sort `s` once before calling. We do not sort inside this
    function because it is called several times per simulation and sorting
    10k-sample lists 6× per run is meaningful overhead.
    """
    if not s:
        return float("nan")
    if q <= 0:
        return s[0]
    if q >= 1:
        return s[-1]
    pos = q * (len(s) - 1)
    low = int(math.floor(pos))
    high = int(math.ceil(pos))
    if low == high:
        return s[low]
    frac = pos - low
    return s[low] * (1 - frac) + s[high] * frac


def simulate(spec: dict) -> dict:
    scenario = spec["scenario"]
    milestone = spec["milestone"]
    p = spec["parameters"]
    n = int(spec.get("num_samples", 10_000))
    seed = int(spec.get("seed", 0))

    rng = random.Random(seed)

    present_year = float(p["present_year"])
    metr_hrs_doubling_months = float(p["metr_hrs_doubling_months"])
    ac_threshold_doublings = float(p["ac_threshold_doublings"])
    rd_uplift_pre_ac = float(p["rd_uplift_pre_ac"])
    rd_uplift_post_ac = float(p["rd_uplift_post_ac"])
    b = float(p["b"])
    compute_growth_rate = float(p.get("compute_growth_rate", 0.4))
    taste_only_singularity = bool(p.get("taste_only_singularity", True))

    # Pre-AC time: extrapolate METR-HRS doubling time scaled by R&D uplift.
    # months_per_doubling_pre_ac = doubling_months / rd_uplift_pre_ac
    pre_ac_months_per_doubling = metr_hrs_doubling_months / max(rd_uplift_pre_ac, 0.1)
    months_to_ac_mean = pre_ac_months_per_doubling * ac_threshold_doublings

    # Add a small log-normal scatter to capture parameter uncertainty.
    scatter_mean_log = 0.0
    scatter_sigma = 0.25  # ~25% lognormal scatter

    # Post-AC: takeoff dynamics. Each doubling beyond AC takes b * (prior doubling).
    # If taste-only-singularity is true and b<1, doublings shrink geometrically.
    extra_doublings = MILESTONE_DOUBLING_GAPS[milestone]

    samples_years: list[float] = []
    for _ in range(n):
        scatter = math.exp(rng.gauss(scatter_mean_log, scatter_sigma))
        ac_months = months_to_ac_mean * scatter
        if extra_doublings == 0:
            total_months = ac_months
        else:
            # Post-AC base doubling time scaled by post-AC R&D uplift.
            base_post = pre_ac_months_per_doubling / max(rd_uplift_post_ac / max(rd_uplift_pre_ac, 0.1), 0.1)
            post_months = 0.0
            current = base_post
            doublings_left = extra_doublings
            while doublings_left > 0:
                step = min(1.0, doublings_left)
                post_months += current * step
                # Apply b for next doubling (taste-only-singularity gate).
                if taste_only_singularity:
                    current *= b
                doublings_left -= step
            # Compute also slows or speeds things slightly.
            post_months *= math.pow(1.0 - 0.05 * compute_growth_rate, max(0.0, extra_doublings))
            total_months = ac_months + post_months

        years_offset = total_months / 12.0
        samples_years.append(present_year + years_offset)

    # Apply scenario posture: stretch samples around their median.
    posture = SCENARIO_POSTURE.get(scenario, 0.0)
    if posture > 0.0:
        med = statistics.median(samples_years)
        samples_years = [med + (x - med) * (1.0 + posture) for x in samples_years]

    mean_year = statistics.mean(samples_years)
    stddev_year = statistics.pstdev(samples_years) if len(samples_years) > 1 else 0.0

    samples_years.sort()
    intervals = {
        "50": [_quantile(samples_years, 0.25), _quantile(samples_years, 0.75)],
        "80": [_quantile(samples_years, 0.10), _quantile(samples_years, 0.90)],
        "90": [_quantile(samples_years, 0.05), _quantile(samples_years, 0.95)],
    }

    return {
        "prediction": {
            "kind": "numeric",
            "mean": round(mean_year, 4),
            "intervals": {
                k: [round(lo, 4), round(hi, 4)] for k, (lo, hi) in intervals.items()
            },
        },
        "manifest": {
            "seed": seed,
            "num_samples": n,
            "scenario": scenario,
            "milestone": milestone,
            "parameters_used": p,
            "samples_summary": {
                "mean": round(mean_year, 4),
                "stddev": round(stddev_year, 4),
            },
        },
    }


def main() -> int:
    spec = json.load(sys.stdin)
    out = simulate(spec)
    json.dump(out, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
