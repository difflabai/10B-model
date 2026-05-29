"""`Bmi10BBase` — the registry-aware Basic Model Interface base class.

Every 10B model node (cell, rollup, head, forecast, external wrapper) is a
subclass of `Bmi10BBase`. The base carries everything the nodes share:

  - resolving the registry root (via `_paths`),
  - loading `model.meta.json` + `model.run.json` on `initialize()`,
  - answering all BMI introspection (vars, grids, time) from the
    subclass's `INPUT_VARS` / `OUTPUT_VARS` declarations and the central
    standard-name + grid registries,
  - holding computed values and serving them through `get_value`.

Subclasses override only the substantive bits: `INPUT_VARS`,
`OUTPUT_VARS`, `_grid_for`, and `_compute` (which recomputes — or, in the
no-op phase, reads the already-materialised `runs/output.json`).

`bmipy` is an optional dependency. When it is installed we subclass the
real `bmipy.Bmi` for true conformance; otherwise we fall back to a local
abstract base with the same surface so the package works in a plain
checkout with no extra installs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

import sys as _sys

_sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _paths import tenb_root  # noqa: E402

from . import grids as _grids  # noqa: E402
from . import standard_names as _sn  # noqa: E402

try:  # pragma: no cover - exercised only where bmipy is installed
    from bmipy import Bmi as _BmiABC

    HAVE_BMIPY = True
except Exception:  # bmipy not installed — use a local stand-in
    HAVE_BMIPY = False

    class _BmiABC:  # minimal stand-in; Bmi10BBase implements the full surface
        pass


class BmiDependencyMissing(ImportError):
    """Raised when a BMI node needs an optional runtime that is not
    installed (e.g. the FRB/US `pyfrbus` package). Carries an actionable
    install hint. The coupler catches this and logs the node as skipped.
    """


class Bmi10BBase(_BmiABC):
    """Registry-aware BMI base for 10B model nodes."""

    # Subclasses declare the standard names they consume / produce. Long
    # CSDMS names (or MMB short aliases, which `resolve` follows).
    INPUT_VARS: Tuple[str, ...] = ()
    OUTPUT_VARS: Tuple[str, ...] = ()

    # Human-facing component name; subclasses may override.
    COMPONENT_NAME = "10B model node"

    # One quarter / one pipeline epoch in seconds; non-temporal nodes
    # report a zero time step (steady state, per BMI best practice).
    _STEADY_STATE = True
    _TIME_STEP_SECONDS = 0.0

    def __init__(self) -> None:
        self._initialized = False
        self._meta: Dict[str, Any] = {}
        self._run: Dict[str, Any] = {}
        self._model_dir: Optional[Path] = None
        self._model_id: str = ""
        # Computed values, keyed by canonical (resolved) standard name.
        self._values: Dict[str, np.ndarray] = {}
        # String-typed outputs live here (BMI numeric get_value can't carry
        # them); served via get_value_text. Keyed by canonical name.
        self._text_values: Dict[str, Any] = {}
        self._current_time = 0.0

    # ------------------------------------------------------------------ #
    # Control functions
    # ------------------------------------------------------------------ #
    def initialize(self, config_file: str) -> None:
        """Load this node's `model.run.json` (the config_file) and its
        sibling `model.meta.json`. Does not recompute — call `update()`
        for that.
        """
        run_path = Path(config_file)
        if run_path.is_dir():
            run_path = run_path / "model.run.json"
        self._model_dir = run_path.parent
        self._run = json.loads(run_path.read_text(encoding="utf-8"))
        self._model_id = self._run.get("modelId", "")
        meta_path = run_path.parent / "model.meta.json"
        if meta_path.exists():
            self._meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self._initialized = True

    def update(self) -> None:
        """Recompute outputs from current inputs. The base delegates to
        `_compute`; the no-op subclasses read the materialised output file.
        """
        self._require_init()
        self._compute()

    def update_until(self, time: float) -> None:
        """Advance to `time`. Non-temporal (steady-state) nodes treat this
        as a single `update()`; temporal nodes (forecasts) override.
        """
        self.update()
        self._current_time = time

    def finalize(self) -> None:
        """Release resources. The no-op nodes hold nothing; subclasses that
        write outputs override to flush atomically.
        """
        self._values.clear()
        self._text_values.clear()
        self._initialized = False

    def _compute(self) -> None:
        """Populate `self._values` / `self._text_values`. The base raises;
        every concrete subclass overrides.
        """
        raise NotImplementedError(
            f"{type(self).__name__}._compute is not implemented"
        )

    # ------------------------------------------------------------------ #
    # Model information
    # ------------------------------------------------------------------ #
    def get_component_name(self) -> str:
        return self._meta.get("name", self.COMPONENT_NAME)

    def get_input_item_count(self) -> int:
        return len(self.INPUT_VARS)

    def get_output_item_count(self) -> int:
        return len(self.OUTPUT_VARS)

    def get_input_var_names(self) -> Tuple[str, ...]:
        return tuple(_sn.resolve(n) for n in self.INPUT_VARS)

    def get_output_var_names(self) -> Tuple[str, ...]:
        return tuple(_sn.resolve(n) for n in self.OUTPUT_VARS)

    # ------------------------------------------------------------------ #
    # Variable information
    # ------------------------------------------------------------------ #
    def _spec(self, name: str) -> _sn.StandardName:
        return _sn.get(name)

    def get_var_grid(self, name: str) -> int:
        return self._grid_for(_sn.resolve(name))

    def get_var_type(self, name: str) -> str:
        return self._spec(name).dtype

    def get_var_units(self, name: str) -> str:
        return self._spec(name).units

    def get_var_itemsize(self, name: str) -> int:
        dtype = self._spec(name).dtype
        if dtype == "str":
            return 0  # strings are served out-of-band via get_value_text
        return int(np.dtype(dtype).itemsize)

    def get_var_nbytes(self, name: str) -> int:
        return self.get_var_itemsize(name) * _grids.grid_size(
            self.get_var_grid(name), k=self._k(), horizon=self._horizon()
        )

    def get_var_location(self, name: str) -> str:
        # 10B has no edge/face-located data in the BMI sense; the peer graph
        # is exposed through get_grid_edge_* rather than a var location.
        return "node"

    def _grid_for(self, name: str) -> int:
        """Grid id for a (resolved) standard name. Subclasses override; the
        base default is a single scalar grid.
        """
        return _grids.SCALAR

    # ------------------------------------------------------------------ #
    # Getters / setters
    # ------------------------------------------------------------------ #
    def get_value(self, name: str, dest: np.ndarray) -> np.ndarray:
        canonical = _sn.resolve(name)
        if canonical in self._values:
            dest[:] = self._values[canonical].ravel()[: dest.size]
        else:
            dest[:] = np.nan
        return dest

    def get_value_ptr(self, name: str) -> np.ndarray:
        canonical = _sn.resolve(name)
        if canonical not in self._values:
            raise KeyError(f"no computed value for {canonical!r}; call update()")
        return self._values[canonical]

    def get_value_at_indices(
        self, name: str, dest: np.ndarray, inds: np.ndarray
    ) -> np.ndarray:
        canonical = _sn.resolve(name)
        src = self._values.get(canonical)
        if src is None:
            dest[:] = np.nan
            return dest
        flat = src.ravel()
        dest[:] = flat[np.asarray(inds)]
        return dest

    def get_value_text(self, name: str):
        """10B extension: return a string-typed output (agent surfaces,
        summaries). BMI's numeric get_value cannot carry strings.
        """
        return self._text_values.get(_sn.resolve(name))

    def set_value(self, name: str, src: np.ndarray) -> None:
        canonical = _sn.resolve(name)
        self._values[canonical] = np.asarray(src).copy()

    def set_value_at_indices(
        self, name: str, inds: np.ndarray, src: np.ndarray
    ) -> None:
        canonical = _sn.resolve(name)
        if canonical not in self._values:
            raise KeyError(f"no array to index into for {canonical!r}")
        self._values[canonical].ravel()[np.asarray(inds)] = np.asarray(src)

    # ------------------------------------------------------------------ #
    # Time functions
    # ------------------------------------------------------------------ #
    def get_current_time(self) -> float:
        return self._current_time

    def get_start_time(self) -> float:
        return 0.0

    def get_end_time(self) -> float:
        return 0.0

    def get_time_units(self) -> str:
        return "s"

    def get_time_step(self) -> float:
        return self._TIME_STEP_SECONDS

    # ------------------------------------------------------------------ #
    # Grid functions
    # ------------------------------------------------------------------ #
    def _k(self) -> Optional[int]:
        """Cluster count for unstructured grids; None unless overridden."""
        return None

    def _horizon(self) -> Optional[int]:
        """Forecast horizon length for the time grid; None unless overridden."""
        return None

    def get_grid_rank(self, grid: int) -> int:
        return _grids.GRIDS[grid].rank

    def get_grid_size(self, grid: int) -> int:
        return _grids.grid_size(grid, k=self._k(), horizon=self._horizon())

    def get_grid_type(self, grid: int) -> str:
        return _grids.GRIDS[grid].grid_type

    def get_grid_shape(self, grid: int, shape: np.ndarray) -> np.ndarray:
        s = _grids.grid_shape(grid, k=self._k(), horizon=self._horizon())
        shape[:] = np.asarray(s, dtype=shape.dtype)[: shape.size]
        return shape

    def get_grid_spacing(self, grid: int, spacing: np.ndarray) -> np.ndarray:
        spacing[:] = np.nan
        return spacing

    def get_grid_origin(self, grid: int, origin: np.ndarray) -> np.ndarray:
        origin[:] = np.nan
        return origin

    def get_grid_x(self, grid: int, x: np.ndarray) -> np.ndarray:
        if grid == _grids.COUNTRY_POINTS:
            lons = [_grids.country_xy(s)[0] for s in _grids.country_slugs()]
            x[:] = np.asarray(lons, dtype=x.dtype)[: x.size]
        else:
            x[:] = np.nan
        return x

    def get_grid_y(self, grid: int, y: np.ndarray) -> np.ndarray:
        if grid == _grids.COUNTRY_POINTS:
            lats = [_grids.country_xy(s)[1] for s in _grids.country_slugs()]
            y[:] = np.asarray(lats, dtype=y.dtype)[: y.size]
        else:
            y[:] = np.nan
        return y

    def get_grid_z(self, grid: int, z: np.ndarray) -> np.ndarray:
        z[:] = np.nan
        return z

    def get_grid_node_count(self, grid: int) -> int:
        return self.get_grid_size(grid)

    def get_grid_edge_count(self, grid: int) -> int:
        return 0

    def get_grid_face_count(self, grid: int) -> int:
        return 0

    def get_grid_edge_nodes(self, grid: int, edge_nodes: np.ndarray) -> np.ndarray:
        return edge_nodes

    def get_grid_face_edges(self, grid: int, face_edges: np.ndarray) -> np.ndarray:
        return face_edges

    def get_grid_face_nodes(self, grid: int, face_nodes: np.ndarray) -> np.ndarray:
        return face_nodes

    def get_grid_nodes_per_face(
        self, grid: int, nodes_per_face: np.ndarray
    ) -> np.ndarray:
        return nodes_per_face

    # ------------------------------------------------------------------ #
    # 10B-internal helpers
    # ------------------------------------------------------------------ #
    @property
    def model_id(self) -> str:
        return self._model_id

    def _require_init(self) -> None:
        if not self._initialized:
            raise RuntimeError(
                f"{type(self).__name__}: initialize() must be called first"
            )

    def _read_output(self, filename: str = "runs/output.json") -> Dict[str, Any]:
        """Read a materialised output file relative to this node's directory.
        Returns {} when the file is absent (model not yet run).
        """
        if self._model_dir is None:
            return {}
        path = self._model_dir / filename
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
