"""SupervisedBmi — the supervised hold-out trajectory head.

Trains a quintile classifier on the macro embedding and reports hold-out
AUC across the sociodemographic targets. The headline output is a single
AUC scalar; output lives in the top-level `runs/supervised-auc.json`.
"""

from __future__ import annotations

import numpy as np

from .base import Bmi10BBase
from . import grids as _grids


class SupervisedBmi(Bmi10BBase):
    COMPONENT_NAME = "supervised hold-out trajectory"

    INPUT_VARS = ("population_needs__satisfaction_score",)
    OUTPUT_VARS = ("population_supervised__holdout_auc",)

    def _grid_for(self, name: str) -> int:
        return _grids.SCALAR

    def _compute(self) -> None:
        out = self._read_output(self._run.get("output", "../runs/supervised-auc.json"))
        auc = out.get("mean_auc")
        if auc is None:
            auc = out.get("holdout_auc")
        if auc is not None:
            self._values["population_supervised__holdout_auc"] = np.array(
                [float(auc)], dtype="float64"
            )
