#!/usr/bin/env python3
"""Validates every generated model.meta.json under registry/global/10B.

Mirrors the Rust ModelMeta serde contract (see crates/bwm-server/src/types.rs
and crates/bwm-server/src/registry/meta.rs).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import tenb_root  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE = tenb_root()

KIND_VALUES = {"forecast_harness", "sector_economic"}
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


def main() -> int:
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
