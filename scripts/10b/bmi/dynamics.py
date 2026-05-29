"""DynamicsBmi — the unsupervised macro-dynamics head.

Consumes the country × category matrix and emits a k-means cluster
assignment per country (grid 1). Output lives in the top-level
`runs/macro-dynamics.json`.
"""

from __future__ import annotations

import numpy as np

from .base import Bmi10BBase
from . import grids as _grids


class DynamicsBmi(Bmi10BBase):
    COMPONENT_NAME = "macro-dynamics (k-means)"

    INPUT_VARS = ("population_needs__satisfaction_score",)
    OUTPUT_VARS = ("population_dynamics__cluster_id",)

    def _grid_for(self, name: str) -> int:
        # One cluster id per country.
        return _grids.COUNTRY_POINTS

    def _compute(self) -> None:
        out = self._read_output(self._run.get("output", "../runs/macro-dynamics.json"))
        assignments = out.get("country_assignments")
        if isinstance(assignments, dict):
            vec = np.full(_grids.country_count(), -1, dtype="int32")
            for slug, cid in assignments.items():
                idx = _grids.country_index(slug)
                if idx is not None and cid is not None:
                    vec[idx] = int(cid)
            self._values["population_dynamics__cluster_id"] = vec
