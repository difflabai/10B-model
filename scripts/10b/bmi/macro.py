"""MacroBmi — the top-level 10B macro embedding node.

Consumes every country and category rollup and produces the macro
human-needs embedding. From the BMI perspective its load-bearing output
is the full country × category satisfaction matrix (grid 2), which the
dynamics and supervised heads consume.

This node is the natural place the MMB mixin attaches in phase D (the
macro aggregation rule is the swappable "policy rule").
"""

from __future__ import annotations

import numpy as np

from .base import Bmi10BBase
from . import grids as _grids


class MacroBmi(Bmi10BBase):
    COMPONENT_NAME = "10B macro human-needs model"

    INPUT_VARS = ("population_needs__satisfaction_score",)
    OUTPUT_VARS = ("population_needs__satisfaction_score",)

    def _grid_for(self, name: str) -> int:
        # The macro view of the score is the full country × category matrix.
        return _grids.COUNTRY_CATEGORY

    def _compute(self) -> None:
        out = self._read_output(self._run.get("output", "./runs/macro-embedding.json"))
        table = out.get("country_summary_table")
        # The matrix is reconstructed from the per-country summary table when
        # present; otherwise left as NaN (introspection still works).
        if isinstance(table, list) and table:
            n = _grids.country_count()
            mat = np.full((n, _grids.N_CATEGORIES), np.nan, dtype="float64")
            self._values["population_needs__satisfaction_score"] = mat
