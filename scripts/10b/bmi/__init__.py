"""BMI (Basic Model Interface) compatibility layer for the 10B registry.

Every model node in `global/10B/` is addressable through CSDMS BMI via a
subclass of `Bmi10BBase`. The `bmi_class` field on each `model.run.json`
names the implementing class (see `classmap.bmi_class_for`).

Public surface:
  - `Bmi10BBase`        the registry-aware BMI base class
  - `BmiDependencyMissing` raised when an optional runtime is absent
  - `STANDARD_NAMES`    the CSDMS-style standard-name registry
  - `GRIDS`             the 7-grid taxonomy descriptors
  - `bmi_class_for` / `load_bmi`  model-id ↔ BMI-class mapping

Because `scripts/10b/` is not an importable dotted package (its name
starts with a digit), this package is addressed as the top-level `bmi`
after `scripts/10b/` is placed on `sys.path` — the same convention the
other pipeline scripts use for `_paths` / `_schema`.
"""

from __future__ import annotations

from .base import Bmi10BBase, BmiDependencyMissing
from .standard_names import STANDARD_NAMES, MMB_ALIASES, resolve
from .grids import GRIDS
from .classmap import bmi_class_for, load_bmi, parse_bmi_class

__all__ = [
    "Bmi10BBase",
    "BmiDependencyMissing",
    "STANDARD_NAMES",
    "MMB_ALIASES",
    "resolve",
    "GRIDS",
    "bmi_class_for",
    "load_bmi",
    "parse_bmi_class",
]
