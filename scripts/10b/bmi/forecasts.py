"""ForecastBmi — a forecast node on the time grid.

Forecasts are the one genuinely temporal part of 10B. A forecast node
advertises its expected (and, once resolved, resolved) score on the time
grid, with `update_until(t)` rolling the horizon forward.

Note: in the current registry forecasts are materialised as standalone
`forecasts/*.json` ForecastMeta files, not as `model.run.json` nodes, so
nothing in the 4,228-node tree maps here yet. This class is the BMI
surface that phase D's macro-resolution forecast nodes (which gain
`model.run.json` + `mmb` blocks) will use.
"""

from __future__ import annotations

import numpy as np

from .base import Bmi10BBase
from . import grids as _grids


class ForecastBmi(Bmi10BBase):
    COMPONENT_NAME = "forecast node"

    # Temporal: a quarter-month cadence to a resolution date.
    _STEADY_STATE = False
    _TIME_STEP_SECONDS = 2.628e6  # ~one month

    INPUT_VARS = ()
    OUTPUT_VARS = (
        "population_forecast__expected_score",
        "population_forecast__resolved_score",
    )

    def _grid_for(self, name: str) -> int:
        return _grids.TIME

    def _horizon(self) -> int:
        # One point per monthly step over the (default) horizon. Overridden
        # per-forecast once horizons are wired in phase D.
        return 1

    def _compute(self) -> None:
        out = self._read_output(self._run.get("output", "runs/output.json"))
        pred = out.get("current_prediction")
        if pred is not None:
            self._values["population_forecast__expected_score"] = np.array(
                [float(pred)], dtype="float64"
            )
