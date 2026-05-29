# BMI compatibility layer for the 10B registry

This package makes every model node in `global/10B/` addressable through
the CSDMS **Basic Model Interface** (BMI), and publishes the whole 10B
model as a single CSDMS-style registry entry. The design rationale —
why BMI, the grid taxonomy, the standard-name namespaces, the MMB
profile, and the FRB/US mapping — lives in
[`.context/bmi-10b-architecture.md`](../../../.context/bmi-10b-architecture.md).
This README is the operational reference.

## What it adds

- A `bmi_class` field on every `model.run.json` naming the BMI class that
  implements that node (e.g. `"bmi.cells:CellBmi"`).
- A top-level **`/model-registry.json`** (repo root) — one file an
  external CSDMS/BMI consumer reads to discover every submodel, its BMI
  class, and the package entrypoint. `global/10B/runs/manifest.json` is a
  10B-internal view derived from it.
- A read-only introspection CLI and a coupler that derives execution
  order from the dependency graph.

No model outputs change: the BMI classes wrap the existing pipeline. In
this phase `_compute()` reads the already-materialised `runs/output.json`
files; it does not recompute.

## Layout

| module | purpose |
|---|---|
| `base.py` | `Bmi10BBase` — registry-aware BMI base (full BMI 2.0 surface) |
| `standard_names.py` | `population_*` + macro standard names; MMB aliases |
| `grids.py` | the 7-grid taxonomy + country/region geometry helpers |
| `classmap.py` | model-id ↔ BMI-class mapping (single source of truth) |
| `cells.py` … `schema.py` | the 10 node classes (cell, rollups, heads, …) |
| `coupler.py` | execution-order + dependency audit + `inspect` |
| `cli.py` | `inspect` / `names` / `grids` introspection commands |
| `model_registry.py` | builds `/model-registry.json` |
| `backfill_bmi_class.py` | one-time migration stamping `bmi_class` on existing files |
| `tests/` | introspection tests driven by the live registry |

## Import convention

`scripts/10b/` is not an importable dotted package (its name starts with a
digit), so — like the existing `_paths` / `_schema` modules — this package
is addressed as the top-level `bmi` after `scripts/10b/` is on
`PYTHONPATH`:

```sh
export PYTHONPATH=scripts/10b
```

## Usage

```sh
# Inspect a node's BMI variable + grid surface
python -m bmi.cli inspect global.10B.countries.india.health

# List the standard-name registry / grid taxonomy
python -m bmi.cli names
python -m bmi.cli grids

# Print the execution order and audit dependency edges
python -m bmi.coupler --dry-run

# Inspect via the coupler (same as cli inspect)
python -m bmi.coupler --inspect global.10B

# Rebuild the top-level registry descriptor
python -m bmi.model_registry

# Stamp bmi_class onto existing run files (idempotent; --check for dry-run)
python -m bmi.backfill_bmi_class --check
```

Programmatic:

```python
import numpy as np
from bmi import load_bmi, bmi_class_for
from _paths import tenb_root

base = tenb_root()
cls = load_bmi(bmi_class_for("global.10B.countries.india.health"))
node = cls()
node.initialize(str(base / "countries/india/health/model.run.json"))
node.update()
buf = np.empty(node.get_grid_size(
    node.get_var_grid("population_needs__satisfaction_score")))
node.get_value("population_needs__satisfaction_score", buf)
print(buf)  # India × health composite score
```

## Grid taxonomy

| id | type | what it carries |
|---|---|---|
| 0 | scalar | world means, single scores, AUC |
| 1 | points (lat/lon) | per-country scalars |
| 2 | rectilinear (n×15) | country × category matrix (macro) |
| 3 | points | UN-region centroids |
| 4 | rectilinear (6×15) | region × category matrix |
| 5 | unstructured | cluster centroids / peer graph |
| 6 | uniform_rectilinear | forecast horizons (time) |

The same standard name may sit on different grids in different nodes — a
satisfaction score is a scalar in a cell, a per-country vector in a
category rollup, and the full matrix at the macro node — which is why each
node owns its `_grid_for`.

## Standard names

