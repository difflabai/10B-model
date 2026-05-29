"""Generate the registry metadata for the FRB/US external node.

This writes `global/10B/external/federalreserve/frbus/{model.meta.json,
model.run.json}` — committed metadata so the registry always knows the
node exists (and the coupler can wire it) even when the `pyfrbus` runtime
is not installed. The runtime stays out of the repo (see `.gitignore`).

    PYTHONPATH=scripts/10b python -m bmi.external.frbus_node
"""

from __future__ import annotations

import sys
from pathlib import Path

_sys_path = str(Path(__file__).resolve().parents[2])
if _sys_path not in sys.path:
    sys.path.insert(0, _sys_path)

from _paths import tenb_root  # noqa: E402
from _schema import (  # noqa: E402
    component,
    io_spec,
    model_run,
    parameter_row,
    reference,
    write_json,
)
from bmi.mmb import build_mmb_block  # noqa: E402

MODEL_ID = "external.federalreserve.frbus"
CAPABILITIES = [
    "TAYLOR_LWW", "TAYLOR_INERTIAL", "MC_TAYLOR_INERTIAL",
    "TAYLOR_INTERCEPT", "MODEL_SPECIFIC",
]


def build_meta() -> dict:
    return {
        "id": MODEL_ID,
        "name": "FRB/US — Federal Reserve macro model",
        "kind": "sector_economic",
        "blurb": (
            "BMI + MMB wrapper around the Federal Reserve Board's FRB/US, a "
            "~380-equation quarterly macroeconometric model of the US economy. "
            "Backs the US country rollup and the five US macro cells; exposes "
            "the five MMB common variables and a swappable monetary policy rule."
        ),
        "mechanism": (
            "FRB/US is distributed by the Federal Reserve as the Python package "
            "`pyfrbus`, which 10B does not bundle. Install it locally (see "
            "https://www.federalreserve.gov/econres/us-models-package.htm) into "
            "`<repo>/pyfrbus/` or set `$BWM_FRBUS_PCIM`. The wrapper imports it "
            "lazily: introspection and the rest of the pipeline work without it. "
            "Lifecycle maps initialize→load model+LONGBASE, update→solve one "
            "quarter, update_until→solve to horizon. The five MMB common "
            "variables are sourced from native `rff`/`pic4`/`picxfe`/`xgap2`/"
            "`xgdp`; residual (`*_aerr`) inputs are the bottom-up entry point."
        ),
        "components": [
            component("loader", "Model + data loader",
                      "Loads the FRB/US model file and LONGBASE dataset.",
                      ["initialize", "load_data"]),
            component("solver", "FRB/US solver",
                      "Solves the model forward quarter by quarter.",
                      ["solve", "mce_solve"]),
            component("policy", "Swappable policy rule",
                      "Toggles the FRB/US monetary policy rule per MMB capability.",
                      ["set_policy_rule"]),
        ],
        "inputs": [
            io_spec("monetary-policy-shock", "scalar",
                    "Policy rule shock (FRB/US rffintay_aerr)."),
            io_spec("fiscal-shock", "scalar",
                    "Discretionary fiscal shock (FRB/US egfo_aerr)."),
            io_spec("oil-price", "scalar", "Crude oil price overlay (poilr)."),
        ],
        "outputs": [
            io_spec("interest", "scalar", "Federal funds rate (rff), annualised %."),
            io_spec("inflation", "scalar", "4-quarter inflation (pic4), %."),
            io_spec("outputgap", "scalar", "Output gap (xgap2), %."),
            io_spec("output", "scalar", "Real GDP index (xgdp)."),
            io_spec("unemployment", "scalar", "Unemployment rate (lur), %."),
        ],
        "parameters": [
            parameter_row("expectations", "VAR",
                          "Expectations mode: VAR (default) or MC."),
            parameter_row("equations", "~380", "Approximate equation count."),
            parameter_row("frequency", "quarterly", "Solution frequency."),
        ],
        "references": [
            reference("FRB/US model package", "url",
                      "https://www.federalreserve.gov/econres/us-models-package.htm"),
            reference("FRB/US in Python", "url",
                      "https://www.federalreserve.gov/econres/us-models-python.htm"),
        ],
        # FRB/US is a source the US rollup and US macro cells consume; it has
        # no in-registry prerequisites of its own. The consumer edges live on
        # those nodes (added by generate.py when FRB/US is active), and the
        # execution ordering is encoded in the coupler's class-level DAG.
        "depends_on": [],
    }


def build_run() -> dict:
    return model_run(
        model_id=MODEL_ID,
        engine="external-solver",
        mmb=build_mmb_block(CAPABILITIES, rule_id="MODEL_SPECIFIC", msr=None),
        inputs={
            "model-file": {"env": "BWM_FRBUS_PCIM",
                           "default": "../../../../pyfrbus/data/model.xml"},
            "data-file": {"env": "BWM_FRBUS_DATA",
                          "default": "../../../../pyfrbus/data/LONGBASE.TXT"},
            "frbus_blend_weight": {"value": 0.5},
        },
        spec={"inline": {"expectations": "VAR", "horizon_quarters": 40}},
        output="./runs/output.json",
    )


def main(argv=None) -> int:
    node_dir = tenb_root() / "external" / "federalreserve" / "frbus"
    write_json(node_dir / "model.meta.json", build_meta())
    write_json(node_dir / "model.run.json", build_run())
    print(f"FRB/US node metadata written to {node_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
