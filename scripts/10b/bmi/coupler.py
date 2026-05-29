"""The 10B BMI coupler — execution ordering + introspection over the registry.

In this phase the coupler is a dry-run / introspection tool: it derives the
execution order, audits the registry's dependency edges against it, and can
print the BMI surface of any node. Phase E promotes it to the production
runner that replaces `pipeline.sh`.

Execution order is derived at *class* granularity from `CLASS_DEPS` (the
authoritative data-flow DAG, matching the order `pipeline.sh` runs the
scripts), not by topologically sorting the node-level `depends_on` edges.
The node edges contain a deliberate back-reference — each cell declares
`consumes_from` its category rollup as an "aggregates this model"
annotation — which would otherwise form a cycle. `audit_edges` cross-checks
the node edges against the class order and reports genuine violations,
treating that known annotation as expected.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_sys_path = str(Path(__file__).resolve().parent.parent)
if _sys_path not in sys.path:
    sys.path.insert(0, _sys_path)

from _paths import registry_root, tenb_root  # noqa: E402

from .base import BmiDependencyMissing  # noqa: E402
from .classmap import bmi_class_for, load_bmi  # noqa: E402

# The production pipeline, as an ordered list of (label, argv) steps. The
# coupler `run` mode executes exactly these — the same scripts pipeline.sh
# has always run, in dependency order — so its output is byte-for-byte
# identical to the legacy sequence. New BMI steps (FRB/US node + the
# top-level registry) slot in before the manifest.
PIPELINE_STEPS: List[Tuple[str, List[str]]] = [
    ("generate per-cell + rollup metadata", ["scripts/10b/generate.py"]),
    ("closed-form scorer", ["scripts/10b/scorer.py"]),
    ("dynamics / supervised / agent metas", ["scripts/10b/extra_models.py"]),
    ("k-means macro-dynamics", ["scripts/10b/dynamics.py", "6"]),
    ("personal-agent context", ["scripts/10b/agent_context.py"]),
    ("regional rollups", ["scripts/10b/regions.py"]),
    ("forecasts", ["scripts/10b/forecasts.py"]),
    ("FRB/US external node", ["-m", "bmi.external.frbus_node"]),
    ("top-level model registry", ["-m", "bmi.model_registry"]),
    ("manifest", ["scripts/10b/manifest.py"]),
    ("validation", ["scripts/10b/validate.py"]),
]

# Class-level data-flow DAG: class -> classes it depends on (must run first).
# This mirrors pipeline.sh's step ordering.
CLASS_DEPS: Dict[str, Tuple[str, ...]] = {
    "SchemaBmi": (),
    # External macro backings run first (no in-registry prerequisites).
    "FrbusBmi": (),
    "CellBmi": ("SchemaBmi",),
    "CountryRollupBmi": ("CellBmi",),
    # MMB-compliant country rollups also wait on their macro backing.
    "MmbCountryRollupBmi": ("CellBmi", "FrbusBmi"),
    "CategoryWorldBmi": ("CellBmi",),
    "RegionRollupBmi": ("CellBmi", "CountryRollupBmi", "MmbCountryRollupBmi"),
    "MacroBmi": ("CountryRollupBmi", "MmbCountryRollupBmi", "CategoryWorldBmi"),
    "DynamicsBmi": ("MacroBmi",),
    "SupervisedBmi": ("MacroBmi",),
    "PersonalAgentBmi": ("CountryRollupBmi", "MmbCountryRollupBmi", "DynamicsBmi"),
    "ForecastBmi": ("MacroBmi",),
}


@dataclass
class Node:
    model_id: str
    run_path: Path
    bmi_class: str
    depends_on: List[dict] = field(default_factory=list)

    @property
    def class_name(self) -> str:
        return self.bmi_class.split(":", 1)[1]


def iter_nodes(root: Optional[Path] = None) -> List[Node]:
    """Walk the registry, returning one Node per `model.run.json`."""
    base = root or tenb_root()
    nodes: List[Node] = []
    for run_path in base.rglob("model.run.json"):
        try:
            run = json.loads(run_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        mid = run.get("modelId", "")
        bmi_class = run.get("bmi_class") or _safe_class_for(mid)
        meta_path = run_path.parent / "model.meta.json"
        deps: List[dict] = []
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                deps = meta.get("depends_on", []) or []
            except Exception:
                deps = []
        nodes.append(Node(mid, run_path, bmi_class, deps))
    return nodes


def _safe_class_for(model_id: str) -> str:
    try:
        return bmi_class_for(model_id)
    except ValueError:
        return ""


def class_execution_order() -> List[str]:
    """Topologically sort the BMI classes by `CLASS_DEPS` (prerequisites
    first). Deterministic: ties break alphabetically.
    """
    order: List[str] = []
    visited: Dict[str, int] = {}  # 0=visiting, 1=done

    def visit(cls: str) -> None:
        state = visited.get(cls)
        if state == 1:
            return
        if state == 0:
            raise ValueError(f"cycle in CLASS_DEPS at {cls}")
        visited[cls] = 0
        for prereq in sorted(CLASS_DEPS.get(cls, ())):
            visit(prereq)
        visited[cls] = 1
        order.append(cls)

    for cls in sorted(CLASS_DEPS):
        visit(cls)
    return order


def _is_aggregation_backref(node: Node, edge: dict) -> bool:
    """True for the known cell→category 'aggregates this model' annotation,
    which is a back-reference rather than a data dependency.
    """
    note = (edge.get("note") or "").lower()
    return node.class_name == "CellBmi" and "aggregates this model" in note


def audit_edges(nodes: List[Node]) -> List[str]:
    """Cross-check node `depends_on` edges against the class execution order.

    For a real data dependency (`consumes_from` / `depends_on`), the target's
    class must execute no later than the consumer's class. Returns a list of
    human-readable violation strings (empty when consistent).
    """
    order = class_execution_order()
    rank = {cls: i for i, cls in enumerate(order)}
    by_id = {n.model_id: n for n in nodes}
    violations: List[str] = []

    for node in nodes:
        if node.class_name not in rank:
            continue
        for edge in node.depends_on:
            if edge.get("kind") not in ("consumes_from", "depends_on"):
                continue
            if _is_aggregation_backref(node, edge):
                continue
            target_id = edge.get("target_model_id")
            target = by_id.get(target_id)
            if target is None or target.class_name not in rank:
                continue
            if rank[target.class_name] > rank[node.class_name]:
                violations.append(
                    f"{node.model_id} ({node.class_name}) depends on "
                    f"{target_id} ({target.class_name}) which runs later"
                )
    return violations


def dry_run(root: Optional[Path] = None) -> int:
    nodes = iter_nodes(root)
    order = class_execution_order()
    counts: Dict[str, int] = {}
    missing_class = 0
    for n in nodes:
        if not n.bmi_class:
            missing_class += 1
            continue
        counts[n.class_name] = counts.get(n.class_name, 0) + 1

    print(f"registry: {len(nodes)} nodes under {root or tenb_root()}")
    print("execution order (class granularity):")
    for cls in order:
        if counts.get(cls):
            print(f"  {cls:22s} {counts.get(cls, 0):5d} nodes")
    # Surface any classes not in the execution DAG so nothing is hidden.
    extra = sorted(set(counts) - set(order))
    for cls in extra:
        print(f"  {cls:22s} {counts[cls]:5d} nodes  (not in execution DAG)")
    if missing_class:
        print(f"  WARNING: {missing_class} nodes have no bmi_class")

    violations = audit_edges(nodes)
    if violations:
        print(f"\n{len(violations)} dependency-order violation(s):")
        for v in violations[:20]:
            print(f"  - {v}")
        return 1
    print("\nall dependency edges respect the class execution order")
    return 0


def mmb_nodes(root: Optional[Path] = None) -> List[dict]:
    """Return the MMB-compliant nodes (those whose run.json has an mmb block)
    with their capabilities. Used for cross-rule comparison planning.
    """
    base = root or tenb_root()
    out: List[dict] = []
    for run_path in base.rglob("model.run.json"):
        try:
            run = json.loads(run_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        mmb = run.get("mmb")
        if not mmb:
            continue
        out.append({
            "model_id": run.get("modelId", ""),
            "capabilities": mmb.get("capabilities", []),
        })
    out.sort(key=lambda d: d["model_id"])
    return out


def rule_plan(rules: List[str], root: Optional[Path] = None) -> int:
    """Report which MMB-compliant nodes would be re-simulated under each
    requested policy rule (dry-run for the cross-rule comparison flow).
    """
    nodes = mmb_nodes(root)
    if not nodes:
        print("no MMB-compliant nodes found")
        return 0
    print(f"{len(nodes)} MMB-compliant node(s):")
    for n in nodes:
        print(f"  {n['model_id']}  caps={n['capabilities']}")
    print()
    for rule in rules:
        applicable = [n["model_id"] for n in nodes if rule in n["capabilities"]]
        skipped = [n["model_id"] for n in nodes if rule not in n["capabilities"]]
        print(f"rule {rule}: would re-run {len(applicable)} node(s)")
        for mid in applicable:
            print(f"  + {mid}")
        for mid in skipped:
            print(f"  - {mid} (rule not in capabilities)")
    return 0


def inspect(model_id: str, root: Optional[Path] = None) -> int:
    """Instantiate the BMI node for a model id and print its BMI surface."""
    base = root or tenb_root()
    target = None
    for run_path in base.rglob("model.run.json"):
        try:
            run = json.loads(run_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if run.get("modelId") == model_id:
            target = (run_path, run)
            break
    if target is None:
        print(f"model id not found: {model_id}")
        return 1

    run_path, run = target
    bmi_class = run.get("bmi_class") or bmi_class_for(model_id)
    cls = load_bmi(bmi_class)
    inst = cls()
    try:
        inst.initialize(str(run_path))
    except BmiDependencyMissing:
        # Introspection doesn't need the optional runtime (e.g. pyfrbus for
        # FRB/US) — load metadata only via the runtime-free base initialize.
        from .base import Bmi10BBase

        Bmi10BBase.initialize(inst, str(run_path))

    print(f"model id:   {model_id}")
    print(f"bmi_class:  {bmi_class}")
    print(f"component:  {inst.get_component_name()}")
    print(f"inputs  ({inst.get_input_item_count()}):")
    for name in inst.get_input_var_names():
        print(f"  - {name:50s} grid={inst.get_var_grid(name)} "
              f"type={inst.get_var_type(name)} units={inst.get_var_units(name)}")
    print(f"outputs ({inst.get_output_item_count()}):")
    for name in inst.get_output_var_names():
        print(f"  - {name:50s} grid={inst.get_var_grid(name)} "
              f"type={inst.get_var_type(name)} units={inst.get_var_units(name)}")
    return 0


def _pipeline_env() -> dict:
    """Environment for pipeline subprocesses: ensure scripts/10b is on
    PYTHONPATH (for the `bmi` package) and prepend a vendored pyfrbus/ when
    present so the FRB/US wrapper can import it.
    """
    rroot = registry_root()
    env = dict(os.environ)
    paths = ["scripts/10b"]
    pyfrbus_dir = rroot / "pyfrbus"
    if pyfrbus_dir.is_dir():
        paths.append(str(pyfrbus_dir))
    existing = env.get("PYTHONPATH")
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def run(root: Optional[Path] = None, *, plan_only: bool = False) -> int:
    """Production runner: execute the pipeline steps in dependency order.

    Sequences the existing generation scripts (byte-faithful to the legacy
    `pipeline.sh`) plus the new FRB/US-node and model-registry steps. The
    byte-for-byte equivalence to `--legacy` is the migration's acceptance
    gate; with `plan_only` it prints the step list without executing.
    """
    rroot = registry_root()
    print(f"10B pipeline (coupler) — root {rroot}")
    for i, (label, argv) in enumerate(PIPELINE_STEPS, 1):
        cmd = [sys.executable] + argv
        print(f"  [{i}/{len(PIPELINE_STEPS)}] {label}: {' '.join(argv)}")
        if plan_only:
            continue
        result = subprocess.run(cmd, cwd=str(rroot), env=_pipeline_env())
        if result.returncode != 0:
            print(f"FAIL at step {i} ({label}): exit {result.returncode}")
            return result.returncode
    if not plan_only:
        print("pipeline complete.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="bmi.coupler", description=__doc__)
    parser.add_argument("--root", type=Path, default=None,
                        help="registry root (defaults to tenb_root())")
    parser.add_argument("--dry-run", action="store_true",
                        help="print execution order and audit dependency edges")
    parser.add_argument("--inspect", metavar="MODEL_ID", default=None,
                        help="print the BMI surface of one node")
    parser.add_argument("--rule", metavar="RULES", default=None,
                        help="comma-separated MMB policy rules; report which "
                             "MMB-compliant nodes each would re-simulate")
    parser.add_argument("run", nargs="?", default=None,
                        help="'run' executes the full pipeline (production runner)")
    parser.add_argument("--plan", action="store_true",
                        help="with run: print the step list without executing")
    args = parser.parse_args(argv)

    if args.inspect:
        return inspect(args.inspect, args.root)
    if args.rule:
        return rule_plan([r.strip() for r in args.rule.split(",") if r.strip()],
                         args.root)
    if args.run == "run":
        return run(args.root, plan_only=args.plan)
    # Default action is the dry-run topology audit.
    return dry_run(args.root)


if __name__ == "__main__":
    sys.exit(main())
