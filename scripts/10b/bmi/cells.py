"""CellBmi — one (country × category) satisfaction cell.

The 3,855 leaf nodes of the registry. Each scores one category of human
need for one country into a [0,1] satisfaction value. In the no-op phase
`_compute` reads the materialised `runs/output.json`; the score is the
BMI-visible output that flows up into the country and category rollups.
"""

from __future__ import annotations

import numpy as np

from .base import Bmi10BBase
from . import grids as _grids


class CellBmi(Bmi10BBase):
    COMPONENT_NAME = "country × category needs cell"

    # A cell consumes a factbook indicator slice (not a population_* var) so
    # it declares no standard-named inputs in the no-op phase. The US macro
    # cells add FRB/US-backed inputs in phase E.
    INPUT_VARS = ()
    OUTPUT_VARS = (
        "population_needs__satisfaction_score",
        "population_needs__indicator_coverage",
    )

    def _grid_for(self, name: str) -> int:
        # A single cell holds single values.
        return _grids.SCALAR

    def attach_backing(self, backing) -> None:
        """Wire a macroeconomic backing (FRB/US) into a US macro cell. The
        coupler calls this when the backing is available; absent it, the
        cell scores from the factbook alone (the committed behaviour).
        """
        self._backing = backing

    def _compute(self) -> None:
        out = self._read_output(self._run.get("output", "runs/output.json"))
        score = out.get("composite_score")
        coverage = out.get("indicator_coverage")
        if coverage is not None:
            self._values["population_needs__indicator_coverage"] = np.array(
                [float(coverage)], dtype="float64"
            )
        if score is None:
            return
        score = float(score)

        backing = getattr(self, "_backing", None)
        if backing is not None:
            score = self._blend_with_backing(score, backing)
        self._values["population_needs__satisfaction_score"] = np.array(
            [score], dtype="float64"
        )

    def _blend_with_backing(self, factbook_score: float, backing) -> float:
        """Blend the factbook score with an FRB/US-derived macro proxy.

        Only reached when a backing is attached (FRB/US installed + wired by
        the coupler). The blend weight comes from the run config
        (`inputs.frbus_blend_weight`, default 0.5). The proxy maps the
        output gap to a [0,1] contribution; this is illustrative and the
        real calibration is future work.
        """
        weight = 0.5
        try:
            weight = float(
                (self._run.get("inputs", {}).get("frbus_blend_weight", {}) or {})
                .get("value", 0.5)
            )
        except Exception:
            weight = 0.5
        try:
            buf = np.empty(
                backing.get_grid_size(
                    backing.get_var_grid("national_accounts__output_gap_pct")
                ),
                dtype="float64",
            )
            backing.get_value("national_accounts__output_gap_pct", buf)
            gap = float(buf[0])
            # Map output gap (percent) to a bounded [0,1] proxy around 0.5.
            proxy = max(0.0, min(1.0, 0.5 + gap / 20.0))
        except Exception:
            return factbook_score
        return (1.0 - weight) * factbook_score + weight * proxy
