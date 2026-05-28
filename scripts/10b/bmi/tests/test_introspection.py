"""Introspection tests for the 10B BMI layer, driven by the live registry.

Read-only: instantiates one BMI node per class against the materialised
`global/10B/` tree and asserts the BMI surface is coherent. Runs without
`bmipy` installed (the base falls back to a local ABC) and without
`countries.json` (grids derive the country set from the materialised tree).

Run with `scripts/10b/` on the path:
    PYTHONPATH=scripts/10b python -m pytest scripts/10b/bmi/tests -q
or directly:
    PYTHONPATH=scripts/10b python scripts/10b/bmi/tests/test_introspection.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[2]))  # scripts/10b

from _paths import tenb_root  # noqa: E402
from bmi import bmi_class_for, load_bmi, grids, standard_names  # noqa: E402

BASE = tenb_root()

# One representative node per BMI class -> registry-relative directory.
SAMPLES = {
    "MacroBmi": ".",
    "SchemaBmi": "schema",
    "DynamicsBmi": "dynamics",
    "SupervisedBmi": "supervised-trajectory",
    "PersonalAgentBmi": "personal-agent",
    "CategoryWorldBmi": "categories/food",
    "CountryRollupBmi": "countries/india",
    "CellBmi": "countries/india/health",
    "RegionRollupBmi": "regions/africa",
}


def _node(relpath: str):
    run_path = BASE / relpath / "model.run.json"
    import json

    mid = json.loads(run_path.read_text())["modelId"]
    cls = load_bmi(bmi_class_for(mid))
    inst = cls()
    inst.initialize(str(run_path))
    return inst


def test_every_class_introspects():
    for cls_name, relpath in SAMPLES.items():
        inst = _node(relpath)
        assert inst.get_component_name()
        # Non-schema nodes consume or produce at least one variable.
        out_names = inst.get_output_var_names()
        assert len(out_names) >= 1, f"{cls_name} has no outputs"
        for name in inst.get_input_var_names() + out_names:
            # Every declared var resolves to a registered standard name,
            # a known grid, and a numpy-or-str dtype.
            assert standard_names.is_registered(name), f"{name} not registered"
            gid = inst.get_var_grid(name)
            assert gid in grids.GRIDS, f"{cls_name}:{name} bad grid {gid}"
            dtype = inst.get_var_type(name)
            assert dtype in ("float64", "int32", "int8", "str")


def test_get_value_reads_materialised_output():
    # Cell score round-trips from runs/output.json.
    cell = _node("countries/india/health")
    cell.update()
    g = cell.get_var_grid("population_needs__satisfaction_score")
    buf = np.empty(cell.get_grid_size(g), dtype="float64")
    cell.get_value("population_needs__satisfaction_score", buf)
    assert 0.0 <= float(buf[0]) <= 1.0

    # Country rollup score in [0,1].
    country = _node("countries/india")
    country.update()
    buf = np.empty(1, dtype="float64")
    country.get_value("population_needs__satisfaction_score", buf)
    assert 0.0 <= float(buf[0]) <= 1.0


def test_dynamics_cluster_ids_on_country_grid():
    dy = _node("dynamics")
    dy.update()
    g = dy.get_var_grid("population_dynamics__cluster_id")
    assert g == grids.COUNTRY_POINTS
    buf = np.empty(dy.get_grid_size(g), dtype="int32")
    dy.get_value("population_dynamics__cluster_id", buf)
    assigned = sorted(set(int(x) for x in buf if x >= 0))
    assert len(assigned) >= 2  # at least a couple of clusters present


def test_mmb_aliases_resolve():
    assert standard_names.resolve("interest") == "monetary_policy__short_rate_annualized"
    assert standard_names.resolve("outputgap") == "national_accounts__output_gap_pct"
    # Unknown / already-canonical names pass through unchanged.
    assert standard_names.resolve("population_needs__satisfaction_score") == \
        "population_needs__satisfaction_score"


def test_grid_nbytes_consistent():
    cell = _node("countries/india/health")
    name = "population_needs__satisfaction_score"
    itemsize = cell.get_var_itemsize(name)
    size = cell.get_grid_size(cell.get_var_grid(name))
    assert cell.get_var_nbytes(name) == itemsize * size


def _run_all():
    """Allow running without pytest installed."""
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
