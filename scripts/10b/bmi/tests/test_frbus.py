"""FRB/US wrapper tests.

These run without `pyfrbus` installed: they exercise import, BMI
introspection, and graceful dependency degradation. The actual solve is
only checked when `pyfrbus` is importable (otherwise skipped).
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[2]))  # scripts/10b

from _paths import tenb_root  # noqa: E402
from bmi.base import BmiDependencyMissing  # noqa: E402
from bmi.external.frbus import FrbusBmi  # noqa: E402

BASE = tenb_root()
RUN = BASE / "external/federalreserve/frbus/model.run.json"

FIVE_COMMON = [
    "monetary_policy__short_rate_annualized",
    "consumer_prices__inflation_yoy_pct",
    "consumer_prices__inflation_qoq_annualized",
    "national_accounts__output_gap_pct",
    "national_accounts__output_level_index",
]


def _pyfrbus_available() -> bool:
    try:
        import pyfrbus  # noqa: F401

        return True
    except Exception:
        return False


def test_imports_without_pyfrbus():
    # Constructing and introspecting must not require pyfrbus.
    f = FrbusBmi()
    outs = set(f.get_output_var_names())
    for name in FIVE_COMMON:
        assert name in outs, f"{name} missing from FRB/US outputs"
    # Residual / shock inputs are present (the bottom-up entry point).
    ins = set(f.get_input_var_names())
    assert "monetary_policy__rule_shock" in ins
    assert "fiscal_policy__discretionary_shock" in ins


def test_capabilities():
    f = FrbusBmi()
    f.initialize_meta_only()  # load run.json without pyfrbus (see helper below)
    caps = f.get_mmb_capabilities()
    assert "MODEL_SPECIFIC" in caps
    assert "TAYLOR_LWW" in caps


def test_initialize_degrades_without_pyfrbus():
    if _pyfrbus_available():
        print("pyfrbus present; skipping degradation assertion")
        return
    f = FrbusBmi()
    try:
        f.initialize(str(RUN))
        assert False, "expected BmiDependencyMissing without pyfrbus"
    except BmiDependencyMissing as e:
        assert "pyfrbus" in str(e)


def test_solve_when_pyfrbus_present():
    if not _pyfrbus_available():
        print("pyfrbus not installed; skipping live solve")
        return
    import numpy as np

    f = FrbusBmi()
    f.initialize(str(RUN))
    f.update()
    buf = np.empty(1, dtype="float64")
    f.get_value("monetary_policy__short_rate_annualized", buf)
    assert np.isfinite(buf[0])


# Small helper so capability tests can read the mmb block without pyfrbus:
def _initialize_meta_only(self, run_path=str(RUN)):
    import json
    from pathlib import Path as _P

    self._run = json.loads(_P(run_path).read_text())
    self._model_id = self._run.get("modelId", "")


FrbusBmi.initialize_meta_only = lambda self: _initialize_meta_only(self)


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
