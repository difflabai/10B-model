#!/usr/bin/env python3
"""Validates every generated model.meta.json under registry/global/10B.

Mirrors the Rust ModelMeta serde contract (see crates/bwm-server/src/types.rs
and crates/bwm-server/src/registry/meta.rs).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import tenb_root  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE = tenb_root()

KIND_VALUES = {"forecast_harness", "sector_economic"}

# A bmi_class pointer is "module.path:ClassName".
BMI_CLASS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$")
REFKIND_VALUES = {"paper", "spec", "crate", "url"}
RELKIND_VALUES = {
    "depends_on",
    "consumes_from",
    "shares_component",
    "references_spec",
    "contains",
    "owns",
}

REQUIRED_TOP = {"id", "name", "kind", "blurb", "mechanism"}

REQUIRED_FORECAST = {
    "id",
    "label",
    "prompt",
    "resolution_criteria",
    "expected_resolution_at",
    "outcome_space",
    "schedule",
    "status",
}
FORECAST_STATUS = {"healthy", "stale", "pending", "resolved"}
OUTCOME_KIND = {"binary", "numeric", "categorical"}
SCHEDULE_KIND = {"fixed", "event_driven"}


def errors_for_meta(path: Path, meta: Dict[str, Any]) -> List[str]:
    errs: List[str] = []
    for k in REQUIRED_TOP:
        if k not in meta:
            errs.append(f"missing required key: {k}")

    if meta.get("kind") not in KIND_VALUES:
        errs.append(f"invalid kind: {meta.get('kind')!r}; expected one of {sorted(KIND_VALUES)}")

    for ref in meta.get("references", []) or []:
        if not isinstance(ref, dict):
            errs.append(f"reference is not an object: {ref}")
            continue
        if ref.get("kind") not in REFKIND_VALUES:
            errs.append(f"invalid reference.kind: {ref.get('kind')!r}")
        for k in ("label", "kind", "location"):
            if k not in ref:
                errs.append(f"reference missing key: {k}")

    for dep in meta.get("depends_on", []) or []:
        if not isinstance(dep, dict):
            errs.append(f"dep is not an object: {dep}")
            continue
        if dep.get("kind") not in RELKIND_VALUES:
            errs.append(f"invalid depends_on.kind: {dep.get('kind')!r}")
        if "target_model_id" not in dep:
            errs.append("depends_on missing target_model_id")

    for io_key in ("inputs", "outputs"):
        for io in meta.get(io_key, []) or []:
            for k in ("name", "kind", "description"):
                if k not in io:
                    errs.append(f"{io_key} entry missing {k}")

    for comp in meta.get("components", []) or []:
        for k in ("id", "name", "role"):
            if k not in comp:
                errs.append(f"component missing {k}")
        if "key_symbols" in comp and not isinstance(comp["key_symbols"], list):
            errs.append("component.key_symbols must be list")

    for p in meta.get("parameters", []) or []:
        for k in ("key", "value"):
            if k not in p:
                errs.append(f"parameter missing {k}")

    return errs


def errors_for_run(path: Path, run: Dict[str, Any], *, import_check: bool = False) -> List[str]:
    """Validate a `model.run.json`: it must carry a well-formed `bmi_class`
    pointer. With `import_check`, the class is actually imported (the hard
    check promoted in phase D); without it, only the shape is checked so
    `validate.py` stays dependency-free on a plain checkout.
    """
    errs: List[str] = []
    if "modelId" not in run:
        errs.append("missing modelId")
    bmi = run.get("bmi_class")
    bmi_cls = None
    if bmi is None:
        errs.append("missing bmi_class")
    elif not isinstance(bmi, str) or not BMI_CLASS_RE.match(bmi):
        errs.append(f"invalid bmi_class shape: {bmi!r}; expected 'module:ClassName'")
    elif import_check:
        try:
            from bmi.classmap import load_bmi

            bmi_cls = load_bmi(bmi)
        except Exception as e:  # noqa: BLE001
            errs.append(f"bmi_class not importable: {bmi!r} ({e})")

    mmb = run.get("mmb")
    if mmb is not None:
        from bmi.mmb import mmb_block_errors

        # Under import_check, also assert the node's outputs cover the five
        # MMB common variables (resolved to canonical standard names).
        out_names = None
        if bmi_cls is not None:
            try:
                from bmi import standard_names as _sn

                out_names = {
                    _sn.resolve(n) for n in getattr(bmi_cls, "OUTPUT_VARS", ())
                }
            except Exception:  # noqa: BLE001
                out_names = None
        errs.extend(f"mmb: {e}" for e in mmb_block_errors(mmb, out_names))
    return errs


def errors_for_forecast(meta: Dict[str, Any]) -> List[str]:
    errs: List[str] = []
    for k in REQUIRED_FORECAST:
        if k not in meta:
            errs.append(f"missing required key: {k}")
    if meta.get("status") not in FORECAST_STATUS:
        errs.append(f"invalid status: {meta.get('status')!r}")
    out = meta.get("outcome_space") or {}
    if out.get("kind") not in OUTCOME_KIND:
        errs.append(f"invalid outcome_space.kind: {out.get('kind')!r}")
    sched = meta.get("schedule") or {}
    if sched.get("kind") not in SCHEDULE_KIND:
        errs.append(f"invalid schedule.kind: {sched.get('kind')!r}")
    return errs


def validate_model_registry(base: Path, *, import_check: bool = False) -> List[str]:
    """Validate the top-level model-registry.json: it must exist, its
    `bmi_package` must import, and every submodel id it lists must have a
    `model.meta.json` on disk. Returns a list of error strings.
    """
    errs: List[str] = []
    try:
        from bmi.model_registry import registry_path
    except Exception as e:  # noqa: BLE001
        return [f"cannot import bmi.model_registry: {e}"]

    reg_path = registry_path()
    if not reg_path.exists():
        return [f"model-registry.json not found at {reg_path}"]
    try:
        reg = json.loads(reg_path.read_text())
    except Exception as e:  # noqa: BLE001
        return [f"model-registry.json parse error: {e}"]

    for key in ("schema_version", "registry_kind", "id", "bmi_package",
                "bmi_entrypoint", "submodels"):
        if key not in reg:
            errs.append(f"model-registry missing key: {key}")

    submodels = reg.get("submodels", [])
    known_ids = {
        json.loads(p.read_text()).get("id")
        for p in base.rglob("model.meta.json")
    }
    listed_ids = {s.get("id") for s in submodels}
    missing = listed_ids - known_ids
    if missing:
        errs.append(
            f"{len(missing)} registry submodel(s) have no model.meta.json: "
            f"{sorted(m for m in missing if m)[:3]}"
        )
    not_listed = known_ids - listed_ids
    if not_listed:
        errs.append(
            f"{len(not_listed)} on-disk model(s) absent from registry: "
            f"{sorted(m for m in not_listed if m)[:3]}"
        )

    if import_check:
        try:
            import importlib

            importlib.import_module(reg.get("bmi_package", ""))
        except Exception as e:  # noqa: BLE001
            errs.append(f"bmi_package not importable: {reg.get('bmi_package')!r} ({e})")
    return errs


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validate", description=__doc__)
    parser.add_argument(
        "--import-check",
        action="store_true",
        help="also import every bmi_class (requires the bmi package on path)",
    )
    args = parser.parse_args(argv)

    base = BASE
    if not base.exists():
        print(f"registry not generated at {base}")
        return 1
    meta_files = list(base.rglob("model.meta.json"))
    print(f"validating {len(meta_files)} meta files under {base}")
    bad = 0
    for f in meta_files:
        try:
            meta = json.loads(f.read_text())
        except Exception as e:
            print(f"  PARSE ERROR {f}: {e}")
            bad += 1
            continue
        errs = errors_for_meta(f, meta)
        if errs:
            bad += 1
            if bad <= 5:
                print(f"  ERR {f.relative_to(base)}:")
                for e in errs[:5]:
                    print(f"    - {e}")
    if bad:
        print(f"FAIL: {bad} of {len(meta_files)} meta files invalid")
        return 1
    print(f"OK: {len(meta_files)} meta files valid")

    run_files = list(base.rglob("model.run.json"))
    print(f"validating {len(run_files)} run files (bmi_class)")
    rbad = 0
    for f in run_files:
        try:
            run = json.loads(f.read_text())
        except Exception as e:
            print(f"  PARSE ERROR {f}: {e}")
            rbad += 1
            continue
        errs = errors_for_run(f, run, import_check=args.import_check)
        if errs:
            rbad += 1
            if rbad <= 5:
                print(f"  ERR {f.relative_to(base)}:")
                for e in errs[:5]:
                    print(f"    - {e}")
    if rbad:
        print(f"FAIL: {rbad} of {len(run_files)} run files invalid")
        return 1
    print(f"OK: {len(run_files)} run files valid")

    reg_errs = validate_model_registry(base, import_check=args.import_check)
    if reg_errs:
        print("validating model-registry.json")
        for e in reg_errs[:10]:
            print(f"  - {e}")
        print(f"FAIL: model-registry.json invalid ({len(reg_errs)} error(s))")
        return 1
    print("OK: model-registry.json valid")

    fc_files = [
        p
        for p in base.rglob("forecasts/*.json")
        if p.is_file() and p.name != "needs-tree.json"
    ]
    print(f"validating {len(fc_files)} forecast files")
    fbad = 0
    for f in fc_files:
        try:
            meta = json.loads(f.read_text())
        except Exception as e:
            print(f"  PARSE ERROR {f}: {e}")
            fbad += 1
            continue
        errs = errors_for_forecast(meta)
        if errs:
            fbad += 1
            if fbad <= 5:
                print(f"  ERR {f.relative_to(base)}:")
                for e in errs[:5]:
                    print(f"    - {e}")
    if fbad:
        print(f"FAIL: {fbad} of {len(fc_files)} forecast files invalid")
        return 1
    print(f"OK: {len(fc_files)} forecast files valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
