"""Build the top-level `model-registry.json` — 10B as a single CSDMS entry.

The whole 10B model is intended to register as ONE entry in the CSDMS
model registry, internally exposing its submodel tree. This module writes
that descriptor to the repo root: a single file an external BMI/CSDMS
consumer (or the downstream `bwm-server`) reads to discover every submodel,
its implementing BMI class, and the package entrypoint.

`model-registry.json` is the canonical artifact; `manifest.py` derives its
10B-internal `runs/manifest.json` view from it (no data computed twice).

    PYTHONPATH=scripts/10b python -m bmi.model_registry
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_sys_path = str(Path(__file__).resolve().parent.parent)
if _sys_path not in sys.path:
    sys.path.insert(0, _sys_path)

from _paths import registry_root, tenb_root  # noqa: E402

from bmi import grids as _grids  # noqa: E402
from bmi import standard_names as _sn  # noqa: E402

SCHEMA_VERSION = "1.0"
BMI_VERSION = "2.0"
BMI_PACKAGE = "bmi"
BMI_ENTRYPOINT = "bmi.macro:MacroBmi"

STANDARD_NAME_NAMESPACES = [
    "population_*",
    "monetary_policy__*",
    "consumer_prices__*",
    "labour_market__*",
    "national_accounts__*",
    "fiscal_policy__*",
]


def _grid_entries() -> List[Dict[str, Any]]:
    out = []
    for gid in sorted(_grids.GRIDS):
        d = _grids.GRIDS[gid]
        out.append({
            "id": gid,
            "type": d.grid_type,
            "rank": d.rank,
            "shape": list(d.shape) if d.shape is not None else None,
            "has_xy": d.has_xy,
            "has_edges": d.has_edges,
        })
    return out


def _submodels(base: Path) -> List[Dict[str, Any]]:
    """One entry per `model.meta.json` node: id, BMI class, MMB flag, path."""
    rroot = registry_root()
    entries: List[Dict[str, Any]] = []
    for meta_path in base.rglob("model.meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        mid = meta.get("id")
        if not mid:
            continue
        run_path = meta_path.parent / "model.run.json"
        bmi_class = None
        mmb_compliant = False
        if run_path.exists():
            try:
                run = json.loads(run_path.read_text(encoding="utf-8"))
                bmi_class = run.get("bmi_class")
                mmb_compliant = bool(run.get("mmb"))
            except Exception:
                pass
        try:
            rel = str(meta_path.relative_to(rroot))
        except ValueError:
            rel = str(meta_path)
        entries.append({
            "id": mid,
            "bmi_class": bmi_class,
            "mmb_compliant": mmb_compliant,
            "path": rel,
        })
    entries.sort(key=lambda e: e["id"])
    return entries


# Static metadata for external-model runtimes that 10B wraps but does not
# bundle. Keyed by the model-id prefix that identifies the node.
_EXTERNAL_RUNTIMES = {
    "external.federalreserve.frbus": {
        "name": "FRB/US (Federal Reserve)",
        "required": False,
        "runtime_package": "pyfrbus",
        "install_hint": (
            "Download the FRB/US Python package from "
            "https://www.federalreserve.gov/econres/us-models-package.htm into "
            "<repo>/pyfrbus/ (data at <repo>/pyfrbus/data/), or set "
            "$BWM_FRBUS_PCIM. Not redistributed by 10B."
        ),
    },
}


def _external_dependencies(submodels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Describe each registered external-model node (FRB/US, …) so a
    consumer knows it exists, how to install its runtime, and that it is
    optional.
    """
    out: List[Dict[str, Any]] = []
    for s in submodels:
        mid = s.get("id", "")
        if not mid.startswith("external."):
            continue
        meta = _EXTERNAL_RUNTIMES.get(mid, {})
        out.append({
            "id": mid,
            "bmi_class": s.get("bmi_class"),
            "mmb_compliant": s.get("mmb_compliant", False),
            "required": meta.get("required", False),
            "runtime_package": meta.get("runtime_package"),
            "install_hint": meta.get("install_hint"),
            "name": meta.get("name", mid),
        })
    return out


def build_registry(base: Optional[Path] = None, *, generated_at: Optional[str] = None) -> Dict[str, Any]:
    base = base or tenb_root()
    root_meta_path = base / "model.meta.json"
    description = ""
    name = "10B — human-needs macro model"
    if root_meta_path.exists():
        try:
            rm = json.loads(root_meta_path.read_text(encoding="utf-8"))
            description = rm.get("blurb", "")
            name = rm.get("name", name)
        except Exception:
            pass

    if generated_at is None:
        generated_at = (
            dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        )

    submodels = _submodels(base)
    external_deps = _external_dependencies(submodels)
    rroot = registry_root()
    try:
        manifest_rel = str((base / "runs" / "manifest.json").relative_to(rroot))
    except ValueError:
        manifest_rel = "global/10B/runs/manifest.json"

    return {
        "schema_version": SCHEMA_VERSION,
        "registry_kind": "csdms_bmi",
        "id": "io.10b-model",
        "name": name,
        "description": description,
        "generated_at": generated_at,
        "bmi_version": BMI_VERSION,
        "bmi_package": BMI_PACKAGE,
        "bmi_entrypoint": BMI_ENTRYPOINT,
        "standard_name_namespaces": STANDARD_NAME_NAMESPACES,
        "grids": _grid_entries(),
        "submodels": submodels,
        "external_dependencies": external_deps,
        "manifest_path": manifest_rel,
    }


def registry_path() -> Path:
    return registry_root() / "model-registry.json"


def main(argv=None) -> int:
    reg = build_registry()
    out = registry_path()
    out.write_text(
        json.dumps(reg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"model-registry: {len(reg['submodels'])} submodels -> {out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
