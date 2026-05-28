"""`python -m bmi.cli` — read-only BMI introspection over the 10B registry.

Subcommands:
  inspect <model_id>   print a node's BMI variable + grid surface
  names                list the registered standard names
  grids                list the grid taxonomy

Run with `scripts/10b/` on PYTHONPATH (the pipeline convention), e.g.:
    PYTHONPATH=scripts/10b python -m bmi.cli inspect global.10B.countries.india.health
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_sys_path = str(Path(__file__).resolve().parent.parent)
if _sys_path not in sys.path:
    sys.path.insert(0, _sys_path)

from bmi import grids as _grids  # noqa: E402
from bmi import standard_names as _sn  # noqa: E402
from bmi.coupler import inspect as _inspect  # noqa: E402


def _cmd_names() -> int:
    for name in sorted(_sn.STANDARD_NAMES):
        spec = _sn.STANDARD_NAMES[name]
        ext = " (external)" if spec.external else ""
        print(f"{name:52s} {spec.dtype:8s} {spec.units:10s}{ext}")
    print("\nMMB aliases:")
    for short, long in _sn.MMB_ALIASES.items():
        print(f"  {short:12s} -> {long}")
    return 0


def _cmd_grids() -> int:
    for gid in sorted(_grids.GRIDS):
        d = _grids.GRIDS[gid]
        print(f"grid {gid}: {d.grid_type:20s} rank={d.rank} "
              f"xy={d.has_xy} edges={d.has_edges}")
    print(f"\ncountry_count() = {_grids.country_count()}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="bmi.cli", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_inspect = sub.add_parser("inspect", help="inspect one model node")
    p_inspect.add_argument("model_id")
    p_inspect.add_argument("--root", type=Path, default=None)

    sub.add_parser("names", help="list registered standard names")
    sub.add_parser("grids", help="list the grid taxonomy")

    args = parser.parse_args(argv)
    if args.cmd == "inspect":
        return _inspect(args.model_id, args.root)
    if args.cmd == "names":
        return _cmd_names()
    if args.cmd == "grids":
        return _cmd_grids()
    return 1


if __name__ == "__main__":
    sys.exit(main())
