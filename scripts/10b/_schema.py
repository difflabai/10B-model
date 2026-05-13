"""Shared schema-construction helpers for the 10B pipeline scripts.

Every script that emits a `model.meta.json` builds the same shapes —
I/O ports, references, parameter rows, components, dependency edges —
plus a tiny JSON-write helper. Keeping the constructors here means a
schema tweak (e.g. adding a field to `component`) lands in exactly
one place instead of three.

The names are deliberately spelled out (`io_spec`, `reference`,
`parameter_row`, `component`) rather than abbreviated to two-letter
forms; readability at call sites is worth more than typing speed in
4,000-line generators.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


def io_spec(name: str, kind: str, description: str) -> Dict[str, str]:
    """One I/O port on a model (input or output): name + kind + free-text
    description. Matches the `IoSpec` shape on the Rust side.
    """
    return {"name": name, "kind": kind, "description": description}


def reference(label: str, kind: str, location: str) -> Dict[str, str]:
    """One external reference (paper / spec / crate / URL) attached to a
    model. `kind` is one of the `ReferenceKind` enum values.
    """
    return {"label": label, "kind": kind, "location": location}


def parameter_row(
    key: str, value: str, description: str | None = None
) -> Dict[str, Any]:
    """One parameter-table row. `description` is omitted from the dict
    when None so the materialised JSON stays minimal.
    """
    row: Dict[str, Any] = {"key": key, "value": value}
    if description is not None:
        row["description"] = description
    return row


def component(
    cid: str,
    name: str,
    role: str,
    key_symbols: List[str] | None = None,
) -> Dict[str, Any]:
    """One sub-component of a model (e.g. "Equilibrium solver"). The
    `crate_path` field is always None for Python-generated models —
    it's populated only by Rust-side metas that point at a real source
    location.
    """
    return {
        "id": cid,
        "name": name,
        "role": role,
        "crate_path": None,
        "key_symbols": key_symbols or [],
    }


def dep(target_model_id: str, kind: str, note: str) -> Dict[str, Any]:
    """One model-to-model dependency edge. `kind` is one of the
    `RelationshipKind` enum values (e.g. `depends_on`, `consumes_from`).
    """
    return {"target_model_id": target_model_id, "kind": kind, "note": note}


def write_json(path: Path, data: Any) -> None:
    """Atomic-enough JSON write with `mkdir -p`, pretty-printed, UTF-8,
    trailing newline. The single point of truth for how every pipeline
    output gets serialised — keeps every model.meta.json / model.run.json
    diffable across runs.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