CSDMS-style `object__quantity` names in dedicated namespaces:
`population_*` for the human-needs core, plus `monetary_policy__*`,
`consumer_prices__*`, `national_accounts__*`, `labour_market__*`,
`fiscal_policy__*` for the macro / MMB surface. The five MMB common
variables have short aliases (`interest`, `inflation`, `inflationq`,
`outputgap`, `output`); `standard_names.resolve()` follows them.

## MMB Modelbase-block compatibility

Macroeconomic nodes additionally implement the IMFS Goethe **MMB** profile
(`mmb.py::MmbCompliantBmi`): they expose the five MMB common variables
(`interest`, `inflation`, `inflationq`, `outputgap`, `output`), declare the
policy rules they can be simulated under, and support a swappable policy
rule. Such a node carries an `mmb` block in its `model.run.json`.

In this repo the MMB-compliant nodes are the **FRB/US** wrapper and the
**US country rollup** it backs:

```sh
# Which MMB-compliant nodes each rule would re-simulate
python -m bmi.coupler --rule TAYLOR_LWW,SW
```

```python
from bmi import load_bmi, bmi_class_for
from _paths import tenb_root
us = load_bmi(bmi_class_for("global.10B.countries.united-states"))()
us.initialize(str(tenb_root() / "countries/united-states/model.run.json"))
us.get_mmb_capabilities()          # ['TAYLOR_LWW', 'TAYLOR_INERTIAL', ...]
us.set_policy_rule("TAYLOR_LWW")   # swap the policy rule
```

## FRB/US integration

`bmi/external/frbus.py::FrbusBmi` wraps the Federal Reserve's FRB/US model
(`pyfrbus`) as a BMI + MMB node at `external.federalreserve.frbus`. The
runtime is **not bundled**: install it locally under `<repo>/pyfrbus/`
(data at `<repo>/pyfrbus/data/`) or set `$BWM_FRBUS_PCIM`. The wrapper
imports it lazily inside `initialize()`, so import, introspection,
validation, and the rest of the pipeline all work without it; calling
`update()` without it raises `BmiDependencyMissing` with an install hint.

The node's metadata is committed (regenerated by `python -m
bmi.external.frbus_node`); the five US macro cells (`work`, `mobility`,
`communications`, `governance`, `energy`) gain an FRB/US dependency edge
only when `$BWM_FRBUS_PCIM` is set, so a checkout without FRB/US
regenerates byte-identically.

### Downloading and running FRB/US

FRB/US is published by the Federal Reserve Board, not on PyPI, and 10B does
not redistribute it. You download it once, install it into a virtualenv,
and point 10B at it.

**1. Download the package.** Get the FRB/US *Python* package (`pyfrbus`)
from the Fed:

> https://www.federalreserve.gov/econres/us-models-package.htm

Unzip it. The tree looks like:

```
pyfrbus/
├── setup.py
├── pyfrbus/            # the Python package
├── models/
│   └── model.xml       # the model file   ← note: models/, not data/
├── data/
│   └── LONGBASE.TXT    # the baseline dataset (tab-separated, quarterly)
└── demos/              # example1.py … (canonical usage)
```

Put it at `<repo>/pyfrbus/` (it is `.gitignore`'d) or anywhere you like —
you can point at it with env vars instead.

**2. Install into a virtualenv.** `pyfrbus` needs `pandas>=2.1,<3`, `scipy`,
`numpy`, `sympy==1.3`, `symengine`, `networkx`, `lxml` — a system Python
usually lacks `scipy`/`symengine`, so use a fresh venv (Python ≥3.9):

```sh
python3.11 -m venv ~/.venvs/frbus
~/.venvs/frbus/bin/pip install --upgrade pip
~/.venvs/frbus/bin/pip install /path/to/pyfrbus      # runs setup.py, pulls deps
# sanity check:
~/.venvs/frbus/bin/python -c "from pyfrbus.frbus import Frbus; print('ok')"
```

**3. Tell 10B where the model + data are.** Two env vars (the wrapper also
auto-discovers `<repo>/pyfrbus/{models/model.xml,data/LONGBASE.TXT}`):

```sh
export BWM_FRBUS_PCIM=/path/to/pyfrbus/models/model.xml
export BWM_FRBUS_DATA=/path/to/pyfrbus/data/LONGBASE.TXT
export PYTHONPATH=scripts/10b          # so the `bmi` package imports
```

**4. Run a live solve.** Use the venv Python (it has the FRB/US deps).
Baseline vs a +100 bp monetary tightening, driven through the BMI cycle:

```python
# run with ~/.venvs/frbus/bin/python, env vars from step 3 set
import numpy as np
from bmi import load_bmi, bmi_class_for
from _paths import tenb_root

