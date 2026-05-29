"""CategoryWorldBmi — one category's world rollup across all countries.

Consumes the per-country cell scores for a single category and emits the
population-weighted world-mean satisfaction for that category (a scalar),
alongside distribution statistics. The materialised rollup stores the
world aggregates rather than a per-country vector, so the BMI-visible
output is the scalar world mean; the per-country detail lives in the cells
and country rollups. (Exposing a per-country category vector here is a
future enhancement once the scorer emits one.)
"""

from __future__ import annotations

import numpy as np

from .base import Bmi10BBase
from . import grids as _grids


class CategoryWorldBmi(Bmi10BBase):
    COMPONENT_NAME = "category world rollup"

    INPUT_VARS = ("population_needs__satisfaction_score",)
    OUTPUT_VARS = ("population_needs__satisfaction_score",)

    def _grid_for(self, name: str) -> int:
        # The materialised output is the world-mean scalar for this category.
        return _grids.SCALAR

    def _compute(self) -> None:
        out = self._read_output(self._run.get("output", "runs/output.json"))
        world_mean = out.get("world_mean")
        if world_mean is not None:
            self._values["population_needs__satisfaction_score"] = np.array(
                [float(world_mean)], dtype="float64"
            )
