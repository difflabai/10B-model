"""One-time migration: stamp `bmi_class` onto existing `model.run.json`.

The generators now emit `bmi_class` (via `_schema.model_run`), but the
already-materialised registry predates that field. This backfill walks
every `model.run.json` and inserts `bmi_class` immediately after `engine`,
deriving it from the model id with the same `bmi.classmap.bmi_class_for`
the generators use — so a backfilled tree and a freshly generated tree are
byte-identical.

Idempotent: a file that already carries a (correct) `bmi_class` is left
untouched. Re-runnable safely.

    PYTHONPATH=scripts/10b python -m bmi.backfill_bmi_class            # apply
    PYTHONPATH=scripts/10b python -m bmi.backfill_bmi_class --check    # dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

_sys_path = str(Path(__file__).resolve().parent.parent)
if _sys_path not in sys.path:
    sys.path.insert(0, _sys_path)

from _paths import tenb_root  # noqa: E402
from _schema import write_json  # noqa: E402
from bmi.classmap import bmi_class_for  # noqa: E402
from bmi.mmb import mmb_block_for  # noqa: E402


def _with_bmi_class(run: dict, bmi_class: str, mmb: Optional[dict] = None) -> dict:
    """Return a new run dict with `bmi_class` inserted right after `engine`
    (and the `mmb` block right after `bmi_class` when supplied), preserving
    the order and values of every other key. Matches `_schema.model_run`.
    """
    out = {}
    for key, value in run.items():
        if key in ("bmi_class", "mmb"):
            continue  # re-inserted in canonical position below
        out[key] = value
        if key == "engine":
            out["bmi_class"] = bmi_class
            if mmb is not None:
                out["mmb"] = mmb
    if "engine" not in run:
        out["bmi_class"] = bmi_class
        if mmb is not None:
            out["mmb"] = mmb
    return out


def backfill(root: Optional[Path] = None, *, check: bool = False) -> int:
    base = root or tenb_root()
    run_files = sorted(base.rglob("model.run.json"))
    changed = 0
    correct = 0
    errors: List[str] = []

    for path in run_files:
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{path}: parse error {e}")
            continue
        mid = run.get("modelId", "")
        try:
            expected = bmi_class_for(mid)
        except ValueError as e:
            errors.append(f"{path}: {e}")
            continue
        existing = run.get("bmi_class")
        existing_mmb = run.get("mmb")
        # The backfill only manages the country-rollup mmb blocks. For nodes
        # it doesn't manage (e.g. the FRB/US external node, whose mmb is
        # authored by frbus_node.py), preserve any existing block rather
        # than stripping it.
        expected_mmb = mmb_block_for(mid)
        if expected_mmb is None:
            expected_mmb = existing_mmb
        if existing == expected and existing_mmb == expected_mmb:
            correct += 1
            continue
        changed += 1
        if not check:
            new_run = _with_bmi_class(run, expected, expected_mmb)
            write_json(path, new_run)

    print(
        f"{'would change' if check else 'changed'}: {changed}; "
        f"already correct: {correct}; total: {len(run_files)}"
    )
    if errors:
        print(f"{len(errors)} error(s):")
        for e in errors[:20]:
            print(f"  - {e}")
        return 1
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="bmi.backfill_bmi_class", description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--check", action="store_true", help="dry-run; report only")
    args = parser.parse_args(argv)
    return backfill(args.root, check=args.check)


if __name__ == "__main__":
    sys.exit(main())
