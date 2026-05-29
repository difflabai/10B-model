"""SchemaBmi — the needs-tree schema node.

A schema-only model: zero inputs, one string output (the needs-tree
document). `_compute` rereads `needs-tree.json`; `update` is effectively a
no-op since the schema is static.
"""

from __future__ import annotations

import json

from .base import Bmi10BBase
from . import grids as _grids


class SchemaBmi(Bmi10BBase):
    COMPONENT_NAME = "10B needs tree (schema)"

    INPUT_VARS = ()
    OUTPUT_VARS = ("schema__needs_tree",)

    def _grid_for(self, name: str) -> int:
        return _grids.SCALAR

    def _compute(self) -> None:
        # The schema document is the needs-tree, one level up from schema/.
        from _paths import tenb_root

        path = tenb_root() / "needs-tree.json"
        if path.exists():
            self._text_values["schema__needs_tree"] = path.read_text(encoding="utf-8")