run = str(tenb_root() / "external/federalreserve/frbus/model.run.json")

def frbus():
    f = load_bmi(bmi_class_for("external.federalreserve.frbus"))()
    f.initialize(run)         # loads model.xml + LONGBASE, runs init_trac
    f.report_at("2042Q4")     # which horizon quarter get_value reports
    return f

rate = "monetary_policy__short_rate_annualized"
gap = "national_accounts__output_gap_pct"

base = frbus(); base.update()
shock = frbus()
shock.set_value("monetary_policy__rule_shock", np.array([1.0]))  # +100 bp
shock.update()

buf = np.empty(1)
for f, label in [(base, "baseline"), (shock, "shock")]:
    f.get_value(rate, buf); r = float(buf[0])
    f.get_value(gap, buf);  g = float(buf[0])
    print(f"{label:8s} rate={r:.3f}  outputgap={g:.3f}")
# shock shows the output gap falling and inflation/GDP softening — a
# textbook monetary contraction.
```

`set_policy_rule("TAYLOR_INERTIAL")` (or any `get_mmb_capabilities()` entry)
swaps the FRB/US monetary policy rule before `update()`.

**5. The FRB/US backing flows into the US models.** Attach the solved
FRB/US node to the US country rollup or a US macro cell and its score
becomes monetary-policy-responsive:

```python
us = load_bmi(bmi_class_for("global.10B.countries.united-states"))()
us.initialize(str(tenb_root() / "countries/united-states/model.run.json"))
us.attach_backing(shock)      # wire in the solved FRB/US node
us.update()
# us now serves the five MMB common variables sourced from FRB/US, and the
# US 'work' cell's satisfaction score reflects the tightening.
```

**6. Verify with the test suite.** `test_frbus.py` runs the live solve when
`pyfrbus` is importable and skips it otherwise:

```sh
BWM_FRBUS_PCIM=… BWM_FRBUS_DATA=… PYTHONPATH=scripts/10b \
  ~/.venvs/frbus/bin/python scripts/10b/bmi/tests/test_frbus.py
```

**Notes / gotchas.**
- The model file is `models/model.xml`, *not* `data/model.xml` — a common
  mix-up. `BWM_FRBUS_PCIM` must point at the former.
- FRB/US solves over a horizon (default 40 quarters from `2040Q1`, set via
  `spec.inline.{start,horizon_quarters}` in the node's `model.run.json`),
  not one quarter at a time. `update()` re-solves the whole horizon from a
  cached add-factored baseline; `report_at()` picks the reported quarter.
- Expectations default to VAR; `spec.inline.expectations: "MC"` selects
  model-consistent expectations.
- Without FRB/US installed, none of this is required — the pipeline,
  introspection, and validation all run, and `FrbusBmi.update()` raises a
  `BmiDependencyMissing` that repeats these install steps.

## Production runner

The pipeline runs through the coupler by default:

```sh
bash scripts/10b/pipeline.sh            # = python -m bmi.coupler run
bash scripts/10b/pipeline.sh --plan     # preview the step list
bash scripts/10b/pipeline.sh --legacy   # inline script sequence (escape hatch)
```

The coupler sequences the same generation scripts in dependency order plus
the FRB/US-node and model-registry steps, so its output is byte-for-byte
equal to `--legacy`. That equivalence is the migration's acceptance gate
(a required CI diff) and must be run against a real `countries.json`.

## Optional dependencies

- **`bmipy`** — when installed, `Bmi10BBase` subclasses the real
  `bmipy.Bmi`; otherwise it falls back to a local ABC with the same
  surface, so the layer works on a plain checkout.
- **`countries.json`** — `grids.py` uses it for country centroids and
  order when present, and derives the country set from the materialised
  `countries/` tree when absent.

## Validation

`validate.py` checks every `model.run.json` has a well-formed `bmi_class`
and that `/model-registry.json` is consistent with the on-disk tree. With
`--import-check` it additionally imports every `bmi_class`:

```sh
PYTHONPATH=scripts/10b python scripts/10b/validate.py --import-check
```
