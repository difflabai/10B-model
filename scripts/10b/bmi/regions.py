"""RegionRollupBmi — UN-geoscheme regional rollups.

Covers both the 6 region rollups (`global.10B.regions.africa`) and the
90 region×category cells (`global.10B.regions.africa.food`). A region
rollup exposes a single regional satisfaction score; a region×category
cell exposes its single score. Both are scalars from the node's own
perspective.
"""

from __future__ import annotations

import numpy as np

from .base import Bmi10BBase
from . import grids as _grids


class RegionRollupBmi(Bmi10BBase):
    COMPONENT_NAME = "regional needs rollup"

    INPUT_VARS = ("population_needs__satisfaction_score",)
    OUTPUT_VARS = ("population_needs__satisfaction_score",)

    def _grid_for(self, name: str) -> int:
        return _grids.SCALAR

    def _compute(self) -> None:
        out = self._read_output(self._run.get("output", "runs/output.json"))
        # Region rollup uses "region_score"; region×category cell stores its
        # aggregate as "mean" (and may also carry "composite_score").
        score = out.get("region_score")
        if score is None:
            score = out.get("mean")
        if score is None:
            score = out.get("composite_score")
        if score is not None:
            self._values["population_needs__satisfaction_score"] = np.array(
                [float(score)], dtype="float64"
            )
