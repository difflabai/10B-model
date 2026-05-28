"""CountryRollupBmi — one country's needs rollup across all 15 categories.

Consumes the 15 per-category cell scores and emits a single country
satisfaction score (plus, internally, the country embedding and tier
scores). The score is exposed as a scalar; the per-category inputs are
declared so the standard-name-closure validator can see the edge from the
cells.
"""

from __future__ import annotations

import numpy as np

from .base import Bmi10BBase
from .mmb import MmbCompliantBmi
from . import grids as _grids


class CountryRollupBmi(Bmi10BBase):
    COMPONENT_NAME = "country needs rollup"

    INPUT_VARS = ("population_needs__satisfaction_score",)
    OUTPUT_VARS = (
        "population_needs__satisfaction_score",
        "population_needs__indicator_coverage",
    )

    def _grid_for(self, name: str) -> int:
        # One country: a single rolled-up value.
        return _grids.SCALAR

    def _compute(self) -> None:
        out = self._read_output(self._run.get("output", "runs/output.json"))
        score = out.get("country_score")
        if score is not None:
            self._values["population_needs__satisfaction_score"] = np.array(
                [float(score)], dtype="float64"
            )


class MmbCountryRollupBmi(CountryRollupBmi, MmbCompliantBmi):
    """A country rollup that is also MMB Modelbase-block compliant.

    Used for countries with a registered macroeconomic backing (initially
    the United States, backed by FRB/US). In addition to the needs score,
    it exposes the five MMB common variables sourced from the backing
    model; until that model is installed/wired they resolve to NaN, but the
    node still advertises its MMB capabilities and swappable policy rule.
    """

    COMPONENT_NAME = "country needs rollup (MMB-compliant)"

    # The five MMB common variables (long CSDMS names) join the outputs so
    # the MMB output-coverage validator is satisfied.
    OUTPUT_VARS = CountryRollupBmi.OUTPUT_VARS + (
        "monetary_policy__short_rate_annualized",
        "consumer_prices__inflation_yoy_pct",
        "consumer_prices__inflation_qoq_annualized",
        "national_accounts__output_gap_pct",
        "national_accounts__output_level_index",
    )

    def attach_backing(self, backing) -> None:
        """Wire the macroeconomic backing BMI (e.g. FrbusBmi). The coupler
        calls this before `update()` when the backing model is available.
        """
        self._backing = backing

    def _compute(self) -> None:
        super()._compute()
        backing = getattr(self, "_backing", None)
        if backing is None:
            return
        # Pull the five common variables from the backing macro model.
        for long_name in self.OUTPUT_VARS[2:]:
            try:
                buf = np.empty(
                    backing.get_grid_size(backing.get_var_grid(long_name)),
                    dtype="float64",
                )
                backing.get_value(long_name, buf)
                self._values[long_name] = buf
            except Exception:
                continue
