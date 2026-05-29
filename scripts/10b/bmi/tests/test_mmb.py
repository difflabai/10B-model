"""MMB Modelbase-block compatibility tests (driven by the live registry)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[2]))  # scripts/10b

from _paths import tenb_root  # noqa: E402
from bmi import bmi_class_for, load_bmi  # noqa: E402
from bmi.mmb import (  # noqa: E402
    MMB_COMMON_NAMES, MMB_RULE_VALUES, build_mmb_block, mmb_block_errors,
    mmb_block_for,
)

BASE = tenb_root()


def _us_rollup():
    mid = "global.10B.countries.united-states"
    cls = load_bmi(bmi_class_for(mid))
    inst = cls()
    inst.initialize(str(BASE / "countries/united-states/model.run.json"))
    return inst


def test_us_rollup_is_mmb_compliant():
    us = _us_rollup()
    assert type(us).__name__ == "MmbCountryRollupBmi"
    assert us.is_mmb_compliant()
    caps = us.get_mmb_capabilities()
    assert caps and set(caps) <= MMB_RULE_VALUES
    # All five MMB common variables are among the outputs.
    outs = set(us.get_output_var_names())
    for short, long in us.get_mmb_common_variables().items():
        assert short in MMB_COMMON_NAMES
        assert long in outs


def test_policy_rule_swap():
    us = _us_rollup()
    rid, msr = us.get_policy_rule()
    assert rid == "MODEL_SPECIFIC" and msr is None
    us.set_policy_rule("TAYLOR_LWW")
    assert us.get_policy_rule()[0] == "TAYLOR_LWW"
    # Unknown rule rejected.
    try:
        us.set_policy_rule("NOPE")
        assert False, "should have rejected unknown rule"
    except ValueError:
        pass
    # Wrong-length msr rejected.
    try:
        us.set_policy_rule("TAYLOR_LWW", np.zeros(5))
        assert False, "should have rejected short msr"
    except ValueError:
        pass


def test_mmb_block_validation():
    good = build_mmb_block(["TAYLOR_LWW", "MODEL_SPECIFIC"])
    assert mmb_block_errors(good) == []
    # Missing a common variable.
    bad = build_mmb_block(["TAYLOR_LWW"])
    bad["common_variables"].pop("output")
    assert mmb_block_errors(bad)
    # Unknown capability.
    bad2 = build_mmb_block(["NOT_A_RULE"])
    assert mmb_block_errors(bad2)


def test_only_us_rollup_is_backed():
    assert mmb_block_for("global.10B.countries.united-states") is not None
    assert mmb_block_for("global.10B.countries.india") is None
    assert mmb_block_for("global.10B.countries.united-states.health") is None


def test_frbus_node_mmb_block_valid():
    import json
    run = json.loads(
        (BASE / "external/federalreserve/frbus/model.run.json").read_text()
    )
    assert "mmb" in run
    assert mmb_block_errors(run["mmb"]) == []


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
