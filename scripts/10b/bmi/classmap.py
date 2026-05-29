"""Map a 10B model id to the BMI class that implements it, and back.

The model id is a complete discriminator for which BMI subclass a node
needs — the registry's dot-path encodes the node's role. This mapping is
the single source of truth, used by:

  - the generators (when they emit `bmi_class` into `model.run.json`),
  - the `backfill_bmi_class` migration (stamping existing run files),
  - the coupler (instantiating the right class per node),
  - `model_registry.py` (recording each submodel's class).

`bmi_class` strings are `"module:ClassName"`. Because the pipeline lives
under `scripts/10b/` — not an importable dotted package (the directory
name starts with a digit) — the modules are addressed as top-level
`bmi.*`, matching how the other pipeline scripts import `_paths` /
`_schema` after putting `scripts/10b/` on `sys.path`.
"""

from __future__ import annotations

import importlib
from typing import Tuple

# Country slugs whose rollup is MMB Modelbase-block compliant because a
# macroeconomic backing model is registered for them. The United States is
# backed by FRB/US; others join as their backing models are wrapped.
MMB_BACKED_COUNTRIES = {"united-states"}


def bmi_class_for(model_id: str) -> str:
    """Return the `"module:ClassName"` BMI pointer for a model id."""
    mid = model_id
    parts = mid.split(".")

    if mid == "global.10B":
        return "bmi.macro:MacroBmi"
    if mid == "global.10B.needs-tree":
        return "bmi.schema:SchemaBmi"
    if mid == "global.10B.dynamics":
        return "bmi.dynamics:DynamicsBmi"
    if mid == "global.10B.supervised-trajectory":
        return "bmi.supervised:SupervisedBmi"
    if mid == "global.10B.personal-agent":
        return "bmi.agent:PersonalAgentBmi"

    if mid.startswith("global.10B.categories."):
        return "bmi.categories:CategoryWorldBmi"

    if mid.startswith("global.10B.regions."):
        # Both region rollups (.regions.africa) and region×category cells
        # (.regions.africa.food) share one class.
        return "bmi.regions:RegionRollupBmi"

    if mid.startswith("global.10B.countries."):
        # 4 parts → country rollup; 5 parts → country×category cell.
        if len(parts) == 5:
            return "bmi.cells:CellBmi"
        # Countries with a registered macroeconomic backing are MMB-compliant.
        if parts[3] in MMB_BACKED_COUNTRIES:
            return "bmi.countries:MmbCountryRollupBmi"
        return "bmi.countries:CountryRollupBmi"

    if mid.startswith("external.federalreserve.frbus"):
        return "bmi.external.frbus:FrbusBmi"

    raise ValueError(f"no BMI class mapping for model id {model_id!r}")


def parse_bmi_class(bmi_class: str) -> Tuple[str, str]:
    """Split a `"module:ClassName"` pointer into (module, class_name)."""
    if ":" not in bmi_class:
        raise ValueError(
            f"invalid bmi_class {bmi_class!r}; expected 'module:ClassName'"
        )
    module, cls = bmi_class.split(":", 1)
    return module, cls


def load_bmi(bmi_class: str):
    """Import and return the BMI class object named by a `bmi_class` pointer.

    Raises ImportError / AttributeError with the original context if the
    module or class can't be resolved — callers (validate --import-check,
    the coupler) surface this directly.
    """
    module, cls = parse_bmi_class(bmi_class)
    mod = importlib.import_module(module)
    return getattr(mod, cls)
