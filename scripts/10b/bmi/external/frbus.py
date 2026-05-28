"""FrbusBmi — a BMI + MMB wrapper around the Federal Reserve's FRB/US model.

FRB/US is a ~380-equation quarterly macroeconometric model of the US
economy, distributed by the Federal Reserve Board as a Python package
(`pyfrbus`). 10B does not bundle it: `pyfrbus` is installed locally by the
user and imported lazily inside `initialize()`. Every other part of the
pipeline — including importing this class and introspecting its BMI
surface — works without `pyfrbus` present.

The node sits at model id `external.federalreserve.frbus`. The five US
macro cells (`work`, `mobility`, `communications`, `governance`, `energy`)
and the MMB-compliant US country rollup consume it.

Mapping (per `.context/bmi-10b-architecture.md` §13): the whole FRB/US
model is a single point; current-quarter values sit on the scalar grid.
Outputs expose the five MMB common variables (sourced from FRB/US's native
`rff` / `pic4` / `picxfe` / `xgap2` / `xgdp`) plus key labour/spending
series; inputs expose the policy/fiscal/demand residuals (`*_aerr`) — the
bottom-up entry point — and exogenous overlays.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np

from ..base import Bmi10BBase, BmiDependencyMissing
from ..mmb import MmbCompliantBmi
from .. import grids as _grids


def _optional_import_pyfrbus():
    """Import pyfrbus or raise BmiDependencyMissing with an install hint."""
    try:
        from pyfrbus.frbus import Frbus  # type: ignore
        from pyfrbus.load_data import load_data  # type: ignore

        return Frbus, load_data
    except Exception as e:  # noqa: BLE001
        raise BmiDependencyMissing(
            "FrbusBmi requires pyfrbus, which 10B does not bundle. Download "
            "the FRB/US Python package from "
            "https://www.federalreserve.gov/econres/us-models-package.htm into "
            "<repo>/pyfrbus/ (data at <repo>/pyfrbus/data/), put it on "
            "PYTHONPATH, or set $BWM_FRBUS_PCIM to the model file."
        ) from e


class FrbusBmi(Bmi10BBase, MmbCompliantBmi):
    COMPONENT_NAME = "FRB/US (Federal Reserve)"

    # Output standard name -> (native FRB/US column, transform). The five
    # MMB common variables come first; transform is applied to the raw
    # native value (identity when None).
    OUTPUT_NATIVE: Dict[str, Tuple[str, Optional[str]]] = {
        "monetary_policy__short_rate_annualized": ("rff", None),
        "consumer_prices__inflation_yoy_pct": ("pic4", None),
        "consumer_prices__inflation_qoq_annualized": ("picxfe", None),
        "national_accounts__output_gap_pct": ("xgap2", None),
        "national_accounts__output_level_index": ("xgdp", None),
        "labour_market__unemployment_rate_pct": ("lur", None),
        "labour_market__nairu_pct": ("lurnat", None),
        "national_accounts__consumption_index": ("ec", None),
        "fiscal_policy__federal_spending_index": ("egfo", None),
    }

    INPUT_NATIVE: Dict[str, str] = {
        "monetary_policy__rule_shock": "rffintay_aerr",
        "fiscal_policy__discretionary_shock": "egfo_aerr",
        "aggregate_demand__shock": "ec_aerr",
        "foreign_sector__world_gdp": "fgdp",
        "commodity_markets__crude_oil_price": "poilr",
    }

    OUTPUT_VARS = tuple(OUTPUT_NATIVE.keys())
    INPUT_VARS = tuple(INPUT_NATIVE.keys())

    # FRB/US policy-rule modes (DataFrame switch columns), keyed by the MMB
    # capability id we expose them under.
    RULE_COLUMNS = {
        "TAYLOR_INERTIAL": "dmpintay",
        "TAYLOR_LWW": "dmptay",
        "TAYLOR_INTERCEPT": "dmptlr",
        "MC_TAYLOR_INERTIAL": "dmpintay",  # with the MCE model variant
    }
    ALL_RULE_COLUMNS = ("dmpintay", "dmptay", "dmptlr", "dmpalt", "dmpgen",
                        "dmpex", "dmprr")

    _TIME_STEP_SECONDS = 7.884e6  # one quarter

    def __init__(self) -> None:
        super().__init__()
        self._frbus = None
        self._baseline = None  # add-factored baseline frame (immutable)
        self._data = None      # most recent solved frame
        self._start = None
        self._end = None
        self._report_period = None

    # ------------------------------------------------------------------ #
    def _grid_for(self, name: str) -> int:
        # Single point (the US economy); current-quarter scalars.
        return _grids.SCALAR

    def _resolve_paths(self):
        """Resolve (model_xml, data_file). Looks at spec/env first, then the
        conventional vendored layout `<root>/pyfrbus/{models/model.xml,
        data/LONGBASE.TXT}`.
        """
        from _paths import registry_root

        spec = (self._run.get("spec", {}) or {}).get("inline", {})
        root = registry_root()
        model_cands = [
            spec.get("frbus_model_xml"),
            os.environ.get("BWM_FRBUS_PCIM"),
            str(root / "pyfrbus" / "models" / "model.xml"),
            str(root / "pyfrbus" / "data" / "model.xml"),
        ]
        data_cands = [
            spec.get("frbus_data"),
            os.environ.get("BWM_FRBUS_DATA"),
            str(root / "pyfrbus" / "data" / "LONGBASE.TXT"),
        ]
        model_path = next((Path(c) for c in model_cands if c and Path(c).exists()), None)
        data_path = next((Path(c) for c in data_cands if c and Path(c).exists()), None)
        if model_path is None or data_path is None:
            raise BmiDependencyMissing(
                "FRB/US model/data not found. Set $BWM_FRBUS_PCIM and "
                "$BWM_FRBUS_DATA, or place pyfrbus at <repo>/pyfrbus/."
            )
        return model_path, data_path

    def initialize(self, config_file: str) -> None:
        super().initialize(config_file)
        Frbus, load_data = _optional_import_pyfrbus()  # raises if absent
        import pandas as pd

        model_path, data_path = self._resolve_paths()
        spec = (self._run.get("spec", {}) or {}).get("inline", {})
        # Expectations: VAR (backward-looking, default) or MC (model-
        # consistent). MC loads the MCE equation set; `mce_type` selects the
        # FRB/US MCE configuration (all / mcap / wp / mcap+wp).
        expectations = str(spec.get("expectations", "VAR")).upper()
        mce = spec.get("mce_type", "mcap+wp") if expectations == "MC" else None
        self._frbus = Frbus(str(model_path), mce=mce)
        raw = load_data(str(data_path))

        # Horizon: a forecast window inside the LONGBASE extension.
        start_str = spec.get("start", "2040Q1")
        horizon = int(spec.get("horizon_quarters", 40))
        self._start = pd.Period(start_str, freq="Q")
        self._end = self._start + (horizon - 1)

        # Standard fiscal configuration (surplus-ratio targeting), per the
        # FRB/US demos, then compute tracking residuals so the baseline
        # solves to itself. `_baseline` is the immutable add-factored frame;
        # each update() solves a fresh copy with staged shocks applied.
        raw.loc[self._start:self._end, "dfpdbt"] = 0
        raw.loc[self._start:self._end, "dfpsrp"] = 1
        self._baseline = self._frbus.init_trac(self._start, self._end, raw)
        self._data = None
        self._report_period = self._end  # period reported via get_value

    def update(self) -> None:
        self._require_init()
        if self._frbus is None or self._baseline is None:
            raise BmiDependencyMissing("FrbusBmi not initialized with pyfrbus")
        frame = self._baseline.copy()
        self._apply_rule(frame)
        self._apply_shocks(frame)
        self._data = self._frbus.solve(self._start, self._end, frame)
        self._populate_from_data()

    def update_until(self, time: float) -> None:
        self.update()
        self._current_time = time

    def _apply_shocks(self, frame) -> None:
        """Translate staged BMI inputs (set_value) into FRB/US DataFrame
        edits at the impact period. Residual/shock inputs are additive
        add-factors; exogenous inputs are level overrides over the horizon.
        """
        additive = {
            "monetary_policy__rule_shock": "rffintay_aerr",
            "fiscal_policy__discretionary_shock": "egfo_aerr",
            "aggregate_demand__shock": "ec_aerr",
        }
        overrides = {
            "foreign_sector__world_gdp": "fgdp",
            "commodity_markets__crude_oil_price": "poilr",
        }
        for long_name, native in additive.items():
            if long_name in self._values and native in frame.columns:
                frame.loc[self._start, native] += float(self._values[long_name][0])
        for long_name, native in overrides.items():
            if long_name in self._values and native in frame.columns:
                frame.loc[self._start:self._end, native] = float(
                    self._values[long_name][0]
                )

    def _apply_rule(self, frame) -> None:
        rid, _coeffs = self.get_policy_rule()
        if rid == "MODEL_SPECIFIC":
            return
        col = self.RULE_COLUMNS.get(rid)
        if col is None:
            return
        for c in self.ALL_RULE_COLUMNS:
            if c in frame.columns:
                frame.loc[self._start:self._end, c] = 0
        if col in frame.columns:
            frame.loc[self._start:self._end, col] = 1

    def _populate_from_data(self) -> None:
        if self._data is None:
            return
        row = self._data.loc[self._report_period]
        for long_name, (native, _transform) in self.OUTPUT_NATIVE.items():
            if native in self._data.columns:
                self._values[long_name] = np.array(
                    [float(row[native])], dtype="float64"
                )

    def report_at(self, period) -> None:
        """Choose which horizon period get_value reports (default end)."""
        import pandas as pd

        self._report_period = pd.Period(period, freq="Q")

    # ------------------------------------------------------------------ #
    def get_mmb_capabilities(self):
        # FRB/US ships its own rule variants; expose them plus MODEL_SPECIFIC.
        declared = super().get_mmb_capabilities()
        return declared or list(self.RULE_COLUMNS.keys()) + ["MODEL_SPECIFIC"]

    def _on_policy_rule_changed(self, rule_id, coefficients) -> None:
        """The swap is applied per-solve in `_apply_rule` (which reads the
        current rule from `get_policy_rule`), so this hook is a no-op."""
        return None
