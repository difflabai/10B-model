"""Shared path resolution + naming helpers for the 10B pipeline scripts.

The pipeline writes into the same repo it lives in — this is the
`difflabai/10B-model` repo. Output lands at `<repo>/global/10B/` by
default. Override with one of the BWM environment variables if you
want the pipeline to populate a different writable registry tree:

  - $BWM_10B_ROOT — if set, points at *this repo's* checkout root
    (the directory that contains `global/10B/`). Use this when you've
    cloned the repo somewhere other than the script's parent — e.g.
    a Conductor workspace.
  - $BWM_LOCAL_ROOT — writable local registry root used by the
    `business-world-models` admin server. If set, the scripts write to
    `$BWM_LOCAL_ROOT/global/10B/` so a re-run hot-replaces the local
    fork without needing another `import` round-trip.

Default fallback order (first match wins):
  1. $BWM_10B_ROOT
  2. $BWM_LOCAL_ROOT
  3. <repo-root>/ (the directory two levels above this file)

The naming helpers (`slugify`, `country_dot_id`) live here because
country slugs are part of every output path — every script that
writes a country file needs them in lock-step with `tenb_root()`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def registry_root() -> Path:
    """Return the directory whose direct children are namespace
    prefixes like `global/`. Write targets resolve here first; readers
    do the same so the pipeline is round-trippable.
    """
    for env_var in ("BWM_10B_ROOT", "BWM_LOCAL_ROOT"):
        env = os.environ.get(env_var)
        if env:
            return Path(env).resolve()
    return REPO_ROOT


def tenb_root() -> Path:
    """The `global/10B/` directory inside the resolved registry root —
    where every model.meta.json / model.run.json this pipeline
    generates lives.
    """
    return registry_root() / "global" / "10B"


def countries_json_path() -> Path:
    """Where the CIA Factbook countries dump lives. Several pipeline
    steps depend on this (country list, region classification, forecast
    seeding). Override with $COUNTRIES_JSON; defaults to
    `<repo-root>/countries.json`. The file is not committed — see the
    README for how to obtain it.
    """
    env = os.environ.get("COUNTRIES_JSON")
    if env:
        return Path(env).resolve()
    return REPO_ROOT / "countries.json"


def require_countries_json() -> Path:
    """Same as `countries_json_path` but raises a friendly SystemExit
    when the file is missing — used by the entry-point scripts so the
    user gets a one-line diagnostic instead of a Python traceback.
    """
    path = countries_json_path()
    if not path.exists():
        raise SystemExit(
            f"countries.json not found at {path}. "
            "Drop a CIA Factbook countries dump at this path (or set "
            "$COUNTRIES_JSON to point at one) before running the pipeline. "
            "See README.md for details."
        )
    return path


_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """Lowercase, ASCII-only, hyphen-separated slug. Used for every
    directory name under `countries/`, region buckets, and category
    rollups — keeping it in one place is what guarantees the slug a
    write produces matches the slug a downstream read looks up.

    Empty input maps to `"unknown"` so a typo doesn't silently produce
    an empty path segment.
    """
    s = _SLUG_NON_ALNUM.sub("-", name.lower().strip()).strip("-")
    return s or "unknown"


def country_dot_id(name: str) -> str:
    """Slug used as the trailing dot-segment of a country model id —
    e.g. `India` → `india` for `global.10B.countries.india`. Equal to
    `slugify` today; kept as its own name so call sites that mean
    "country dot-id specifically" are searchable.
    """
    return slugify(name)
