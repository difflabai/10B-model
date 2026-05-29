"""The 7-grid taxonomy that every 10B BMI node maps its variables onto.

BMI was designed for spatially-discretised models; 10B's "space" is a
(258 country × 15 category) discretisation plus a handful of derived
shapes. We enumerate the grids once here, give each a stable integer id
(the BMI grid id), and let every node declare which grid each of its
variables lives on via `Bmi10BBase._grid_for`.

Grid ids are deliberately stable — downstream consumers and the
`model-registry.json` descriptor reference them by number.

    id  type                  shape       what 10B uses it for
    --  --------------------  ----------  ------------------------------------
    0   scalar                ()          world means, AUC, single scores
    1   points                (258,)      per-country scalars; x/y = centroid
    2   rectilinear           (258, 15)   country × category matrix / tensor
    3   points                (6,)        UN-region centroids
    4   rectilinear           (6, 15)     region × category matrix
    5   unstructured          (k,)        k-means centroids / peer-graph nodes
    6   uniform_rectilinear   (H,)        forecast horizons (time)

The country/region counts are not hard-coded as magic numbers at call
sites: `country_count()` derives 258 from the factbook so the taxonomy
tracks the data if the country universe ever changes.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import sys as _sys

_sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _paths import countries_json_path, country_dot_id  # noqa: E402

# Grid id constants — referenced by name everywhere instead of bare ints.
SCALAR = 0
COUNTRY_POINTS = 1
COUNTRY_CATEGORY = 2
REGION_POINTS = 3
REGION_CATEGORY = 4
UNSTRUCTURED = 5
TIME = 6

# The 15 needs categories are fixed by the needs tree; the regions are the
# six UN-geoscheme buckets the pipeline uses. Both are small, closed sets.
N_CATEGORIES = 15
N_REGIONS = 6

# Aggregate factbook entries that are not real countries (mirrors the set
# generate.py drops) — excluded from the country grid so grid 1 size lines
# up with the materialised `countries/` tree.
AGGREGATE_ENTRIES = {"World", "European Union"}


@dataclass(frozen=True)
class GridDescriptor:
    """Static description of one BMI grid. `shape` is None for grids whose
    extent is data-derived (country/region counts, cluster k, horizon H);
    those resolve through the helpers below at runtime.
    """

    gid: int
    grid_type: str
    rank: int
    shape: Optional[Tuple[int, ...]] = None
    has_xy: bool = False  # exposes get_grid_x / get_grid_y (point grids)
    has_edges: bool = False  # exposes get_grid_edge_* (peer graph)


GRIDS: Dict[int, GridDescriptor] = {
    SCALAR: GridDescriptor(SCALAR, "scalar", 0, shape=()),
    COUNTRY_POINTS: GridDescriptor(COUNTRY_POINTS, "points", 1, has_xy=True),
    COUNTRY_CATEGORY: GridDescriptor(COUNTRY_CATEGORY, "rectilinear", 2),
    REGION_POINTS: GridDescriptor(REGION_POINTS, "points", 1, shape=(N_REGIONS,), has_xy=True),
    REGION_CATEGORY: GridDescriptor(
        REGION_CATEGORY, "rectilinear", 2, shape=(N_REGIONS, N_CATEGORIES)
    ),
    UNSTRUCTURED: GridDescriptor(UNSTRUCTURED, "unstructured", 1, has_edges=True),
    TIME: GridDescriptor(TIME, "uniform_rectilinear", 1),
}


@lru_cache(maxsize=1)
def _countries() -> Dict[str, dict]:
    path = countries_json_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


@lru_cache(maxsize=1)
def country_slugs() -> Tuple[str, ...]:
    """Ordered tuple of country slugs that make up grid 1 / grid 2's first
    axis. Order is the factbook key order minus the aggregate entries —
    identical to the order generate.py materialises `countries/` in.

    Falls back to walking the materialised `countries/` tree when the
    factbook dump is absent (the common case for a read-only checkout), so
    introspection still works without countries.json.
    """
    countries = _countries()
    if countries:
        names = [n for n in countries.keys() if n not in AGGREGATE_ENTRIES]
        return tuple(country_dot_id(n) for n in names)
    # Fallback: derive from the materialised registry.
    from _paths import tenb_root  # local import to avoid cycles at module load

    cdir = tenb_root() / "countries"
    if cdir.is_dir():
        return tuple(sorted(p.name for p in cdir.iterdir() if p.is_dir()))
    return ()


def country_count() -> int:
    return len(country_slugs())


@lru_cache(maxsize=1)
def _country_index() -> Dict[str, int]:
    return {slug: i for i, slug in enumerate(country_slugs())}


def country_index(slug: str) -> Optional[int]:
    """Row index of a country on grid 1 / grid 2, or None if unknown."""
    return _country_index().get(slug)


def country_xy(slug: str) -> Tuple[float, float]:
    """(longitude, latitude) centroid for a country, or (nan, nan) when the
    factbook has no usable geographic coordinates. BMI tolerates NaN node
    coordinates, so a missing centroid never breaks grid introspection.
    """
    countries = _countries()
    # Reverse the slug→name mapping lazily; factbook keys are human names.
    for name, data in countries.items():
        if name in AGGREGATE_ENTRIES:
            continue
        if country_dot_id(name) == slug:
            return _parse_geo_coords(data)
    return (math.nan, math.nan)


def _parse_geo_coords(country: dict) -> Tuple[float, float]:
    """Pull (lon, lat) out of the factbook 'Geographic coordinates' field.

    The factbook stores e.g. "20 00 N, 77 00 E"; we decode to signed
    decimal degrees. Returns (nan, nan) on any parse failure rather than
    raising — coordinates are advisory metadata on the country point grid.
    """
    geo = country.get("Geography", {})
    if not isinstance(geo, dict):
        return (math.nan, math.nan)
    raw = geo.get("Geographic coordinates")
    text = None
    if isinstance(raw, dict):
        text = raw.get("text")
    elif isinstance(raw, str):
        text = raw
    if not text:
        return (math.nan, math.nan)
    try:
        lat_part, lon_part = [p.strip() for p in text.split(",")[:2]]
        lat = _dms_to_decimal(lat_part)
        lon = _dms_to_decimal(lon_part)
        return (lon, lat)
    except Exception:
        return (math.nan, math.nan)


def _dms_to_decimal(part: str) -> float:
    toks = part.split()
    deg = float(toks[0])
    minutes = float(toks[1]) if len(toks) > 2 else 0.0
    hemi = toks[-1].upper()
    val = deg + minutes / 60.0
    if hemi in ("S", "W"):
        val = -val
    return val


def grid_size(gid: int, *, k: Optional[int] = None, horizon: Optional[int] = None) -> int:
    """Number of elements on a grid. `k` (cluster count) and `horizon`
    (number of forecast steps) parameterise the data-derived grids.
    """
    desc = GRIDS[gid]
    if gid == SCALAR:
        return 1
    if gid == COUNTRY_POINTS:
        return country_count()
    if gid == COUNTRY_CATEGORY:
        return country_count() * N_CATEGORIES
    if gid == REGION_POINTS:
        return N_REGIONS
    if gid == REGION_CATEGORY:
        return N_REGIONS * N_CATEGORIES
    if gid == UNSTRUCTURED:
        return int(k) if k is not None else 0
    if gid == TIME:
        return int(horizon) if horizon is not None else 0
    if desc.shape is not None:
        n = 1
        for d in desc.shape:
            n *= d
        return n
    return 0


def grid_shape(gid: int, *, k: Optional[int] = None, horizon: Optional[int] = None) -> Tuple[int, ...]:
    if gid == SCALAR:
        return ()
    if gid == COUNTRY_POINTS:
        return (country_count(),)
    if gid == COUNTRY_CATEGORY:
        return (country_count(), N_CATEGORIES)
    if gid == REGION_POINTS:
        return (N_REGIONS,)
    if gid == REGION_CATEGORY:
        return (N_REGIONS, N_CATEGORIES)
    if gid == UNSTRUCTURED:
        return (int(k),) if k is not None else (0,)
    if gid == TIME:
        return (int(horizon),) if horizon is not None else (0,)
    return GRIDS[gid].shape or ()
